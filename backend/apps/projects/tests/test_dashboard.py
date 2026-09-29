"""Synthèse projet de la phase 8 : chiffres serveur, permissions et journal."""

import pytest
from django.core.cache import cache

from apps.core.activity import log_event
from apps.core.models import ActivityLog
from apps.projects.models import Milestone, MilestoneStatus, Task, TaskStatus
from apps.projects.progress import recalculate_project_progress

DASHBOARD_URL = "/api/projects/{project_id}/dashboard/"
ACTIVITY_URL = "/api/projects/{project_id}/activity/"


@pytest.mark.django_db
def test_dashboard_aggregates_progress_alerts_budget_and_recent_activity(
    auth_client, project, project_context
):
    owner = project_context["owner"]
    milestone = Milestone.objects.create(
        project=project,
        title="Fondations achevées",
        status=MilestoneStatus.DONE,
        planned_date="2026-05-10",
        actual_date="2026-05-12",
        created_by=owner,
    )
    Task.objects.create(
        project=project,
        milestone=milestone,
        title="Contrôle des fondations",
        status=TaskStatus.DONE,
        planned_start_date="2026-05-01",
        planned_end_date="2026-05-10",
        actual_end_date="2026-05-10",
        created_by=owner,
    )
    log_event(
        "MILESTONE_CREATED",
        actor=owner,
        entity_type="Milestone",
        entity_id=milestone.pk,
        organization=project.organization,
        project=project,
        metadata={"title": milestone.title},
    )

    recalculate_project_progress(project)
    response = auth_client(owner).get(DASHBOARD_URL.format(project_id=project.pk))

    assert response.status_code == 200, response.data
    assert response.data["project"]["progress"] == 100.0
    assert response.data["milestones"]["done"] == 1
    assert response.data["milestones"]["last"]["id"] == milestone.pk
    assert response.data["budget"]["planned"] == project.budget_total
    assert response.data["permissions"]["view_finance"] is True
    assert response.data["activity"][0]["action"] == "MILESTONE_CREATED"


@pytest.mark.django_db
def test_dashboard_hides_finance_and_activity_from_field_agent(
    auth_client, project, project_context
):
    response = auth_client(project_context["agent"]).get(
        DASHBOARD_URL.format(project_id=project.pk)
    )

    assert response.status_code == 200
    assert response.data["permissions"]["view_finance"] is False
    assert response.data["budget"] is None
    assert response.data["expenses"]["count"] is None
    assert response.data["permissions"]["view_activity"] is False
    assert response.data["activity"] == []


@pytest.mark.django_db
def test_dashboard_is_scoped_to_accessible_projects(auth_client, project_context, project):
    response = auth_client(project_context["stranger"]).get(
        DASHBOARD_URL.format(project_id=project.pk)
    )
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_dashboard_cache_is_invalidated_after_activity_write(auth_client, project, project_context):
    owner = project_context["owner"]
    url = DASHBOARD_URL.format(project_id=project.pk)
    client = auth_client(owner)

    first = client.get(url)
    assert first.status_code == 200
    assert first.data["activity"] == []
    assert cache.get(f"kemta:dashboard:project:v1:{project.pk}") is not None

    log_event(
        "PROJECT_UPDATED",
        actor=owner,
        entity_type="Project",
        entity_id=project.pk,
        organization=project.organization,
        project=project,
    )

    assert cache.get(f"kemta:dashboard:project:v1:{project.pk}") is None
    refreshed = client.get(url)
    assert refreshed.data["activity"][0]["action"] == "PROJECT_UPDATED"


@pytest.mark.django_db
def test_project_activity_is_paginated_and_permission_checked(
    auth_client, project, project_context
):
    owner = project_context["owner"]
    for action in ("PROJECT_UPDATED", "TASK_CREATED", "TASK_STATUS_CHANGED"):
        ActivityLog.objects.create(
            actor=owner,
            action=action,
            entity_type="Task",
            entity_id="12",
            organization=project.organization,
            project=project,
        )

    response = auth_client(project_context["engineer"]).get(
        ACTIVITY_URL.format(project_id=project.pk), {"action": "TASK_CREATED", "page_size": 1}
    )
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["action"] == "TASK_CREATED"
    assert "next" in response.data

    forbidden = auth_client(project_context["agent"]).get(
        ACTIVITY_URL.format(project_id=project.pk)
    )
    assert forbidden.status_code == 403


@pytest.mark.django_db
def test_project_activity_unknown_filter_is_rejected(auth_client, project_context, project):
    response = auth_client(project_context["engineer"]).get(
        ACTIVITY_URL.format(project_id=project.pk), {"action": "NOT_AN_ACTION"}
    )
    assert response.status_code == 400
