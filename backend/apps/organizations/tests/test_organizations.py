"""MVP-005 — organisations : création, périmètre, périmètre de visibilité, journalisation."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import ActivityLog
from apps.organizations.models import Organization, OrganizationMember
from apps.users.roles import Role


@pytest.mark.django_db
def test_authorized_user_can_create_organization(auth_client, make_user):
    user = make_user(Role.ORG_OWNER)
    client = auth_client(user)

    response = client.post(
        "/api/organizations/",
        {
            "name": "BTP Kribi SARL",
            "type": "PME",
            "city": "Kribi",
            "address": "Zone portuaire",
            "contact_phone": "+237 6 90 00 00 09",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.data["slug"] == "btp-kribi-sarl"
    assert response.data["owner"]["id"] == user.id

    organization = Organization.objects.get(slug="btp-kribi-sarl")
    assert organization.owner_id == user.id
    # Le créateur devient propriétaire actif dans l'organisation.
    assert OrganizationMember.objects.filter(
        organization=organization, user=user, role=Role.ORG_OWNER, is_active=True
    ).exists()
    assert ActivityLog.objects.filter(action="ORG_CREATED", organization=organization).exists()


@pytest.mark.django_db
def test_field_agent_cannot_create_organization(auth_client, make_user):
    """Un rôle sans capacité de création reçoit un 403 explicite."""
    client = auth_client(make_user(Role.FIELD_AGENT))
    response = client.post("/api/organizations/", {"name": "Sans droits"}, format="json")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"
    assert Organization.objects.count() == 0


@pytest.mark.django_db
def test_slug_is_unique_even_for_identical_names(auth_client, make_user):
    client = auth_client(make_user(Role.ORG_OWNER))
    first = client.post("/api/organizations/", {"name": "Kemta Bâtiment"}, format="json")
    second = client.post("/api/organizations/", {"name": "Kemta Batiment"}, format="json")
    assert first.status_code == 201 and second.status_code == 201
    assert first.data["slug"] != second.data["slug"]
    assert second.data["slug"].startswith("kemta-batiment")


@pytest.mark.django_db
def test_list_is_limited_to_own_scope(auth_client, organization, make_user):
    outsider = make_user(Role.ORG_OWNER, phone_number="+237699111222")
    own = auth_client(organization.owner).get("/api/organizations/")
    other = auth_client(outsider).get("/api/organizations/")

    assert [item["id"] for item in own.data["results"]] == [organization.id]
    assert other.data["results"] == []


@pytest.mark.django_db
def test_detail_of_foreign_organization_is_not_found(auth_client, organization, make_user):
    """Un objet hors périmètre n'existe pas : 404 (et non 403)."""
    outsider = auth_client(make_user(Role.ORG_OWNER, phone_number="+237699111222"))
    response = outsider.get(f"/api/organizations/{organization.id}/")
    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_member_role_grants_read_access(auth_client, organization, make_user):
    member = make_user(Role.INVESTOR)
    OrganizationMember.objects.create(organization=organization, user=member, role=Role.INVESTOR)

    response = auth_client(member).get(f"/api/organizations/{organization.id}/")
    assert response.status_code == 200
    assert response.data["name"] == organization.name


@pytest.mark.django_db
def test_investor_cannot_update_organization(auth_client, organization, make_user):
    investor = make_user(Role.INVESTOR)
    OrganizationMember.objects.create(organization=organization, user=investor, role=Role.INVESTOR)

    response = auth_client(investor).patch(
        f"/api/organizations/{organization.id}/", {"city": "Yaoundé"}, format="json"
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"
    organization.refresh_from_db()
    assert organization.city == "Douala"


@pytest.mark.django_db
def test_owner_can_update_and_change_is_journalised(auth_client, organization):
    response = auth_client(organization.owner).patch(
        f"/api/organizations/{organization.id}/",
        {"city": "Yaoundé", "address": "Bastos"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["city"] == "Yaoundé"

    entry = ActivityLog.objects.filter(action="ORG_UPDATED", organization=organization).first()
    assert entry is not None
    assert entry.actor_id == organization.owner_id
    assert "city" in entry.metadata["fields"]


@pytest.mark.django_db
def test_organization_with_projects_cannot_be_deleted(auth_client, organization, project):
    response = auth_client(organization.owner).delete(f"/api/organizations/{organization.id}/")
    assert response.status_code == 409
    assert response.data["error"]["code"] == "organization_has_projects"
    assert Organization.objects.filter(pk=organization.pk).exists()


@pytest.mark.django_db
def test_empty_organization_is_soft_deleted(auth_client, organization):
    client = auth_client(organization.owner)
    assert client.delete(f"/api/organizations/{organization.id}/").status_code == 204

    assert not Organization.objects.filter(pk=organization.pk).exists()
    assert Organization.all_objects.filter(pk=organization.pk, deleted_at__isnull=False).exists()
    # La suppression est journalisée (aucune donnée historique n'est effacée).
    assert ActivityLog.objects.filter(
        action="ORG_UPDATED", organization=organization, metadata__status="deleted"
    ).exists()


@pytest.mark.django_db
def test_organization_list_is_paginated(auth_client, make_user):
    user = make_user(Role.ORG_OWNER)
    for index in range(25):
        Organization.objects.create(name=f"Organisation {index:02d}", owner=user)
    response = auth_client(user).get("/api/organizations/?page=2")
    assert response.status_code == 200
    assert response.data["count"] == 25
    assert len(response.data["results"]) == 5


@pytest.mark.django_db
def test_organization_list_has_no_n_plus_one(auth_client, make_user, project):
    """Annoter les compteurs évite une requête par ligne."""
    user = project.organization.owner
    for index in range(8):
        Organization.objects.create(name=f"Organisation {index:02d}", owner=user)

    client = auth_client(user)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/organizations/?page_size=50")

    assert response.status_code == 200
    assert len(response.data["results"]) == 9
    # 1 requête de comptage, 1 pour les résultats, 1 pour les owners (select_related),
    # plus l'authentification : on reste très en deçà d'une requête par ligne.
    assert len(queries) <= 6, [query["sql"][:120] for query in queries.captured_queries]


@pytest.mark.django_db
def test_partial_member_patch_keeps_role_and_activation(auth_client, organization, make_user):
    """Un PATCH partiel ne modifie que ce qui est fourni (pas de réactivation implicite)."""
    member_user = make_user(Role.ENGINEER, phone_number="+237699777888")
    response = auth_client(organization.owner).post(
        f"/api/organizations/{organization.id}/members/",
        {"phone": member_user.phone, "role": Role.ENGINEER},
        format="json",
    )
    assert response.status_code == 201, response.data
    membership = OrganizationMember.objects.get(organization=organization, user=member_user)
    membership.is_active = False
    membership.save(update_fields=["is_active"])

    response = auth_client(organization.owner).patch(
        f"/api/organizations/{organization.id}/members/{membership.id}/",
        {"role": Role.FINANCE},
        format="json",
    )
    assert response.status_code == 200, response.data

    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.role == Role.FINANCE
    assert membership.is_active is False  # non réactivé
