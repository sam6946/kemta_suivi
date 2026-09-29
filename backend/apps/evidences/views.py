"""Endpoints des preuves terrain (MVP-007, MVP-008).

Contrats appliqués (voir `docs/api-contract.md` §6) :

* upload `multipart` avec en-tête **`Idempotency-Key` obligatoire** : un renvoi après coupure
  réseau retourne la preuve déjà enregistrée (`200`, `Idempotency-Replayed: true`) au lieu de
  créer un doublon ;
* doublon de contenu (`project`, `hash_sha256`) → `409 duplicate_evidence` **avec la preuve
  existante** dans les détails, ce qui permet au terrain de comprendre et de ne pas insister ;
* fichier non conforme → `413` (taille), `415` (type réel), `400` (dimensions) ;
* GPS disponible mais hors périmètre → `422 evidence_out_of_geofence` (comportement piloté par
  `EVIDENCE_GEOFENCE_ENFORCE`) ;
* les médias ne sont **jamais** servis publiquement : `/api/evidences/{id}/file/` vérifie
  l'appartenance au projet avant de délivrer la pièce (et délègue à Nginx via
  `X-Accel-Redirect` en production).
"""

from __future__ import annotations

import logging
import mimetypes
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.activity import log_event
from apps.core.exceptions import KemtaAPIError
from apps.core.metrics import increment_metric
from apps.evidences.access import accessible_evidences
from apps.evidences.media_tokens import verify_media_token
from apps.evidences.models import (
    Evidence,
    EvidenceStatus,
    MediaScanStatus,
    SyncStatus,
)
from apps.evidences.quotas import enforce_media_quota
from apps.evidences.serializers import (
    EvidenceCreateSerializer,
    EvidenceSerializer,
    EvidenceTransitionSerializer,
    EvidenceValidationSerializer,
    distance_meters,
)
from apps.evidences.services import apply_transition
from apps.evidences.storage import read_and_validate_upload, sha256_of
from apps.evidences.tasks import generate_evidence_derivatives
from apps.projects.access import accessible_projects, has_project_capability
from apps.projects.models import Task
from apps.users.roles import Capability

logger = logging.getLogger("kemta.evidences")

EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def serialize(evidence: Evidence, request) -> dict:
    return EvidenceSerializer(evidence, context={"request": request, "user": request.user}).data


class EvidenceCreateView(APIView):
    """`POST /api/evidences/` — dépôt d'une preuve depuis le terrain."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get(
            "HTTP_IDEMPOTENCY_KEY"
        )
        if not idempotency_key:
            raise KemtaAPIError(
                "idempotency_key_required",
                "L'en-tête « Idempotency-Key » est obligatoire : il évite les doublons "
                "lorsqu'un envoi est réessayé après une coupure réseau.",
            )
        if len(idempotency_key) > 64:
            raise KemtaAPIError("idempotency_key_invalid", "Clé d'idempotence trop longue.")

        # 1. Rejeu d'un envoi déjà reçu : on renvoie la preuve existante, sans rien recréer.
        replayed = (
            Evidence.objects.filter(author=request.user, idempotency_key=idempotency_key)
            .select_related("project", "author", "task")
            .first()
        )
        if replayed is not None:
            return Response(
                serialize(replayed, request),
                status=status.HTTP_200_OK,
                headers={"Idempotency-Replayed": "true"},
            )

        # 2. Périmètre : un projet hors portée produit un 404 (jamais un 403 qui le révélerait).
        project_id = request.data.get("project")
        project = get_object_or_404(accessible_projects(request.user), pk=project_id)
        if not has_project_capability(request.user, project, Capability.CAPTURE_EVIDENCE):
            raise KemtaAPIError(
                "permission_denied",
                "Votre rôle sur ce projet ne permet pas de déposer une preuve.",
                http_status=403,
            )

        # 3. Métadonnées (formes, cohérence GPS / coordonnées, tâche du bon projet).
        serializer = EvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 4. Fichier : taille puis type **réel** puis dimensions.
        payload, content_type = read_and_validate_upload(data["file"])
        digest = sha256_of(payload)

        # 5. Doublon de contenu dans le même projet.
        duplicate = (
            Evidence.objects.filter(project=project, hash_sha256=digest)
            .select_related("project", "author", "task")
            .first()
        )
        if duplicate is not None:
            return Response(
                {
                    "error": {
                        "code": "duplicate_evidence",
                        "message": "Cette photo a déjà été déposée sur ce projet.",
                        "details": {"evidence": serialize(duplicate, request)},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 6. Périmètre géographique : on refuse une preuve manifestement prise ailleurs.
        distance = None
        if (
            data.get("latitude") is not None
            and project.latitude is not None
            and project.longitude is not None
        ):
            distance = distance_meters(
                float(data["latitude"]),
                float(data["longitude"]),
                float(project.latitude),
                float(project.longitude),
            )
            if distance > project.geofence_radius_m and settings.EVIDENCE_GEOFENCE_ENFORCE:
                raise KemtaAPIError(
                    "evidence_out_of_geofence",
                    "La photo a été prise hors du périmètre du chantier "
                    f"({distance:.0f} m du site, périmètre de {project.geofence_radius_m} m).",
                    http_status=422,
                    details={
                        "distance_m": round(distance, 1),
                        "radius_m": project.geofence_radius_m,
                    },
                )

        captured_at = data["captured_at"]
        extension = EXTENSION_BY_CONTENT_TYPE.get(content_type, "jpg")
        task: Task | None = data.get("task")

        with transaction.atomic():
            enforce_media_quota(
                project_id=project.pk, actor_id=request.user.pk, new_size=len(payload)
            )
            evidence = Evidence(
                project=project,
                author=request.user,
                task=task,
                captured_at=captured_at,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                gps_accuracy=data.get("gps_accuracy"),
                gps_status=data["gps_status"],
                device_model=(data.get("device_model") or "")[:120],
                device_platform=(data.get("device_platform") or "")[:60],
                app_version=(data.get("app_version") or "")[:32],
                description=data.get("description") or "",
                hash_sha256=digest,
                idempotency_key=idempotency_key,
                size_bytes=len(payload),
                content_type=content_type,
                status=EvidenceStatus.PENDING,
                sync_status=SyncStatus.SYNCED,
            )
            evidence.file.save(f"original.{extension}", ContentFile(payload), save=False)
            evidence.save()

            log_event(
                "EVIDENCE_CAPTURED",
                actor=request.user,
                entity_type="Evidence",
                entity_id=evidence.pk,
                organization=project.organization,
                project=project,
                metadata={
                    "hash_sha256": digest[:12],  # empreinte tronquée : suffisante pour la trace
                    "size_bytes": len(payload),
                    "content_type": content_type,
                    "gps_status": evidence.gps_status,
                    "distance_m": round(distance, 1) if distance is not None else None,
                    "inside_geofence": None
                    if distance is None
                    else distance <= project.geofence_radius_m,
                    "task": task.pk if task else None,
                    "captured_at": captured_at.isoformat(),
                },
                request=request,
            )

        increment_metric("evidence_upload_total")
        increment_metric("evidence_upload_bytes_total", len(payload))

        # 7. Analyse antivirus et dérivées hors du cycle HTTP. Si Redis est indisponible,
        # la preuve reste en quarantaine et une tâche planifiée la reprendra.
        try:
            generate_evidence_derivatives.delay(evidence.pk)
        except Exception:
            logger.warning(
                "Analyse média de la preuve %s différée : broker indisponible", evidence.pk
            )

        evidence.refresh_from_db()
        return Response(
            serialize(evidence, request),
            status=status.HTTP_201_CREATED,
            headers={"Idempotency-Replayed": "false"},
        )


class ProjectEvidenceListView(APIView):
    """`GET /api/projects/{id}/evidences/` — galerie paginée du chantier."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project = get_object_or_404(accessible_projects(request.user), pk=pk)
        queryset = (
            Evidence.objects.filter(project=project)
            .select_related("author", "task", "project")
            .prefetch_related("validations")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            values = [value.upper() for value in status_filter.split(",") if value]
            unknown = [value for value in values if value not in EvidenceStatus.values]
            if unknown:
                raise KemtaAPIError(
                    "invalid_status", "Statut inconnu.", details={"unknown": unknown}
                )
            queryset = queryset.filter(status__in=values)

        sync_filter = request.query_params.get("sync_status")
        if sync_filter:
            queryset = queryset.filter(sync_status=sync_filter.upper())

        author = request.query_params.get("author")
        if author:
            queryset = queryset.filter(author_id=author)

        task = request.query_params.get("task")
        if task:
            queryset = queryset.filter(task_id=task)

        pending_only = request.query_params.get("pending")
        if pending_only in {"1", "true", "True"}:
            queryset = queryset.filter(status=EvidenceStatus.PENDING)

        from apps.core.pagination import DefaultPagination

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset.order_by("-captured_at", "-id"), request)
        page = list(page)
        from apps.projects.access import build_capabilities_map

        capabilities = build_capabilities_map(
            request.user, {evidence.project_id: evidence.project for evidence in page}.values()
        )
        serializer = EvidenceSerializer(
            page,
            many=True,
            context={
                "request": request,
                "user": request.user,
                "capabilities_by_project": capabilities,
            },
        )
        payload = paginator.get_paginated_response(serializer.data).data
        payload["counts"] = {
            "pending": Evidence.objects.filter(
                project=project, status=EvidenceStatus.PENDING
            ).count(),
            "validated": Evidence.objects.filter(
                project=project, status=EvidenceStatus.VALIDATED
            ).count(),
            "rejected": Evidence.objects.filter(
                project=project, status=EvidenceStatus.REJECTED
            ).count(),
            "flagged": Evidence.objects.filter(
                project=project, status=EvidenceStatus.FLAGGED
            ).count(),
        }
        return Response(payload)


class EvidenceDetailView(APIView):
    """`GET /api/evidences/{id}/` — détail et historique de validation."""

    permission_classes = [IsAuthenticated]

    def get_evidence(self, request, pk) -> Evidence:
        return get_object_or_404(
            accessible_evidences(request.user).prefetch_related("validations__actor"), pk=pk
        )

    def get(self, request, pk):
        evidence = self.get_evidence(request, pk)
        payload = serialize(evidence, request)
        return Response(payload)


class EvidenceHistoryView(APIView):
    """`GET /api/evidences/{id}/history/` — historique paginé (append-only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        evidence = get_object_or_404(accessible_evidences(request.user), pk=pk)
        validations = evidence.validations.select_related("actor").order_by("created_at", "id")
        from apps.core.pagination import DefaultPagination

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(validations, request)
        return paginator.get_paginated_response(EvidenceValidationSerializer(page, many=True).data)


class EvidenceTransitionView(APIView):
    """`POST /api/evidences/{id}/transition/` — valider, rejeter, signaler, rouvrir.

    La règle métier vit dans `apps.evidences.services.apply_transition` : le même service sert
    la reprise hors ligne (`/api/sync/batch/`), donc aucune divergence possible entre les deux.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        evidence = get_object_or_404(
            Evidence.objects.filter(project__in=accessible_projects(request.user)).select_related(
                "project", "author"
            ),
            pk=pk,
        )
        serializer = EvidenceTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        apply_transition(
            evidence=evidence,
            actor=request.user,
            action=serializer.validated_data["action"],
            comment=serializer.validated_data.get("comment") or "",
            request=request,
        )

        payload = serialize(evidence, request)
        payload["last_validation"] = EvidenceValidationSerializer(
            evidence.validations.order_by("-created_at").first()
        ).data
        return Response(payload, status=status.HTTP_200_OK)


def serve_evidence_media(evidence: Evidence, variant: str):
    """Envoie une image déjà analysée ; les fichiers en quarantaine ne sont jamais accessibles."""
    if evidence.scan_status != MediaScanStatus.CLEAN:
        raise KemtaAPIError(
            "media_scan_pending"
            if evidence.scan_status != MediaScanStatus.INFECTED
            else "media_blocked",
            "Le fichier est indisponible tant que son analyse de sécurité n'est pas terminée.",
            http_status=423,
        )

    if variant == "thumbnail" and evidence.thumbnail:
        field = evidence.thumbnail
        content_type = mimetypes.guess_type(field.name)[0] or "image/jpeg"
    else:
        field = evidence.file
        content_type = evidence.content_type or mimetypes.guess_type(field.name)[0]
    if not field:
        raise KemtaAPIError("file_not_available", "Fichier indisponible.", http_status=404)

    if settings.MEDIA_X_ACCEL_REDIRECT:
        response = HttpResponse(status=200)
        response["X-Accel-Redirect"] = f"/protected-media/{field.name}"
        response["Content-Type"] = content_type or "application/octet-stream"
    else:
        response = FileResponse(
            field.open("rb"), content_type=content_type or "application/octet-stream"
        )
        response["Content-Disposition"] = f'inline; filename="{field.name.rsplit("/", 1)[-1]}"'
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class EvidenceFileView(APIView):
    """`GET /api/evidences/{id}/file/` et `/thumbnail/` — accès JWT et périmètre projet."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, variant: str):
        evidence = get_object_or_404(accessible_evidences(request.user), pk=pk)
        return serve_evidence_media(evidence, variant)


class SignedEvidenceMediaView(APIView):
    """Accès image sans JWT via une URL signée à durée de vie courte (pour `<img src>`)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, token: str):
        payload = verify_media_token(token)
        if payload is None:
            raise KemtaAPIError(
                "signed_media_invalid", "Lien média invalide ou expiré.", http_status=404
            )

        from apps.users.models import User

        user = User.objects.filter(
            pk=payload.get("user_id"),
            is_active=True,
            is_phone_verified=True,
            deleted_at__isnull=True,
        ).first()
        if user is None:
            raise KemtaAPIError(
                "signed_media_invalid", "Lien média invalide ou expiré.", http_status=404
            )
        evidence = (
            accessible_evidences(user)
            .filter(pk=payload.get("evidence_id"), project_id=payload.get("project_id"))
            .first()
        )
        if evidence is None:
            raise KemtaAPIError(
                "signed_media_invalid", "Lien média invalide ou expiré.", http_status=404
            )
        return serve_evidence_media(evidence, payload["variant"])


class EvidencePendingCountView(APIView):
    """`GET /api/evidences/pending/` — file d'attente du validateur, tous projets confondus.

    Sert directement l'écran « À valider » : le validateur voit ce qui l'attend sans ouvrir
    chaque projet, et la limite de temps (`?older_than_hours=`) met en avant les preuves qui
    traînent.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = accessible_evidences(request.user).filter(status=EvidenceStatus.PENDING)
        older_than = request.query_params.get("older_than_hours")
        if older_than:
            try:
                hours = int(older_than)
            except ValueError as exc:
                raise KemtaAPIError(
                    "invalid_parameter", "« older_than_hours » doit être un entier."
                ) from exc
            queryset = queryset.filter(captured_at__lt=timezone.now() - timedelta(hours=hours))

        # Les capacités sont résolues une fois par projet, puis la pagination s'applique en SQL.
        from apps.projects.access import build_capabilities_map

        projects = list(accessible_projects(request.user).select_related("organization"))
        capabilities = build_capabilities_map(request.user, projects)
        valid_project_ids = [
            project_id
            for project_id, project_capabilities in capabilities.items()
            if project_capabilities.get(Capability.VALIDATE_EVIDENCE, False)
        ]
        queryset = (
            queryset.filter(project_id__in=valid_project_ids)
            .exclude(author_id=request.user.pk)
            .prefetch_related("validations")
        )
        from apps.core.pagination import DefaultPagination

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(queryset.order_by("captured_at", "id"), request)
        serializer = EvidenceSerializer(
            page,
            many=True,
            context={
                "request": request,
                "user": request.user,
                "capabilities_by_project": capabilities,
            },
        )
        return paginator.get_paginated_response(serializer.data)
