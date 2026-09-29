"""Consultation paginée du journal projet, filtrée par la capacité VIEW_ACTIVITY."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.exceptions import KemtaAPIError
from apps.core.models import ActivityLog
from apps.core.pagination import DefaultPagination
from apps.projects.access import accessible_projects, has_project_capability
from apps.users.roles import Capability


class ProjectActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = get_object_or_404(
            accessible_projects(request.user).select_related("organization"), pk=pk
        )
        if not has_project_capability(request.user, project, Capability.VIEW_ACTIVITY):
            raise KemtaAPIError(
                "permission_denied",
                "Votre rôle ne permet pas de consulter le journal de ce projet.",
                http_status=403,
            )
        queryset = ActivityLog.objects.filter(project=project).select_related("actor")
        action = request.query_params.get("action", "").upper()
        if action:
            if action not in ActivityLog.Action.values:
                raise KemtaAPIError("invalid_action", "Action de journal inconnue.")
            queryset = queryset.filter(action=action)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset, request)
        results = [
            {
                "id": event.pk,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "organization": event.organization_id,
                "project": event.project_id,
                "actor": {
                    "id": event.actor_id,
                    "first_name": event.actor.first_name,
                    "last_name": event.actor.last_name,
                    "role": event.actor.role,
                }
                if event.actor_id
                else None,
                "metadata": event.metadata,
                "created_at": event.created_at,
            }
            for event in page
        ]
        return paginator.get_paginated_response(results)
