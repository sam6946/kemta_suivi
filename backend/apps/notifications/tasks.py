"""Tâches Celery de distribution et d'entretien de l'outbox métier."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("kemta.notifications")


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    name="apps.notifications.dispatch_business_event",
)
def dispatch_business_event(self, event_id: int) -> int:
    from apps.notifications.services import dispatch_event

    return dispatch_event(event_id)


@shared_task(name="apps.notifications.retry_pending_business_events")
def retry_pending_business_events(batch_size: int = 200) -> int:
    """Republie les éléments outbox restés en attente après une panne de broker/worker."""
    from apps.notifications.models import BusinessEvent

    stale_before = timezone.now() - timedelta(minutes=1)
    event_ids = list(
        BusinessEvent.objects.filter(dispatched_at__isnull=True, created_at__lt=stale_before)
        .order_by("created_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    for event_id in event_ids:
        dispatch_business_event.delay(event_id)
    return len(event_ids)


@shared_task(name="apps.notifications.emit_project_delay_events")
def emit_project_delay_events() -> int:
    """Émet une alerte idempotente par projet et date de fin dépassée, une fois par jour."""
    from apps.notifications.models import BusinessEvent, BusinessEventType
    from apps.notifications.services import emit_business_event
    from apps.projects.models import Project, ProjectStatus

    today = timezone.localdate()
    projects = Project.objects.filter(
        status=ProjectStatus.ACTIVE,
        planned_end_date__lt=today,
        actual_end_date__isnull=True,
    ).select_related("organization")
    emitted = 0
    for project in projects.iterator(chunk_size=200):
        dedupe_key = f"project-delayed:{project.pk}:{project.planned_end_date.isoformat()}:{today.isoformat()}"
        created = not BusinessEvent.objects.filter(dedupe_key=dedupe_key).exists()
        emit_business_event(
            BusinessEventType.PROJECT_DELAYED,
            project=project,
            organization=project.organization,
            entity_type="Project",
            entity_id=project.pk,
            payload={
                "planned_end_date": project.planned_end_date.isoformat(),
                "days_late": (today - project.planned_end_date).days,
            },
            dedupe_key=dedupe_key,
        )
        emitted += int(created)
    return emitted


@shared_task(name="apps.notifications.purge_task_logs")
def purge_task_logs(retention_days: int = 90) -> int:
    """Conserve 90 jours de traces d'exploitation par défaut, sans stocker les arguments."""
    from apps.notifications.models import CeleryTaskLog

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = CeleryTaskLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted
