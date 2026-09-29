"""Adaptateur d'envoi de SMS.

- `console` (développement et tests) : le message est conservé dans `outbox`, consultable via
  l'endpoint de développement. Il n'est jamais imprimé dans stdout ou les logs.
- `africastalking` : envoi via l'API HTTPS Africa's Talking ; les identifiants et l'URL
  viennent de l'environnement, jamais du code.
"""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger("kemta.sms")

# Boîte de réception des messages en mode console (tests et développement).
outbox: list[dict] = []


def reset_outbox() -> None:
    outbox.clear()


def send_sms(phone: str, message: str) -> bool:
    from apps.users.tasks import send_sms_task

    send_sms_task.delay(phone, message)
    return True


def deliver_sms(phone: str, message: str) -> None:
    """Envoi effectif (exécuté par le worker Celery, ou de façon synchrone en test)."""
    provider = settings.SMS_PROVIDER
    if provider == "console":
        # La boîte de développement est consultée via l'endpoint protégé ; aucun OTP dans stdout.
        outbox.append({"phone": phone, "message": message})
        return
    if provider in {"africastalking", "real"}:
        _send_with_provider(phone, message)
        return
    raise NotImplementedError(f"Fournisseur SMS inconnu : {provider}")


def _send_with_provider(phone: str, message: str) -> None:
    """Envoie un SMS via Africa's Talking et échoue explicitement en cas de rejet.

    La tâche Celery applique ensuite ses retries bornés. Ni le numéro, ni le code OTP,
    ni la clé API ne sont inclus dans les logs.
    """
    api_key = settings.SMS_API_KEY
    username = settings.SMS_USERNAME
    if not api_key or not username or not settings.SMS_SENDER_ID:
        raise RuntimeError("Le fournisseur SMS n'est pas configuré.")

    payload = json.dumps(
        {
            "username": username,
            "phoneNumbers": [phone],
            "message": message,
            "senderId": settings.SMS_SENDER_ID,
            "enqueue": 1,
        }
    ).encode("utf-8")
    request = Request(
        settings.SMS_API_URL,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.SMS_API_TIMEOUT_SECONDS) as response:
            raw_response = response.read(65_536)
    except HTTPError as exc:
        logger.warning("Le fournisseur SMS a refusé la requête (HTTP %s).", exc.code)
        raise RuntimeError("Le fournisseur SMS a refusé la requête.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("Le fournisseur SMS est indisponible (%s).", type(exc).__name__)
        raise RuntimeError("Le fournisseur SMS est indisponible.") from exc

    try:
        body = json.loads(raw_response.decode("utf-8"))
        recipients = body["SMSMessageData"]["Recipients"]
        status_code = int(recipients[0]["statusCode"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        logger.warning("Réponse invalide du fournisseur SMS.")
        raise RuntimeError("Réponse invalide du fournisseur SMS.") from None

    if status_code not in {100, 101, 102}:
        logger.warning("Le fournisseur SMS a rejeté le destinataire (code %s).", status_code)
        raise RuntimeError("Le fournisseur SMS a rejeté le destinataire.")
    logger.info("SMS accepté par le fournisseur (code %s).", status_code)
