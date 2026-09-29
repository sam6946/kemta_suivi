"""Analyse antivirus puis dérivées d'images, hors du cycle HTTP."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.evidences.antivirus import AntivirusUnavailable, scan_file
from apps.evidences.models import Evidence, MediaScanStatus
from apps.evidences.storage import build_derivatives

logger = logging.getLogger("kemta.tasks")


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    retry_backoff=True,
    retry_jitter=True,
    name="apps.evidences.generate_evidence_derivatives",
)
def generate_evidence_derivatives(self, evidence_id: int) -> bool:
    """Scanne la pièce, la met en quarantaine si nécessaire, puis crée ses deux dérivées."""
    try:
        evidence = Evidence.objects.select_related("project").get(pk=evidence_id)
    except Evidence.DoesNotExist:
        logger.warning("Preuve %s introuvable : traitement média ignoré", evidence_id)
        return False

    if evidence.scan_status == MediaScanStatus.INFECTED:
        return False
    if not evidence.file:
        return False

    if evidence.scan_status != MediaScanStatus.CLEAN:
        evidence.scan_status = MediaScanStatus.SCANNING
        evidence.save(update_fields=["scan_status", "updated_at"])
        try:
            result, signature = scan_file(evidence.file)
        except AntivirusUnavailable as exc:
            Evidence.objects.filter(pk=evidence.pk).update(scan_status=MediaScanStatus.ERROR)
            logger.warning(
                "Scanner indisponible pour la preuve %s ; média conservé en quarantaine",
                evidence_id,
            )
            raise self.retry(exc=exc) from exc

        if result == "INFECTED":
            evidence.file.delete(save=False)
            evidence.thumbnail.delete(save=False)
            evidence.list_version.delete(save=False)
            evidence.scan_status = MediaScanStatus.INFECTED
            evidence.scan_result = signature[:100]
            evidence.scanned_at = timezone.now()
            evidence.save(
                update_fields=[
                    "file",
                    "thumbnail",
                    "list_version",
                    "scan_status",
                    "scan_result",
                    "scanned_at",
                    "updated_at",
                ]
            )
            logger.warning("Fichier de preuve bloqué par l'antivirus (preuve %s)", evidence_id)
            return False

        evidence.scan_status = MediaScanStatus.CLEAN
        evidence.scan_result = ""
        evidence.scanned_at = timezone.now()
        evidence.save(update_fields=["scan_status", "scan_result", "scanned_at", "updated_at"])

    try:
        with evidence.file.open("rb") as handle:
            derivatives = build_derivatives(handle.read())
        evidence.thumbnail.save(derivatives["thumbnail"].name, derivatives["thumbnail"], save=False)
        evidence.list_version.save(
            derivatives["list_version"].name, derivatives["list_version"], save=False
        )
        evidence.save(update_fields=["thumbnail", "list_version", "updated_at"])
    except Exception as exc:  # erreur stockage/décodage : le worker réessaie, aucun secret en log
        logger.warning("Échec de génération des dérivées de la preuve %s", evidence_id)
        raise self.retry(exc=exc) from exc

    return True


@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    retry_backoff=True,
    retry_jitter=True,
    name="apps.evidences.scan_expense_receipt",
)
def scan_expense_receipt(self, expense_id: int) -> bool:
    """Valide aussi les justificatifs financiers (PDF/photo) avec le même scanner ClamAV."""
    from apps.finance.models import Expense, ReceiptScanStatus

    expense = Expense.objects.filter(pk=expense_id).first()
    if expense is None or not expense.receipt:
        return False
    if expense.receipt_scan_status == ReceiptScanStatus.INFECTED:
        return False

    expense.receipt_scan_status = ReceiptScanStatus.SCANNING
    expense.save(update_fields=["receipt_scan_status", "updated_at"])
    try:
        result, signature = scan_file(expense.receipt)
    except AntivirusUnavailable as exc:
        Expense.objects.filter(pk=expense.pk).update(receipt_scan_status=ReceiptScanStatus.ERROR)
        logger.warning("Scanner indisponible pour le justificatif de dépense %s", expense_id)
        raise self.retry(exc=exc) from exc

    if result == "INFECTED":
        expense.receipt.delete(save=False)
        expense.receipt_scan_status = ReceiptScanStatus.INFECTED
        expense.receipt_scan_result = signature[:100]
        expense.receipt_scanned_at = timezone.now()
        expense.save(
            update_fields=[
                "receipt",
                "receipt_scan_status",
                "receipt_scan_result",
                "receipt_scanned_at",
                "updated_at",
            ]
        )
        logger.warning("Justificatif bloqué par l'antivirus (dépense %s)", expense_id)
        return False

    expense.receipt_scan_status = ReceiptScanStatus.CLEAN
    expense.receipt_scan_result = ""
    expense.receipt_scanned_at = timezone.now()
    expense.save(
        update_fields=[
            "receipt_scan_status",
            "receipt_scan_result",
            "receipt_scanned_at",
            "updated_at",
        ]
    )
    return True


@shared_task(name="apps.evidences.retry_pending_media_scans")
def retry_pending_media_scans(batch_size: int = 200) -> int:
    """Récupère les tâches perdues après indisponibilité du broker ou du moteur antivirus."""
    from apps.finance.models import Expense, ReceiptScanStatus

    stale_before = timezone.now() - timedelta(minutes=2)
    evidence_ids = list(
        Evidence.objects.filter(
            scan_status__in=(
                MediaScanStatus.PENDING,
                MediaScanStatus.SCANNING,
                MediaScanStatus.ERROR,
            ),
            updated_at__lt=stale_before,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    receipt_ids = list(
        Expense.objects.filter(
            receipt__isnull=False,
            receipt_scan_status__in=(
                ReceiptScanStatus.PENDING,
                ReceiptScanStatus.SCANNING,
                ReceiptScanStatus.ERROR,
            ),
            updated_at__lt=stale_before,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    for evidence_id in evidence_ids:
        generate_evidence_derivatives.delay(evidence_id)
    for expense_id in receipt_ids:
        scan_expense_receipt.delay(expense_id)
    return len(evidence_ids) + len(receipt_ids)
