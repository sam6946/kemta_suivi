"""Métadonnées partagées avec le frontend (source unique des rôles)."""

from django.core.cache import cache
from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.roles import roles_payload

ROLES_CACHE_KEY = "kemta:meta:roles"
ROLES_CACHE_TTL = 3600


class RolesMetaView(APIView):
    """`GET /api/meta/roles/` — les 9 rôles et leurs capacités."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        payload = cache.get(ROLES_CACHE_KEY)
        if payload is None:
            payload = roles_payload()
            cache.set(ROLES_CACHE_KEY, payload, ROLES_CACHE_TTL)
        return Response({"results": payload})


urlpatterns = [
    path("roles/", RolesMetaView.as_view(), name="meta-roles"),
]
