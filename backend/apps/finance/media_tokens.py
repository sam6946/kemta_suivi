"""Liens média courts et révocables pour les justificatifs financiers."""

from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired

SIGNING_SALT = "kemta.finance-receipt.v1"


def issue_receipt_token(*, expense, user) -> str:
    return signing.dumps(
        {
            "expense_id": expense.pk,
            "project_id": expense.project_id,
            "user_id": user.pk,
        },
        salt=SIGNING_SALT,
        compress=True,
    )


def verify_receipt_token(token: str) -> dict | None:
    try:
        payload = signing.loads(
            token, salt=SIGNING_SALT, max_age=settings.SIGNED_MEDIA_TOKEN_TTL_SECONDS
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload
