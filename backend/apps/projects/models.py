"""Projets et membres de projet : périmètre d'accès et de contrôle des données."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import SoftDeleteModel, TimeStampedModel
from apps.users.roles import ROLE_CHOICES


class ProjectStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    ACTIVE = "ACTIVE", "En cours"
    ON_HOLD = "ON_HOLD", "Suspendu"
    COMPLETED = "COMPLETED", "Terminé"
    ARCHIVED = "ARCHIVED", "Archivé"


class Currency(models.TextChoices):
    XAF = "XAF", "Franc CFA (FCFA)"


# Montant FCFA : entier, jamais de centimes (voir docs/data-model.md, conventions).
MAX_AMOUNT = Decimal("999999999999999")


class Project(TimeStampedModel, SoftDeleteModel):
    """Projet de chantier. **Toujours rattaché à une organisation.**"""

    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="organisation",
        on_delete=models.PROTECT,
        related_name="projects",
    )
    name = models.CharField("nom", max_length=180)
    code = models.CharField("code", max_length=32, blank=True)
    description = models.TextField("description", blank=True)
    location_label = models.CharField("localisation", max_length=200, blank=True)
    city = models.CharField("ville", max_length=80, blank=True)
    region = models.CharField("région", max_length=80, blank=True)
    latitude = models.DecimalField(
        "latitude", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "longitude", max_digits=9, decimal_places=6, null=True, blank=True
    )
    geofence_radius_m = models.PositiveIntegerField("rayon de périmètre (m)", default=500)

    currency = models.CharField(
        "devise", max_length=3, choices=Currency.choices, default=Currency.XAF
    )
    budget_total = models.DecimalField(
        "budget prévu (FCFA)", max_digits=15, decimal_places=0, default=0
    )
    status = models.CharField(
        "statut", max_length=16, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT
    )
    # Avancement calculé **côté serveur** (jalons/tâches à partir de la phase 4).
    progress = models.DecimalField(
        "avancement (%)", max_digits=5, decimal_places=2, default=Decimal("0")
    )

    planned_start_date = models.DateField("début prévu", null=True, blank=True)
    planned_end_date = models.DateField("fin prévue", null=True, blank=True)
    actual_start_date = models.DateField("début réel", null=True, blank=True)
    actual_end_date = models.DateField("fin réelle", null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        on_delete=models.PROTECT,
        related_name="created_projects",
    )

    class Meta:
        verbose_name = "projet"
        verbose_name_plural = "projets"
        ordering = ["-created_at"]
        constraints = [
            # Le code est unique au sein d'une organisation (parmi les projets non supprimés).
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=Q(deleted_at__isnull=True) & ~Q(code=""),
                name="uniq_project_code_per_organization",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["status", "deleted_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code or 'sans code'})"

    # -- Validation métier --------------------------------------------------
    def clean(self) -> None:
        errors: dict[str, str] = {}
        if (
            self.planned_start_date
            and self.planned_end_date
            and self.planned_start_date > self.planned_end_date
        ):
            errors["planned_end_date"] = "La fin prévue doit suivre le début prévu."
        if (
            self.actual_start_date
            and self.actual_end_date
            and self.actual_start_date > self.actual_end_date
        ):
            errors["actual_end_date"] = "La fin réelle doit suivre le début réel."
        if self.budget_total is not None:
            # La valeur peut arriver en `int`, `str` ou `Decimal` selon le point d'entrée.
            try:
                amount = Decimal(str(self.budget_total))
            except (ArithmeticError, ValueError):
                errors["budget_total"] = "Montant invalide."
                amount = None
            if amount is not None:
                self.budget_total = amount
                if amount < 0:
                    errors["budget_total"] = "Le budget ne peut pas être négatif."
                elif amount != amount.to_integral_value():
                    errors["budget_total"] = (
                        "Les montants sont exprimés en FCFA entiers (sans centimes)."
                    )
                elif amount > MAX_AMOUNT:
                    errors["budget_total"] = "Montant hors limites."
        for field, minimum, maximum in (
            ("latitude", Decimal("-90"), Decimal("90")),
            ("longitude", Decimal("-180"), Decimal("180")),
        ):
            coordinate = getattr(self, field)
            if coordinate is None:
                continue
            try:
                value = Decimal(str(coordinate))
            except (ArithmeticError, ValueError):
                errors[field] = "Coordonnées invalides."
                continue
            setattr(self, field, value)
            if not minimum <= value <= maximum:
                errors[field] = "Coordonnées hors limites."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.currency = (self.currency or Currency.XAF).upper()
        self.clean()
        return super().save(*args, **kwargs)


class ProjectMember(TimeStampedModel):
    """Accès d'un utilisateur à un projet : rôle projet + capacités fines.

    Le rôle du membre est **prioritaire** sur le rôle global pour tout ce qui concerne
    ce projet (voir `docs/rbac-matrix.md` §1).
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField("rôle sur le projet", max_length=32, choices=ROLE_CHOICES)
    can_validate_evidence = models.BooleanField("peut valider les preuves", default=False)
    can_manage_finance = models.BooleanField("peut gérer les finances", default=False)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "membre de projet"
        verbose_name_plural = "membres de projet"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="uniq_project_member")
        ]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self) -> str:
        return f"{self.user} @ {self.project} ({self.role})"
