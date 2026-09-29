"""Dashboard projet agrégé, calculé côté serveur et caché à courte durée."""

from __future__ import annotations

import copy
import logging
from datetime import date
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.models import ActivityLog
from apps.evidences.media_tokens import issue_media_token
from apps.evidences.models import Evidence, MediaScanStatus
from apps.finance.models import Expense, ExpenseStatus
from apps.projects.access import resolve_capabilities
from apps.projects.models import (
    FINAL_STATUSES,
    FINAL_TASK_STATUSES,
    Milestone,
    MilestoneStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)

logger = logging.getLogger("kemta.dashboard")
CACHE_PREFIX = "kemta:dashboard:project:v1"


def _safe_cache_get(key):
    try:
        return cache.get(key)
    except Exception:
        logger.warning("Cache dashboard indisponible ; calcul sans cache")
        return None


def _safe_cache_set(key, value):
    try:
        cache.set(key, value, timeout=settings.DASHBOARD_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Écriture cache dashboard impossible")


def _days_late(planned_date: date | None, today: date) -> int:
    return max((today - planned_date).days, 0) if planned_date and planned_date < today else 0


def _build_project_part(project: Project) -> dict:
    """Agrégats par requête SQL et seules les lignes affichées sont chargées en mémoire."""
    today = timezone.localdate()
    milestones = Milestone.objects.filter(project=project)
    tasks = Task.objects.filter(project=project)
    milestone_stats = milestones.aggregate(
        total=Count("id", filter=~Q(status=MilestoneStatus.CANCELLED)),
        done=Count("id", filter=Q(status=MilestoneStatus.DONE)),
        late=Count(
            "id",
            filter=Q(planned_date__lt=today) & ~Q(status__in=FINAL_STATUSES),
        ),
    )
    task_stats = tasks.aggregate(
        total=Count("id", filter=~Q(status=TaskStatus.CANCELLED)),
        done=Count("id", filter=Q(status=TaskStatus.DONE)),
        late=Count(
            "id",
            filter=Q(planned_end_date__lt=today) & ~Q(status__in=FINAL_TASK_STATUSES),
        ),
    )
    active_milestones = milestones.exclude(status=MilestoneStatus.CANCELLED)
    active_tasks = tasks.exclude(status=TaskStatus.CANCELLED)
    milestone_total = milestone_stats["total"]
    milestone_done = milestone_stats["done"]
    milestone_late = milestone_stats["late"]
    task_total = task_stats["total"]
    task_done = task_stats["done"]
    task_late = task_stats["late"]

    last_milestone = (
        active_milestones.filter(status=MilestoneStatus.DONE, actual_date__isnull=False)
        .order_by("-actual_date", "-id")
        .first()
    )
    next_milestone = (
        active_milestones.filter(planned_date__isnull=False)
        .exclude(status__in=FINAL_STATUSES)
        .order_by("planned_date", "id")
        .first()
    )

    evidence_counts = {
        row["status"]: row["total"]
        for row in Evidence.objects.filter(project=project)
        .values("status")
        .annotate(total=Count("id"))
    }
    evidence_qs = (
        Evidence.objects.filter(project=project)
        .select_related("author")
        .order_by("-captured_at", "-id")
    )
    recent_evidence = [
        {
            "id": item.pk,
            "status": item.status,
            "description": item.description,
            "captured_at": item.captured_at.isoformat(),
            "author": {
                "id": item.author_id,
                "first_name": item.author.first_name,
                "last_name": item.author.last_name,
            },
            "media_ready": item.scan_status == MediaScanStatus.CLEAN,
            "has_thumbnail": bool(item.thumbnail),
        }
        for item in evidence_qs[:5]
    ]

    late_tasks = list(
        active_tasks.filter(planned_end_date__lt=today)
        .exclude(status__in=FINAL_TASK_STATUSES)
        .order_by("planned_end_date", "id")[:5]
    )
    late_milestones = list(
        active_milestones.filter(planned_date__lt=today)
        .exclude(status__in=FINAL_STATUSES)
        .order_by("planned_date", "id")[:5]
    )
    delayed = bool(
        project.status == ProjectStatus.ACTIVE
        and project.planned_end_date
        and project.planned_end_date < today
        and project.actual_end_date is None
    )
    alerts = (
        [
            {
                "code": "PROJECT_DELAYED",
                "severity": "critical",
                "message": f"La date de fin prévue ({project.planned_end_date}) est dépassée.",
                "days_late": _days_late(project.planned_end_date, today),
            }
        ]
        if delayed
        else []
    )
    alerts.extend(
        {
            "code": "TASK_DELAYED",
            "severity": "warning",
            "entity_type": "Task",
            "entity_id": task.pk,
            "message": f"Tâche en retard : {task.title}.",
            "days_late": task.days_late,
        }
        for task in late_tasks
    )
    alerts.extend(
        {
            "code": "MILESTONE_DELAYED",
            "severity": "warning",
            "entity_type": "Milestone",
            "entity_id": milestone.pk,
            "message": f"Jalon en retard : {milestone.title}.",
            "days_late": milestone.days_late,
        }
        for milestone in late_milestones
    )

    return {
        "project": {
            "id": project.pk,
            "name": project.name,
            "code": project.code,
            "status": project.status,
            "status_label": project.get_status_display(),
            "currency": project.currency,
            # Project.progress est recalculé par les services d'écriture, jamais par le client.
            "progress": float(project.progress or 0),
            "budget_total": int(project.budget_total),
            "planned_start_date": project.planned_start_date.isoformat()
            if project.planned_start_date
            else None,
            "planned_end_date": project.planned_end_date.isoformat()
            if project.planned_end_date
            else None,
        },
        "milestones": {
            "total": milestone_total,
            "done": milestone_done,
            "late": milestone_late,
            "last": {
                "id": last_milestone.pk,
                "title": last_milestone.title,
                "status": last_milestone.status,
                "actual_date": last_milestone.actual_date.isoformat(),
            }
            if last_milestone
            else None,
            "next": {
                "id": next_milestone.pk,
                "title": next_milestone.title,
                "status": next_milestone.status,
                "planned_date": next_milestone.planned_date.isoformat(),
                "days_remaining": (next_milestone.planned_date - today).days,
            }
            if next_milestone
            else None,
        },
        "tasks": {"total": task_total, "done": task_done, "late": task_late},
        "evidence": {
            "total": sum(evidence_counts.values()),
            "counts": evidence_counts,
            "recent": recent_evidence,
        },
        "alerts": alerts[:15],
        "activity": _activity_part(project),
        "generated_at": timezone.now().isoformat(),
    }


def _finance_part(project: Project) -> dict:
    from apps.finance.services import budget_summary

    summary = budget_summary(project)
    keys = (
        "planned",
        "allocated",
        "unallocated",
        "committed",
        "paid",
        "outstanding",
        "balance",
    )
    finance = {key: int(summary[key]) for key in keys}
    finance.update(
        {
            "consumption_rate": float(summary["consumption_rate"]),
            "threshold": summary["threshold"],
            "currency": summary["currency"],
            "alerts": summary["alerts"],
        }
    )
    expenses = Expense.objects.filter(project=project).order_by("-incurred_on", "-id")[:5]
    return {
        "budget": finance,
        "expenses": {
            "recent": [
                {
                    "id": expense.pk,
                    "title": expense.title,
                    "amount": int(expense.amount),
                    "status": expense.status,
                    "incurred_on": expense.incurred_on.isoformat(),
                }
                for expense in expenses
            ],
            "count": Expense.objects.filter(project=project).count(),
            "pending_review": Expense.objects.filter(
                project=project, status=ExpenseStatus.SUBMITTED
            ).count(),
        },
    }


def _activity_part(project: Project) -> list[dict]:
    events = (
        ActivityLog.objects.filter(project=project)
        .select_related("actor")
        .order_by("-created_at", "-id")[:10]
    )
    return [
        {
            "id": event.pk,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "actor": {
                "id": event.actor_id,
                "first_name": event.actor.first_name,
                "last_name": event.actor.last_name,
            }
            if event.actor_id
            else None,
            "created_at": event.created_at.isoformat(),
            "metadata": event.metadata,
        }
        for event in events
    ]


def project_dashboard(project: Project, user) -> dict:
    """Retourne la synthèse autorisée, avec un cache 30 s invalidé à chaque journal métier."""
    cache_key = f"{CACHE_PREFIX}:{project.pk}"
    core = _safe_cache_get(cache_key)
    if core is None:
        core = _build_project_part(project)
        _safe_cache_set(cache_key, core)

    capabilities = resolve_capabilities(user, project)
    payload = copy.deepcopy(core)
    payload["permissions"] = {
        "view_finance": bool(capabilities.get("view_finance")),
        "view_activity": bool(capabilities.get("view_activity")),
        "capture_evidence": bool(capabilities.get("capture_evidence")),
        "validate_evidence": bool(capabilities.get("validate_evidence")),
    }

    for evidence in payload["evidence"]["recent"]:
        media_ready = evidence.pop("media_ready")
        has_thumbnail = evidence.pop("has_thumbnail")
        if media_ready:
            target = SimpleNamespace(pk=evidence["id"], project_id=project.pk)
            variant = "thumbnail" if has_thumbnail else "file"
            evidence["thumbnail"] = (
                f"/api/media/{issue_media_token(evidence=target, user=user, variant=variant)}/"
            )
        else:
            evidence["thumbnail"] = None

    if capabilities.get("view_finance"):
        finance_key = f"{cache_key}:finance"
        finance = _safe_cache_get(finance_key)
        if finance is None:
            finance = _finance_part(project)
            _safe_cache_set(finance_key, finance)
        payload.update(finance)
        payload["alerts"] = (payload["alerts"] + finance["budget"]["alerts"])[:20]
    else:
        payload["budget"] = None
        payload["expenses"] = {"recent": [], "count": None, "pending_review": None}

    if not capabilities.get("view_activity"):
        payload["activity"] = []
    return payload
