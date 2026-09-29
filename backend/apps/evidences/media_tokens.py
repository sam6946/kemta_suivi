"""Jetons de média signés, courts et liés à un utilisateur et une preuve."""

from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired

SIGNING_SALT = "kemta.evidence-media.v1"


def issue_media_token(*, evidence, user, variant: str) -> str:
    if variant not in {"file", "thumbnail"}:
        raise ValueError("Variante média non supportée.")
    return signing.dumps(
        {
            "evidence_id": evidence.pk,
            "project_id": evidence.project_id,
            "user_id": user.pk,
            "variant": variant,
        },
        salt=SIGNING_SALT,
        compress=True,
    )


def verify_media_token(token: str) -> dict | None:
    try:
        payload = signing.loads(
            token,
            salt=SIGNING_SALT,
            max_age=settings.SIGNED_MEDIA_TOKEN_TTL_SECONDS,
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("variant") not in {"file", "thumbnail"}:
        return None
    return payload
