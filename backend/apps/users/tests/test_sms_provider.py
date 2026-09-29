"""Envoi confidentiel des SMS OTP par l'API Africa's Talking."""

import json
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.users.services import sms
from apps.users.services.sms import deliver_sms


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.body


def _response(status_code: int) -> FakeResponse:
    return FakeResponse(
        json.dumps(
            {"SMSMessageData": {"Recipients": [{"statusCode": status_code, "status": "Success"}]}}
        ).encode()
    )


@pytest.mark.parametrize("status_code", [100, 101, 102])
def test_africas_talking_accepts_processed_sent_or_queued_sms(status_code):
    with (
        override_settings(
            SMS_PROVIDER="africastalking",
            SMS_API_KEY="provider-test-key",
            SMS_USERNAME="kemta-test",
            SMS_API_URL="https://sms.example.test/messages",
            SMS_API_TIMEOUT_SECONDS=4,
            SMS_SENDER_ID="KEMTA",
        ),
        patch("apps.users.services.sms.urlopen", return_value=_response(status_code)) as send,
    ):
        deliver_sms("+237690123456", "Votre code est 123456")

    request = send.call_args.args[0]
    headers = {name.lower(): value for name, value in request.header_items()}
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://sms.example.test/messages"
    assert request.method == "POST"
    assert headers["apikey"] == "provider-test-key"
    assert payload == {
        "username": "kemta-test",
        "phoneNumbers": ["+237690123456"],
        "message": "Votre code est 123456",
        "senderId": "KEMTA",
        "enqueue": 1,
    }
    assert send.call_args.kwargs["timeout"] == 4


def test_sms_provider_rejection_retries_without_logging_personal_data(caplog):
    with (
        override_settings(
            SMS_PROVIDER="africastalking",
            SMS_API_KEY="provider-test-key",
            SMS_USERNAME="kemta-test",
            SMS_API_URL="https://sms.example.test/messages",
            SMS_API_TIMEOUT_SECONDS=4,
            SMS_SENDER_ID="KEMTA",
        ),
        patch("apps.users.services.sms.urlopen", return_value=_response(403)),
        pytest.raises(RuntimeError, match="rejeté"),
    ):
        deliver_sms("+237690123456", "Votre code est 123456")

    assert "+237690123456" not in caplog.text
    assert "123456" not in caplog.text
    assert "provider-test-key" not in caplog.text


def test_missing_sms_credentials_fail_loudly_without_network_call():
    with (
        override_settings(
            SMS_PROVIDER="africastalking",
            SMS_API_KEY="",
            SMS_USERNAME="",
            SMS_SENDER_ID="KEMTA",
        ),
        patch("apps.users.services.sms.urlopen") as send,
        pytest.raises(RuntimeError, match="pas configuré"),
    ):
        deliver_sms("+237690123456", "Votre code est 123456")

    send.assert_not_called()


def test_console_adapter_keeps_otp_out_of_logs_and_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sms, "outbox", [])
    with override_settings(SMS_PROVIDER="console", DEBUG=True):
        deliver_sms("+237690123456", "Votre code est 123456")

    assert sms.outbox == [{"phone": "+237690123456", "message": "Votre code est 123456"}]
    assert "123456" not in capsys.readouterr().out


def test_invalid_provider_response_fails_closed():
    with (
        override_settings(
            SMS_PROVIDER="africastalking",
            SMS_API_KEY="provider-test-key",
            SMS_USERNAME="kemta-test",
            SMS_API_URL="https://sms.example.test/messages",
            SMS_API_TIMEOUT_SECONDS=4,
            SMS_SENDER_ID="KEMTA",
        ),
        patch("apps.users.services.sms.urlopen", return_value=FakeResponse(b"not-json")),
        pytest.raises(RuntimeError, match="Réponse invalide"),
    ):
        deliver_sms("+237690123456", "Votre code est 123456")
