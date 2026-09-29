"""Notifications personnelles, outbox et endpoints d'exploitation."""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.notifications.models import (
    BusinessEvent,
    BusinessEventType,
    CeleryTaskLog,
    Notification,
)
from apps.notifications.services import dispatch_event, emit_business_event
from apps.users.roles import Role


@pytest.mark.django_db
def test_business_event_dispatch_creates_private_notifications(project, project_context):
    actor = project_context["owner"]
    recipient = project_context["engineer"]
    stranger = project_context["stranger"]
    event = emit_business_event(
        BusinessEventType.MILESTONE_VALIDATED,
        actor=actor,
        project=project,
        entity_type="Milestone",
        entity_id="42",
        payload={"password": "must-not-persist", "project_id": project.pk},
    )

    delivered = dispatch_event(event.pk)

    assert delivered == 6  # membres actifs du projet et propriétaire de l'organisation
    assert Notification.objects.filter(recipient=project_context["organization"].owner).exists()
    notification = Notification.objects.get(recipient=recipient)
    assert notification.title.startswith("Jalon terminé")
    assert notification.project == project
    assert "password" not in event.payload
    assert not Notification.objects.filter(recipient=stranger).exists()
    assert BusinessEvent.objects.get(pk=event.pk).dispatched_at is not None
    assert dispatch_event(event.pk) == 0


@pytest.mark.django_db
def test_dispatch_locks_outbox_row_without_locking_nullable_project_join():
    """La FK project nullable doit rester compatible avec le verrou PostgreSQL de l'outbox."""
    if not connection.features.has_select_for_update_of:
        pytest.skip("Ce moteur ne prend pas en charge SELECT FOR UPDATE OF (PostgreSQL).")

    event = BusinessEvent.objects.create(
        event_type=BusinessEventType.PROJECT_DELAYED,
        project=None,
        payload={},
    )

    assert dispatch_event(event.pk) == 0
    event.refresh_from_db()
    assert event.dispatched_at is not None


@pytest.mark.django_db
def test_project_delay_events_are_idempotent_per_local_day(project, monkeypatch):
    from apps.notifications.tasks import emit_project_delay_events

    today = timezone.localdate()
    project.refresh_from_db()
    project.planned_end_date = today - timedelta(days=1)
    project.save(update_fields=["planned_end_date", "updated_at"])

    assert emit_project_delay_events.run() == 1
    assert emit_project_delay_events.run() == 0
    assert BusinessEvent.objects.filter(event_type=BusinessEventType.PROJECT_DELAYED).count() == 1

    tomorrow = today + timedelta(days=1)
    monkeypatch.setattr("apps.notifications.tasks.timezone.localdate", lambda: tomorrow)
    assert emit_project_delay_events.run() == 1
    assert BusinessEvent.objects.filter(event_type=BusinessEventType.PROJECT_DELAYED).count() == 2


@pytest.mark.django_db
def test_sensitive_event_payload_is_removed_and_dispatch_is_on_commit(project, project_context):
    event = emit_business_event(
        BusinessEventType.EXPENSE_SUBMITTED,
        actor=project_context["finance"],
        project=project,
        entity_type="Expense",
        entity_id=7,
        payload={
            "amount": 100,
            "nested": {"otp": "123456", "safe": "value"},
            "items": [{"refresh": "secret", "id": 1}],
        },
    )
    assert event.payload == {"amount": 100, "nested": {"safe": "value"}, "items": [{"id": 1}]}
    assert event.dispatched_at is None


@pytest.mark.django_db
def test_notification_list_mark_read_and_read_all_are_user_scoped(
    auth_client, project_context, project
):
    recipient = project_context["engineer"]
    other = project_context["finance"]
    first = Notification.objects.create(
        recipient=recipient,
        event_type=BusinessEventType.EXPENSE_SUBMITTED,
        project=project,
        title="Dépense à examiner",
        body="Une dépense est soumise.",
        group_key="1:EXPENSE_SUBMITTED:1",
        last_seen_at=timezone.now(),
    )
    Notification.objects.create(
        recipient=recipient,
        event_type=BusinessEventType.PROJECT_DELAYED,
        project=project,
        title="Projet en retard",
        body="La date prévue est dépassée.",
        group_key="1:PROJECT_DELAYED:1",
        last_seen_at=timezone.now(),
    )
    Notification.objects.create(
        recipient=other,
        event_type=BusinessEventType.PROJECT_DELAYED,
        project=project,
        title="Privée",
        body="Autre compte.",
        group_key="2:PROJECT_DELAYED:1",
        last_seen_at=timezone.now(),
    )
    client = auth_client(recipient)

    listed = client.get("/api/notifications/")
    assert listed.status_code == 200
    assert listed.data["count"] == 2
    assert listed.data["unread_count"] == 2
    assert listed.data["results"][0]["link"] == f"/projets/{project.pk}/tableau-de-bord"

    marked = client.post(f"/api/notifications/{first.pk}/read/")
    assert marked.status_code == 200
    assert marked.data["is_read"] is True
    assert Notification.objects.get(pk=first.pk).is_read

    bulk = client.post("/api/notifications/read-all/")
    assert bulk.status_code == 200
    assert bulk.data["updated"] == 1
    assert Notification.objects.filter(recipient=recipient, read_at__isnull=True).count() == 0
    assert Notification.objects.filter(recipient=other, read_at__isnull=True).exists()

    missing = client.post(f"/api/notifications/{first.pk + 10000}/read/")
    assert missing.status_code == 404


@pytest.mark.django_db
def test_metrics_and_celery_journal_are_platform_admin_only(
    auth_client, project_context, make_user
):
    log = CeleryTaskLog.objects.create(
        task_id="task-123",
        name="apps.test.cleanup",
        state="FAILURE",
        retries=2,
        error="RuntimeError: test failed",
        queued_at=timezone.now(),
        finished_at=timezone.now(),
    )
    engineer = auth_client(project_context["engineer"])
    assert engineer.get("/api/metrics/").status_code == 403
    assert engineer.get("/api/operations/").status_code == 403
    assert engineer.get("/api/operations/tasks/").status_code == 403

    admin_user = make_user(Role.PLATFORM_ADMIN, phone_number="+237691889999")
    admin = auth_client(admin_user)
    metrics = admin.get("/api/metrics/")
    assert metrics.status_code == 200
    assert "dependencies" in metrics.data
    assert metrics.data["celery"]["task_states"]["FAILURE"] == 1

    summary = admin.get("/api/operations/")
    assert summary.status_code == 200
    assert summary.data["tasks"]["FAILURE"] == 1
    tasks = admin.get("/api/operations/tasks/", {"state": "FAILURE", "page_size": 1})
    assert tasks.status_code == 200
    assert tasks.data["results"][0]["task_id"] == log.task_id
    assert tasks.data["count"] == 1
