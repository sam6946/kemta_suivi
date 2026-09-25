"""Sérialiseurs projets et membres de projet."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Q
from rest_framework import serializers

from apps.core.exceptions import KemtaAPIError
from apps.core.money import validate_fcfa_amount
from apps.core.serializers import FcfaField, ModelValidationMixin
from apps.organizations.models import Organization
from apps.organizations.serializers import MemberWriteSerializer
from apps.projects.access import (
    accessible_organizations,
    permissions_payload,
    resolve_capabilities,
)
from apps.projects.models import Currency, Project, ProjectMember, ProjectStatus
from apps.users.roles import Role
from apps.users.serializers import UserSerializer


class ProjectSerializer(ModelValidationMixin, serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.none())
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by = UserSerializer(read_only=True)
    member_count = serializers.IntegerField(read_only=True, default=0)
    permissions = serializers.SerializerMethodField()
    # Champs déclarés explicitement : on veut des codes d'erreur métier documentés
    # (`amount_has_cents`, `currency_not_supported`) plutôt que les messages génériques de DRF.
    budget_total = FcfaField(required=False, default=Decimal("0"))
    currency = serializers.CharField(required=False)

    class Meta:
        model = Project
        fields = [
            "id",
            "organization",
            "organization_name",
            "name",
            "code",
            "description",
            "location_label",
            "city",
            "region",
            "latitude",
            "longitude",
            "geofence_radius_m",
            "currency",
            "budget_total",
            "status",
            "status_label",
            "progress",
            "planned_start_date",
            "planned_end_date",
            "actual_start_date",
            "actual_end_date",
            "created_by",
            "member_count",
            "permissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "progress",  # toujours calculé côté serveur
            "created_by",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # On ne peut rattacher un projet qu'à une organisation que l'on pilote.
            self.fields["organization"].queryset = (
                accessible_organizations(request.user)
                .filter(
                    Q(owner=request.user)
                    | Q(
                        members__user=request.user,
                        members__is_active=True,
                        members__role=Role.ORG_OWNER,
                    )
                )
                .distinct()
            )

    # -- Champs -------------------------------------------------------------
    def validate_name(self, value: str) -> str:
        name = (value or "").strip()
        if len(name) < 3:
            raise serializers.ValidationError(
                "Le nom du projet doit contenir au moins 3 caractères."
            )
        return name

    def validate_code(self, value: str) -> str:
        return (value or "").strip().upper()

    def validate_status(self, value: str) -> str:
        if value not in ProjectStatus.values:
            raise serializers.ValidationError("Statut inconnu.")
        return value

    def validate_currency(self, value: str) -> str:
        currency = (value or "").upper()
        if currency not in Currency.values:
            raise KemtaAPIError(
                "currency_not_supported",
                "La devise du MVP est le franc CFA (XAF).",
                details={"supported": [Currency.XAF]},
            )
        return currency

    def validate_budget_total(self, value) -> Decimal:
        return validate_fcfa_amount(value, field="budget_total")

    def validate(self, attrs: dict) -> dict:
        def value(field):
            return attrs.get(field, getattr(self.instance, field, None))

        start, end = value("planned_start_date"), value("planned_end_date")
        if start and end and start > end:
            raise KemtaAPIError(
                "dates_inconsistent",
                "La fin prévue doit être postérieure au début prévu.",
                details={"field": "planned_end_date"},
            )
        actual_start, actual_end = value("actual_start_date"), value("actual_end_date")
        if actual_start and actual_end and actual_start > actual_end:
            raise KemtaAPIError(
                "dates_inconsistent",
                "La fin réelle doit être postérieure au début réel.",
                details={"field": "actual_end_date"},
            )

        organization = attrs.get("organization", getattr(self.instance, "organization", None))
        code = attrs.get("code", getattr(self.instance, "code", ""))
        if organization and code:
            duplicates = Project.objects.filter(organization=organization, code=code)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise KemtaAPIError(
                    "project_code_taken",
                    "Un projet de cette organisation utilise déjà ce code.",
                    http_status=409,
                    details={"field": "code"},
                )
        return attrs

    # -- Charge utile -------------------------------------------------------
    def get_permissions(self, obj: Project) -> dict:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return {}

        # En liste, les capacités sont précalculées (une seule passe, pas de N+1).
        capabilities_map = self.context.get("capabilities_by_project")
        if capabilities_map is not None and obj.pk in capabilities_map:
            return permissions_payload(capabilities_map[obj.pk])
        return permissions_payload(resolve_capabilities(user, obj))

    def create(self, validated_data):
        project = Project(**validated_data)
        self._save_with_model_validation(project.save)
        return project

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        self._save_with_model_validation(instance.save)
        return instance

    @staticmethod
    def with_counts(queryset):
        """Compteurs annotés : une seule requête, aucune requête par ligne."""
        return queryset.select_related("organization", "created_by").annotate(
            member_count=Count("members", filter=Q(members__is_active=True), distinct=True)
        )


class ProjectMemberWriteSerializer(MemberWriteSerializer):
    """Ajout ou modification d'un membre de projet (compte existant obligatoire)."""

    can_validate_evidence = serializers.BooleanField(required=False, default=False)
    can_manage_finance = serializers.BooleanField(required=False, default=False)


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = ProjectMember
        fields = [
            "id",
            "user",
            "role",
            "role_label",
            "can_validate_evidence",
            "can_manage_finance",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
