"""Capture les transitions Celery sans enregistrer les arguments ni les secrets."""

from __future__ import annotations

import re

from celery.signals import task_failure, task_postrun, task_prerun, task_retry, task_sent
from django.utils import timezone

_SECRET_VALUE = re.compile(
    r"(?i)(password|passphrase|otp|token|secret|api[_-]?key|authorization)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_task_error(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    value = f"{type(exc).__name__}: {exc}"
    value = _SECRET_VALUE.sub(r"\1\2[REDACTED]", value)
    value = _CONTROL_CHARS.sub(" ", value)
    return value[:2000]


def _upsert(task_id, name, **defaults):
    if not task_id:
        return
    from apps.notifications.models import CeleryTaskLog

    base = {
        "name": (name or "unknown")[:255],
        "state": "PENDING",
        "queued_at": timezone.now(),
    }
    base.update(defaults)
    CeleryTaskLog.objects.update_or_create(task_id=str(task_id)[:255], defaults=base)


def _update(task_id, **defaults):
    if not task_id:
        return
    from apps.notifications.models import CeleryTaskLog

    CeleryTaskLog.objects.filter(task_id=str(task_id)[:255]).update(**defaults)


@task_sent.connect(dispatch_uid="kemta.task_sent", weak=False)
def record_task_sent(sender=None, task_id=None, name=None, **kwargs):
    _upsert(task_id, name or sender, state="PENDING")


@task_prerun.connect(dispatch_uid="kemta.task_prerun", weak=False)
def record_task_start(sender=None, task_id=None, task=None, **kwargs):
    from apps.notifications.models import CeleryTaskLog

    name = getattr(task, "name", None) or getattr(sender, "name", None)
    log, _ = CeleryTaskLog.objects.get_or_create(
        task_id=str(task_id)[:255],
        defaults={
            "name": (name or "unknown")[:255],
            "state": "STARTED",
            "started_at": timezone.now(),
            "queued_at": timezone.now(),
        },
    )
    CeleryTaskLog.objects.filter(pk=log.pk).update(
        name=(name or log.name)[:255], state="STARTED", started_at=timezone.now(), error=""
    )


@task_retry.connect(dispatch_uid="kemta.task_retry", weak=False)
def record_task_retry(sender=None, request=None, reason=None, **kwargs):
    request = request or getattr(sender, "request", None)
    _update(
        getattr(request, "id", None),
        state="RETRY",
        retries=getattr(request, "retries", 0),
        error=safe_task_error(reason if isinstance(reason, BaseException) else None),
        updated_at=timezone.now(),
    )


@task_failure.connect(dispatch_uid="kemta.task_failure", weak=False)
def record_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    task = sender
    _upsert(
        task_id,
        getattr(task, "name", None),
        state="FAILURE",
        retries=getattr(getattr(task, "request", None), "retries", 0),
        error=safe_task_error(exception),
        finished_at=timezone.now(),
    )


@task_postrun.connect(dispatch_uid="kemta.task_postrun", weak=False)
def record_task_finish(sender=None, task_id=None, task=None, state=None, **kwargs):
    from apps.notifications.models import CeleryTaskLog

    final_state = state or "UNKNOWN"
    defaults = {"state": final_state, "finished_at": timezone.now(), "updated_at": timezone.now()}
    if final_state == "SUCCESS":
        defaults["error"] = ""
    name = getattr(task, "name", None) or getattr(sender, "name", None)
    if task_id and not CeleryTaskLog.objects.filter(task_id=str(task_id)[:255]).exists():
        _upsert(task_id, name, **defaults)
    else:
        _update(task_id, **defaults)

    if final_state in {"SUCCESS", "FAILURE", "RETRY"}:
        from apps.core.metrics import increment_metric

        increment_metric(f"celery_task_{final_state.lower()}_total")
