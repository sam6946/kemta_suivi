"""Quarantaine et accès privé aux justificatifs de dépense."""

from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.evidences.tasks import scan_expense_receipt
from apps.finance.models import Expense, ReceiptScanStatus


@pytest.mark.django_db
def test_infected_receipt_is_deleted_and_signed_link_cannot_serve_it(
    auth_client, expense, project_context, receipt, monkeypatch
):
    upload = auth_client(project_context["finance"]).post(
        f"/api/expenses/{expense.pk}/receipt/", {"file": receipt()}, format="multipart"
    )
    assert upload.status_code == 201, upload.data
    signed_url = upload.data["receipt_url"]
    expense.refresh_from_db()
    original_path = expense.receipt.path
    assert expense.receipt_scan_status == ReceiptScanStatus.CLEAN

    Expense.objects.filter(pk=expense.pk).update(receipt_scan_status=ReceiptScanStatus.PENDING)
    monkeypatch.setattr(
        "apps.evidences.tasks.scan_file", lambda _field: ("INFECTED", "Eicar-Test-Signature")
    )

    assert scan_expense_receipt.run(expense.pk) is False

    expense.refresh_from_db()
    assert expense.receipt_scan_status == ReceiptScanStatus.INFECTED
    assert expense.receipt_scan_result == "Eicar-Test-Signature"
    assert not expense.receipt
    assert not Path(original_path).exists()
    response = APIClient().get(signed_url)
    assert response.status_code == 404
