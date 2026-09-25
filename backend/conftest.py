"""Fixtures partagées : isolation du cache, boîte SMS, utilisateurs de test."""

from __future__ import annotations

import logging
import re

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.users.models import OTPCode, User
from apps.users.services import email as email_service
from apps.users.services import sms

TEST_PHONE = "+237690123456"
TEST_PHONE_2 = "+237677888999"
# Conforme à la politique : > 10 caractères, non courant, non similaire aux attributs.
STRONG_PASSWORD = "Kemta#2026Douala"
NEW_STRONG_PASSWORD = "Chantier#2026Kribi"
CODE_RE = re.compile(r"code de vérification est (\d{6})")


@pytest.fixture(autouse=True)
def clear_cache():
    """Les compteurs de rate limiting et le cache de rôles doivent repartir de zéro."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def reset_sms_outbox():
    sms.reset_outbox()
    email_service.reset_outbox()
    yield
    sms.reset_outbox()
    email_service.reset_outbox()


@pytest.fixture(autouse=True)
def propagate_app_logs():
    """Permet à `caplog` de capturer les logs applicatifs pendant les tests."""
    logger = logging.getLogger("kemta")
    previous = logger.propagate
    logger.propagate = True
    yield
    logger.propagate = previous


@pytest.fixture()
def api():
    return APIClient()


@pytest.fixture()
def phone():
    return TEST_PHONE


@pytest.fixture()
def password():
    return STRONG_PASSWORD


@pytest.fixture()
def last_sms_code():
    """Retourne le dernier code OTP envoyé (mode console)."""

    def _get(index: int = -1) -> str:
        message = sms.outbox[index]["message"]
        match = CODE_RE.search(message)
        assert match, f"Aucun code trouvé dans : {message}"
        return match.group(1)

    return _get


@pytest.fixture()
def last_email_code():
    """Retourne le dernier code OTP envoyé par email (mode console)."""

    def _get(index: int = -1) -> str:
        message = email_service.outbox[index]["message"]
        match = CODE_RE.search(message)
        assert match, f"Aucun code trouvé dans : {message}"
        return match.group(1)

    return _get


@pytest.fixture()
def register_and_activate(api, last_sms_code):
    """Crée un utilisateur activé (inscription + OTP) et retourne l'objet `User`."""

    def _make(phone_number: str = TEST_PHONE, pwd: str = STRONG_PASSWORD, **extra):
        payload = {
            "phone": phone_number,
            "password": pwd,
            "password_confirm": pwd,
            "first_name": "Arnaud",
            "last_name": "Nkoulou",
            **extra,
        }
        response = api.post("/api/auth/register/", payload, format="json")
        assert response.status_code == 201, response.content
        code = last_sms_code()
        verify = api.post(
            "/api/auth/otp/verify/",
            {"phone": phone_number, "code": code, "purpose": "SIGNUP"},
            format="json",
        )
        assert verify.status_code == 200, verify.content
        return User.objects.get(phone=phone_number), verify.data

    return _make


@pytest.fixture()
def active_user(register_and_activate):
    user, _ = register_and_activate()
    return user


@pytest.fixture()
def reset_otp(api, last_sms_code):
    """Déclenche une demande de réinitialisation et retourne le code reçu."""

    def _request(phone_number: str = TEST_PHONE) -> str:
        response = api.post(
            "/api/auth/password/reset/request/", {"phone": phone_number}, format="json"
        )
        assert response.status_code == 200, response.content
        return last_sms_code()

    return _request


@pytest.fixture()
def otp_record():
    def _get(phone_number: str = TEST_PHONE, purpose: str = OTPCode.Purpose.SIGNUP):
        return OTPCode.objects.filter(phone=phone_number, purpose=purpose).order_by("-created_at").first()

    return _get
