"""MVP-005 — projets : création, rattachement, validations métier, pagination, N+1."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import ActivityLog
from apps.organizations.models import OrganizationMember
from apps.projects.models import Project, ProjectMember
from apps.users.roles import Role

VALID_PAYLOAD = {
    "name": "Immeuble Akwa — tranche 2",
    "code": "AKW-T2",
    "description": "8 appartements, 4 niveaux",
    "location_label": "Akwa, rue Castelnau",
    "city": "Douala",
    "region": "Littoral",
    "latitude": "4.051100",
    "longitude": "9.767900",
    "budget_total": 85000000,
    "status": "ACTIVE",
    "planned_start_date": "2026-02-01",
    "planned_end_date": "2027-01-31",
}


@pytest.mark.django_db
def test_authorized_user_creates_project(auth_client, organization):
    client = auth_client(organization.owner)
    response = client.post(
        "/api/projects/", {**VALID_PAYLOAD, "organization": organization.id}, format="json"
    )
    assert response.status_code == 201, response.content

    project = Project.objects.get(code="AKW-T2")
    assert project.organization_id == organization.id, (
        "Un projet appartient toujours à une organisation."
    )
    assert project.currency == "XAF"
    assert project.budget_total == Decimal("85000000")
    assert project.status == "ACTIVE"
    assert project.created_by_id == organization.owner_id
    assert project.progress == Decimal("0")  # calculé côté serveur (phase 4)

    # Le créateur devient responsable du projet.
    membership = ProjectMember.objects.get(project=project, user=organization.owner)
    assert membership.role == Role.PROJECT_OWNER
    assert membership.can_validate_evidence and membership.can_manage_finance

    entry = ActivityLog.objects.filter(action="PROJECT_CREATED", project=project).first()
    assert entry is not None
    assert entry.organization_id == organization.id
    assert entry.metadata["budget_total"] == 85000000


@pytest.mark.django_db
def test_project_cannot_be_created_in_a_foreign_organization(auth_client, organization, make_user):
    outsider = make_user(Role.ORG_OWNER, phone_number="+237699222333")
    response = auth_client(outsider).post(
        "/api/projects/", {**VALID_PAYLOAD, "organization": organization.id}, format="json"
    )
    assert response.status_code == 400
    assert "organization" in response.data["error"]["details"]
    assert Project.objects.count() == 0


@pytest.mark.django_db
def test_investor_cannot_create_project(auth_client, organization, make_user):
    investor = make_user(Role.INVESTOR)
    OrganizationMember.objects.create(organization=organization, user=investor, role=Role.INVESTOR)
    response = auth_client(investor).post(
        "/api/projects/", {**VALID_PAYLOAD, "organization": organization.id}, format="json"
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,expected_code",
    [
        (
            {"planned_start_date": "2027-03-01", "planned_end_date": "2027-01-01"},
            "dates_inconsistent",
        ),
        (
            {"actual_start_date": "2027-03-01", "actual_end_date": "2027-01-01"},
            "dates_inconsistent",
        ),
        ({"budget_total": "85000000.50"}, "amount_has_cents"),
        ({"budget_total": -1}, "amount_invalid"),
        ({"currency": "EUR"}, "currency_not_supported"),
        ({"status": "INCONNU"}, "validation_error"),
    ],
)
def test_invalid_project_payloads_are_refused(auth_client, organization, overrides, expected_code):
    response = auth_client(organization.owner).post(
        "/api/projects/",
        {**VALID_PAYLOAD, **overrides, "organization": organization.id},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert response.data["error"]["code"] == expected_code
    assert Project.objects.count() == 0


@pytest.mark.django_db
def test_project_code_is_unique_within_organization(auth_client, organization):
    client = auth_client(organization.owner)
    assert (
        client.post(
            "/api/projects/", {**VALID_PAYLOAD, "organization": organization.id}, format="json"
        ).status_code
        == 201
    )

    duplicate = client.post(
        "/api/projects/",
        {**VALID_PAYLOAD, "name": "Autre nom", "organization": organization.id},
        format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.data["error"]["code"] == "project_code_taken"


@pytest.mark.django_db
def test_project_list_only_contains_authorized_projects(auth_client, project_context, project):
    members = project_context
    owner_view = auth_client(members["owner"]).get("/api/projects/")
    stranger_view = auth_client(members["stranger"]).get("/api/projects/")

    assert [item["id"] for item in owner_view.data["results"]] == [project.id]
    assert stranger_view.data["results"] == [], "Un non-membre ne doit rien voir."


@pytest.mark.django_db
def test_project_detail_is_not_found_for_non_member(auth_client, project_context, project):
    response = auth_client(project_context["stranger"]).get(f"/api/projects/{project.id}/")
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_project_detail_exposes_backend_permissions(auth_client, project_context, project):
    investor = auth_client(project_context["investor"]).get(f"/api/projects/{project.id}/")
    assert investor.status_code == 200
    assert investor.data["permissions"] == {
        "edit_project": False,
        "archive_project": False,
        "manage_members": False,
        "capture_evidence": False,
        "validate_evidence": False,
        "view_finance": True,
        "manage_finance": False,
    }

    engineer = auth_client(project_context["engineer"]).get(f"/api/projects/{project.id}/")
    assert engineer.data["permissions"]["capture_evidence"] is True
    assert engineer.data["permissions"]["validate_evidence"] is False
    assert engineer.data["permissions"]["manage_finance"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "actor,expected_status",
    [
        ("owner", 200),
        ("engineer", 403),  # visible mais modification interdite → 403
        ("agent", 403),
        ("investor", 403),
        ("stranger", 404),  # hors périmètre → 404
    ],
)
def test_project_update_permissions(auth_client, project_context, project, actor, expected_status):
    client = auth_client(project_context[actor])
    response = client.patch(f"/api/projects/{project.id}/", {"city": "Kribi"}, format="json")
    assert response.status_code == expected_status, response.content
    if expected_status == 200:
        assert response.data["city"] == "Kribi"
    else:
        project.refresh_from_db()
        assert project.city == "Douala"


@pytest.mark.django_db
def test_project_update_is_journalised_with_old_and_new_values(
    auth_client, project_context, project
):
    response = auth_client(project_context["owner"]).patch(
        f"/api/projects/{project.id}/",
        {"budget_total": 60000000, "status": "ON_HOLD"},
        format="json",
    )
    assert response.status_code == 200

    entry = ActivityLog.objects.get(action="PROJECT_UPDATED", project=project)
    assert entry.metadata["changed"]["budget_total"] == {"old": 50000000, "new": 60000000}
    assert entry.metadata["changed"]["status"] == {"old": "ACTIVE", "new": "ON_HOLD"}


@pytest.mark.django_db
def test_progress_is_read_only_for_clients(auth_client, project_context, project):
    response = auth_client(project_context["owner"]).patch(
        f"/api/projects/{project.id}/", {"progress": "95.00"}, format="json"
    )
    assert response.status_code == 200
    project.refresh_from_db()
    assert project.progress == Decimal("0"), "L'avancement est toujours calculé côté serveur."


@pytest.mark.django_db
def test_project_archiving_is_controlled_and_journalised(auth_client, project_context, project):
    assert (
        auth_client(project_context["engineer"]).delete(f"/api/projects/{project.id}/").status_code
        == 403
    )

    response = auth_client(project_context["owner"]).delete(f"/api/projects/{project.id}/")
    assert response.status_code == 204

    assert not Project.objects.filter(pk=project.pk).exists()
    archived = Project.all_objects.get(pk=project.pk)
    assert archived.deleted_at is not None
    assert archived.status == "ARCHIVED"
    assert ActivityLog.objects.filter(action="PROJECT_ARCHIVED", project=project).exists()


@pytest.mark.django_db
def test_project_filters(auth_client, project_context, project, organization, make_user):
    other_owner = make_user(Role.PROJECT_OWNER, phone_number="+237699333444")
    other = Project.objects.create(
        organization=organization,
        name="Entrepôt Bonabéri",
        code="BNB-01",
        city="Douala",
        budget_total=12000000,
        status="DRAFT",
        created_by=other_owner,
    )
    ProjectMember.objects.create(project=other, user=other_owner, role=Role.PROJECT_OWNER)
    # Le propriétaire de l'organisation voit les deux (périmètre d'organisation).
    client = auth_client(organization.owner)

    assert len(client.get("/api/projects/").data["results"]) == 2
    assert [item["code"] for item in client.get("/api/projects/?status=draft").data["results"]] == [
        "BNB-01"
    ]
    assert [
        item["code"] for item in client.get("/api/projects/?search=entrepôt").data["results"]
    ] == ["BNB-01"]
    assert [
        item["code"]
        for item in client.get(f"/api/projects/?organization={organization.id}").data["results"]
    ]
    assert client.get("/api/projects/?ordering=inconnu").status_code == 400
    assert client.get("/api/projects/?status=INCONNU").status_code == 400


@pytest.mark.django_db
def test_project_list_is_paginated(auth_client, project_context, project, organization):
    other_owner = project_context["owner"]
    for index in range(24):
        Project.objects.create(
            organization=organization,
            name=f"Projet {index:02d}",
            code=f"P{index:02d}",
            budget_total=1000000,
            created_by=other_owner,
        )
    response = auth_client(organization.owner).get("/api/projects/?page=1&page_size=10")
    assert response.status_code == 200
    assert response.data["count"] == 25
    assert len(response.data["results"]) == 10


@pytest.mark.django_db
def test_project_list_has_no_n_plus_one(
    auth_client, project_context, organization, project, make_user
):
    """Aucune requête proportionnelle au nombre de projets ou de membres."""
    for index in range(9):
        extra_owner = make_user(Role.PROJECT_OWNER, phone_number=f"+23769970{index:04d}")
        extra = Project.objects.create(
            organization=organization,
            name=f"Projet {index:02d}",
            code=f"NP{index:02d}",
            budget_total=2000000,
            created_by=extra_owner,
        )
        ProjectMember.objects.create(project=extra, user=extra_owner, role=Role.PROJECT_OWNER)

    client = auth_client(organization.owner)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/projects/?page_size=50")

    assert response.status_code == 200
    assert len(response.data["results"]) == 10
    assert len(queries) <= 6, [query["sql"][:120] for query in queries.captured_queries]
