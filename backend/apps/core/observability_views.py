"""Métriques d'API et de service, protégées par la capacité d'exploitation."""

from __future__ import annotations

from django.db.models import Count, Q, Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.metrics import metrics_snapshot
from apps.core.views import check_database, check_redis
from apps.notifications.models import BusinessEvent, CeleryTaskLog
from apps.users.roles import Capability, role_has


class MetricsView(APIView):
    """`GET /api/metrics/` — snapshot JSON, visible à l'administrateur plateforme seulement."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (
            request.user.is_superuser or role_has(request.user.role, Capability.VIEW_OPERATIONS)
        ):
            from apps.core.exceptions import KemtaAPIError

            raise KemtaAPIError(
                "permission_denied",
                "Les métriques sont réservées à l'administrateur plateforme.",
                http_status=403,
            )

        from apps.evidences.models import Evidence
        from apps.finance.models import Expense

        evidence_totals = Evidence.objects.aggregate(
            total=Count("id"), bytes=Sum("size_bytes", filter=Q(file__gt=""))
        )
        receipt_totals = Expense.objects.filter(receipt__gt="").aggregate(
            total=Count("id"), bytes=Sum("receipt_size_bytes")
        )
        scan_states = {
            row["scan_status"]: row["total"]
            for row in Evidence.objects.values("scan_status").annotate(total=Count("id"))
        }
        task_states = {
            row["state"]: row["total"]
            for row in CeleryTaskLog.objects.values("state").annotate(total=Count("id"))
        }
        api_metrics = metrics_snapshot()
        db_ok, db_ms = check_database()
        redis_ok, redis_ms = check_redis()
        return Response(
            {
                "status": "ok" if db_ok and redis_ok else "degraded",
                "dependencies": {
                    "database": {"status": "ok" if db_ok else "down", "latency_ms": db_ms},
                    "redis": {"status": "ok" if redis_ok else "down", "latency_ms": redis_ms},
                },
                "api": api_metrics,
                "uploads": {
                    "evidence_count": evidence_totals["total"],
                    "evidence_bytes": evidence_totals["bytes"] or 0,
                    "receipt_count": receipt_totals["total"],
                    "receipt_bytes": receipt_totals["bytes"] or 0,
                    "scan_states": scan_states,
                },
                "synchronization": {
                    "failed_total": api_metrics["counters"].get("sync_failed_total", 0),
                    "conflict_total": api_metrics["counters"].get("sync_conflict_total", 0),
                },
                "celery": {
                    "task_states": task_states,
                    "pending_business_events": BusinessEvent.objects.filter(
                        dispatched_at__isnull=True
                    ).count(),
                },
            }
        )
