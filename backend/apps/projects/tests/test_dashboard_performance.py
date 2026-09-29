"""Garde contre les N+1 et le chargement intégral des collections du dashboard."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.models import ActivityLog
from apps.projects.models import Milestone, Task, TaskStatus


@pytest.mark.django_db
def test_dashboard_query_count_stays_bounded_for_large_collections(
    auth_client, project, project_context
):
    owner = project_context["owner"]
    today = timezone.localdate()
    Milestone.objects.bulk_create(
        [
            Milestone(
                project=project,
                title=f"Jalon {index}",
                planned_date=today,
                created_by=owner,
                order=index,
            )
            for index in range(40)
        ]
    )
    Task.objects.bulk_create(
        [
            Task(
                project=project,
                title=f"Tâche {index}",
                status=TaskStatus.TODO,
                planned_end_date=today,
                created_by=owner,
            )
            for index in range(40)
        ]
    )
    ActivityLog.objects.bulk_create(
        [
            ActivityLog(
                actor=owner,
                action="TASK_CREATED",
                entity_type="Task",
                entity_id=str(index),
                organization=project.organization,
                project=project,
            )
            for index in range(40)
        ]
    )

    with CaptureQueriesContext(connection) as queries:
        response = auth_client(owner).get(f"/api/projects/{project.pk}/dashboard/")

    assert response.status_code == 200, response.data
    assert response.data["milestones"]["total"] == 40
    assert response.data["tasks"]["total"] == 40
    assert len(response.data["activity"]) == 10
    # Le coût est fixe en fonction du nombre de lignes (et non de 40 jalons/tâches/acteurs).
    assert len(queries) <= 30, [query["sql"] for query in queries]
