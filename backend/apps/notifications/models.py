"""Outbox métier, notifications regroupées et journal d'exécution Celery."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class BusinessEventType(models.TextChoices):
    MILESTONE_VALIDATED = "MILESTONE_VALIDATED", "Jalon validé"
    EXPENSE_SUBMITTED = "EXPENSE_SUBMITTED", "Dépense soumise"
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED", "Preuve rejetée"
    BUDGET_THRESHOLD_REACHED = "BUDGET_THRESHOLD_REACHED", "Seuil budgétaire atteint"
    PROJECT_DELAYED = "PROJECT_DELAYED", "Projet en retard"


class BusinessEvent(models.Model):
    """Outbox durable : l'événement métier est écrit dans la transaction qui le déclenche."""

    event_type = models.CharField(max_length=40, choices=BusinessEventType.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_events",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_events",
    )
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_events",
    )
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    dispatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dispatch_error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["dispatched_at", "created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="uniq_business_event_dedupe_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_type} · {self.entity_type} #{self.entity_id}"


class Notification(models.Model):
    """Notification privée d'un utilisateur ; les événements proches sont regroupés."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=40, choices=BusinessEventType.choices, db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    title = models.CharField(max_length=180)
    body = models.CharField(max_length=500)
    payload = models.JSONField(default=dict, blank=True)
    group_key = models.CharField(max_length=180)
    count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_seen_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "read_at", "last_seen_at"]),
            models.Index(fields=["recipient", "group_key", "read_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self) -> str:
        return f"{self.title} · utilisateur #{self.recipient_id}"


class CeleryTaskLog(models.Model):
    """Journal minimal des tâches ; jamais d'arguments, d'OTP ou de jeton conservés."""

    task_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, db_index=True)
    state = models.CharField(max_length=24, db_index=True)
    retries = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["state", "updated_at"])]

    def __str__(self) -> str:
        return f"{self.name} · {self.state} · {self.task_id}"
