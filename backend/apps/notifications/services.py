"""Émission transactionnelle et distribution idempotente des événements métier."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.notifications.models import BusinessEvent, BusinessEventType, Notification

logger = logging.getLogger("kemta.notifications")
GROUP_WINDOW = timedelta(hours=24)
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "otp",
        "code",
        "token",
        "access",
        "refresh",
        "authorization",
        "secret",
        "api_key",
    }
)

EVENT_COPY = {
    BusinessEventType.MILESTONE_VALIDATED: (
        "Jalon terminé",
        "Un jalon du projet a été marqué comme terminé.",
    ),
    BusinessEventType.EXPENSE_SUBMITTED: (
        "Dépense à examiner",
        "Une dépense a été soumise pour examen.",
    ),
    BusinessEventType.EVIDENCE_REJECTED: (
        "Preuve rejetée",
        "Une de vos preuves nécessite une correction.",
    ),
    BusinessEventType.BUDGET_THRESHOLD_REACHED: (
        "Seuil budgétaire atteint",
        "Le budget du projet a franchi un seuil de vigilance.",
    ),
    BusinessEventType.PROJECT_DELAYED: (
        "Projet en retard",
        "La date de fin prévue du projet est dépassée.",
    ),
}


def _clean_payload(value):
    if isinstance(value, dict):
        return {
            str(key): _clean_payload(item)
            for key, item in value.items()
            if str(key).casefold() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_clean_payload(item) for item in value]
    return value


def _schedule_event(event_id: int) -> None:
    """Enfile sans faire échouer la transaction métier si le broker est momentanément indisponible."""
    from apps.notifications.tasks import dispatch_business_event

    try:
        dispatch_business_event.delay(event_id)
    except Exception:  # le beat réessaiera les événements encore en attente
        logger.warning(
            "Événement métier %s conservé dans l'outbox, envoi Celery à relancer", event_id
        )
        BusinessEvent.objects.filter(pk=event_id, dispatched_at__isnull=True).update(
            dispatch_error="broker_unavailable"
        )


def emit_business_event(
    event_type: str,
    *,
    actor=None,
    project=None,
    organization=None,
    entity_type: str = "",
    entity_id=None,
    payload: dict | None = None,
    dedupe_key: str = "",
) -> BusinessEvent:
    """Inscrit un événement dans l'outbox de la transaction courante.

    La livraison Celery est déclenchée avec `on_commit` : un worker ne peut jamais notifier un
    changement qui serait ensuite annulé. Les événements périodiques peuvent fournir une clé de
    déduplication ; les transitions métier normales ne s'en servent pas.
    """
    if event_type not in BusinessEventType.values:
        raise ValueError(f"Type d'événement métier inconnu : {event_type}")
    if dedupe_key:
        event, created = BusinessEvent.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "event_type": event_type,
                "actor": actor,
                "project": project,
                "organization": organization or getattr(project, "organization", None),
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id is not None else "",
                "payload": _clean_payload(payload or {}),
            },
        )
    else:
        event = BusinessEvent.objects.create(
            event_type=event_type,
            actor=actor,
            project=project,
            organization=organization or getattr(project, "organization", None),
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else "",
            payload=_clean_payload(payload or {}),
        )
        created = True

    if created or event.dispatched_at is None:
        transaction.on_commit(lambda: _schedule_event(event.pk))
    return event


def _recipient_ids(event: BusinessEvent) -> set[int]:
    if event.project_id is None:
        return set()

    from apps.organizations.models import OrganizationMember
    from apps.projects.models import ProjectMember
    from apps.users.roles import Role

    if event.event_type == BusinessEventType.EVIDENCE_REJECTED:
        try:
            from apps.evidences.models import Evidence

            author_id = (
                Evidence.objects.filter(pk=event.entity_id)
                .values_list("author_id", flat=True)
                .first()
            )
        except (TypeError, ValueError):
            author_id = None
        recipients = {author_id} if author_id else set()
    else:
        recipients = set(
            ProjectMember.objects.filter(
                project_id=event.project_id,
                is_active=True,
                user__is_active=True,
                user__is_phone_verified=True,
            ).values_list("user_id", flat=True)
        )
        recipients.update(
            OrganizationMember.objects.filter(
                organization_id=event.organization_id,
                is_active=True,
                user__is_active=True,
                user__is_phone_verified=True,
                role__in=(Role.ORG_OWNER, Role.PROJECT_OWNER),
            ).values_list("user_id", flat=True)
        )
        if event.organization_id:
            from apps.organizations.models import Organization

            owner_id = (
                Organization.objects.filter(
                    pk=event.organization_id,
                    owner__is_active=True,
                    owner__is_phone_verified=True,
                )
                .values_list("owner_id", flat=True)
                .first()
            )
            if owner_id:
                recipients.add(owner_id)

    if event.actor_id:
        recipients.discard(event.actor_id)
    return recipients


def _notification_text(event: BusinessEvent) -> tuple[str, str]:
    title, body = EVENT_COPY[event.event_type]
    project_name = getattr(event.project, "name", "")
    if project_name:
        title = f"{title} · {project_name}"[:180]
    return title, body


@transaction.atomic
def dispatch_event(event_id: int) -> int:
    """Matérialise une notification par destinataire, au plus une fois par événement."""
    event = BusinessEvent.objects.select_for_update().select_related("project").get(pk=event_id)
    if event.dispatched_at:
        return 0

    recipients = _recipient_ids(event)
    now = timezone.now()
    title, body = _notification_text(event)
    project_id = event.project_id
    group_key_base = f"{event.event_type}:{project_id or 0}"
    if event.event_type == BusinessEventType.EVIDENCE_REJECTED:
        group_key_base = f"{group_key_base}:{event.entity_id}"
    dispatched = 0

    for recipient_id in sorted(recipients):
        group_key = f"{recipient_id}:{group_key_base}"[:180]
        current = (
            Notification.objects.select_for_update()
            .filter(
                recipient_id=recipient_id,
                group_key=group_key,
                read_at__isnull=True,
                last_seen_at__gte=now - GROUP_WINDOW,
            )
            .order_by("-last_seen_at", "-pk")
            .first()
        )
        event_payload = {
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "event_id": event.pk,
            "project_id": project_id,
        }
        if current:
            current.count += 1
            current.last_seen_at = now
            current.title = title
            current.body = body
            current.payload = event_payload
            current.save(
                update_fields=["count", "last_seen_at", "title", "body", "payload", "updated_at"]
            )
        else:
            Notification.objects.create(
                recipient_id=recipient_id,
                event_type=event.event_type,
                project_id=project_id,
                title=title,
                body=body,
                payload=event_payload,
                group_key=group_key,
                last_seen_at=now,
            )
        dispatched += 1

    event.dispatched_at = now
    event.dispatch_error = ""
    event.save(update_fields=["dispatched_at", "dispatch_error"])
    return dispatched


def mark_notification_read(*, notification: Notification, user) -> Notification:
    if notification.recipient_id != user.pk:
        raise PermissionError("Cette notification appartient à un autre utilisateur.")
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return notification


def mark_all_notifications_read(*, user) -> int:
    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(
        read_at=timezone.now(), updated_at=timezone.now()
    )


def event_recipients_for_project(project_id: int, organization_id: int | None = None) -> set[int]:
    """Destinataires actifs pour un événement planifié sans acteur métier."""
    from apps.organizations.models import Organization, OrganizationMember
    from apps.projects.models import ProjectMember
    from apps.users.roles import Role

    user_ids = set(
        ProjectMember.objects.filter(
            project_id=project_id,
            is_active=True,
            user__is_active=True,
            user__is_phone_verified=True,
        ).values_list("user_id", flat=True)
    )
    if organization_id:
        user_ids.update(
            OrganizationMember.objects.filter(
                organization_id=organization_id,
                is_active=True,
                user__is_active=True,
                user__is_phone_verified=True,
                role__in=(Role.ORG_OWNER, Role.PROJECT_OWNER),
            ).values_list("user_id", flat=True)
        )
        owner_id = (
            Organization.objects.filter(
                pk=organization_id, owner__is_active=True, owner__is_phone_verified=True
            )
            .values_list("owner_id", flat=True)
            .first()
        )
        if owner_id:
            user_ids.add(owner_id)
    return user_ids


__all__ = [
    "dispatch_event",
    "emit_business_event",
    "event_recipients_for_project",
    "mark_all_notifications_read",
    "mark_notification_read",
]
