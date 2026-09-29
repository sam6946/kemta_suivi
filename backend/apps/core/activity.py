"""Service de journalisation : point d'entrée unique pour créer un événement."""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from .models import ActivityLog

logger = logging.getLogger("kemta.audit")

# Champs de métadonnées dont la valeur ne doit jamais être journalisée.
FORBIDDEN_METADATA_KEYS = {
    "password",
    "new_password",
    "current_password",
    "old_password",
    "password_confirm",
    "new_password_confirm",
    "code",
    "otp",
    "token",
    "access",
    "refresh",
    "password_hash",
    "code_hash",
    "secret_key",
    "api_key",
    "authorization",
}


def get_client_ip(request) -> str | None:
    if request is None:
        return None
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _clean_value(value):
    if isinstance(value, dict):
        return {
            key: _clean_value(item)
            for key, item in value.items()
            if str(key).lower() not in FORBIDDEN_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    return value


def _clean_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    return _clean_value(metadata)


def log_event(
    action: str,
    *,
    actor=None,
    entity_type: str = "",
    entity_id=None,
    metadata: dict | None = None,
    organization=None,
    project=None,
    request=None,
) -> ActivityLog | None:
    """Crée un événement de journal.

    Ne lève jamais d'exception : une panne de journalisation ne doit pas casser
    le parcours utilisateur, mais elle est signalée dans les logs applicatifs.
    """
    actor_instance = actor if actor is not None and getattr(actor, "pk", None) else None
    try:
        event = ActivityLog.objects.create(
            actor=actor_instance,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else "",
            organization=organization,
            project=project,
            metadata=_clean_metadata(metadata),
            ip_address=get_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:200] if request else ""),
        )
        if project is not None:
            from apps.core.cache_utils import invalidate_project_dashboard

            transaction.on_commit(lambda: invalidate_project_dashboard(project.pk))
        return event
    except IntegrityError:  # pragma: no cover - garde-fou
        logger.exception("Impossible d'écrire l'événement %s", action)
        return None
