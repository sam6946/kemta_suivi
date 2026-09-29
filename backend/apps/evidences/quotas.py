"""Quotas cumulatives par utilisateur et par projet pour toutes les pièces médias."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from apps.core.exceptions import KemtaAPIError
from apps.evidences.models import Evidence
from apps.finance.models import Expense
from apps.projects.models import Project
from apps.users.models import User

MEBIBYTE = 1024 * 1024


def _totals(
    *, user_id: int, project_id: int, exclude_expense_id: int | None = None
) -> tuple[int, int]:
    evidence_user = (
        Evidence.objects.filter(author_id=user_id, file__gt="").aggregate(total=Sum("size_bytes"))[
            "total"
        ]
        or 0
    )
    evidence_project = (
        Evidence.objects.filter(project_id=project_id, file__gt="").aggregate(
            total=Sum("size_bytes")
        )["total"]
        or 0
    )

    receipts_user = Expense.objects.filter(receipt_uploaded_by_id=user_id, receipt__gt="")
    receipts_project = Expense.objects.filter(project_id=project_id, receipt__gt="")
    if exclude_expense_id is not None:
        receipts_user = receipts_user.exclude(pk=exclude_expense_id)
        receipts_project = receipts_project.exclude(pk=exclude_expense_id)
    user_bytes = receipts_user.aggregate(total=Sum("receipt_size_bytes"))["total"] or 0
    project_bytes = receipts_project.aggregate(total=Sum("receipt_size_bytes"))["total"] or 0
    return int(evidence_user + user_bytes), int(evidence_project + project_bytes)


@transaction.atomic
def enforce_media_quota(
    *, project_id: int, actor_id: int, new_size: int, exclude_expense_id: int | None = None
) -> None:
    """Verrouille les lignes de quota puis refuse avec 413 avant toute écriture de fichier."""
    # Le verrou utilisateur sérialise ses dépôts entre plusieurs chantiers ; celui du projet
    # protège le quota partagé par les membres. PostgreSQL est le moteur de référence du MVP.
    Project.objects.select_for_update().only("pk").get(pk=project_id)
    User.objects.select_for_update().only("pk").get(pk=actor_id)
    user_used, project_used = _totals(
        user_id=actor_id,
        project_id=project_id,
        exclude_expense_id=exclude_expense_id,
    )
    limits = (
        ("user", user_used, settings.MAX_MEDIA_USER_QUOTA_MB * MEBIBYTE),
        ("project", project_used, settings.MAX_MEDIA_PROJECT_QUOTA_MB * MEBIBYTE),
    )
    for scope, used, limit in limits:
        if used + new_size > limit:
            raise KemtaAPIError(
                "media_quota_exceeded",
                "Le quota de stockage des médias est atteint. Supprimez des pièces inutiles ou contactez l'administrateur.",
                http_status=413,
                details={
                    "scope": scope,
                    "used_bytes": used,
                    "limit_bytes": limit,
                    "incoming_bytes": new_size,
                },
            )
