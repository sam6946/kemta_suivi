"""API des notifications privées et du journal d'exploitation Celery."""

from __future__ import annotations

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import KemtaAPIError
from apps.core.pagination import DefaultPagination
from apps.notifications.models import CeleryTaskLog, Notification
from apps.notifications.serializers import CeleryTaskLogSerializer, NotificationSerializer
from apps.notifications.services import mark_all_notifications_read, mark_notification_read
from apps.users.roles import Capability, role_has


def require_operations_access(user) -> None:
    if not (user.is_superuser or role_has(user.role, Capability.VIEW_OPERATIONS)):
        raise KemtaAPIError(
            "permission_denied",
            "L'accès aux outils d'exploitation est réservé à l'administrateur plateforme.",
            http_status=403,
        )


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.filter(recipient=request.user).select_related("project")
        if request.query_params.get("unread") in {"1", "true", "True"}:
            queryset = queryset.filter(read_at__isnull=True)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset, request)
        response = paginator.get_paginated_response(
            NotificationSerializer(page, many=True).data
        ).data
        response["unread_count"] = Notification.objects.filter(
            recipient=request.user, read_at__isnull=True
        ).count()
        return Response(response)

    def post(self, request):
        """Marque les notifications non lues de l'utilisateur courant comme lues."""
        updated = mark_all_notifications_read(user=request.user)
        return Response({"updated": updated})


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "unread_count": Notification.objects.filter(
                    recipient=request.user, read_at__isnull=True
                ).count()
            }
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        mark_notification_read(notification=notification, user=request.user)
        return Response(NotificationSerializer(notification).data)


class OperationsTaskListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_operations_access(request.user)
        queryset = CeleryTaskLog.objects.all()
        state = request.query_params.get("state", "").upper()
        if state:
            queryset = queryset.filter(state=state)
        name = request.query_params.get("name", "")
        if name:
            queryset = queryset.filter(name__icontains=name[:100])
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(CeleryTaskLogSerializer(page, many=True).data)


class OperationsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_operations_access(request.user)
        from apps.core.metrics import metrics_snapshot
        from apps.notifications.models import BusinessEvent

        task_states = {
            row["state"]: row["total"]
            for row in CeleryTaskLog.objects.values("state").annotate(total=Count("id"))
        }
        return Response(
            {
                "tasks": task_states,
                "pending_events": BusinessEvent.objects.filter(dispatched_at__isnull=True).count(),
                "api": metrics_snapshot(),
            }
        )


__all__ = [
    "NotificationListView",
    "NotificationReadView",
    "NotificationUnreadCountView",
    "OperationsSummaryView",
    "OperationsTaskListView",
]
