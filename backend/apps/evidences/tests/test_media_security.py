"""Quarantaine, quotas et révocation des URL média signées."""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.exceptions import KemtaAPIError
from apps.evidences.antivirus import AntivirusUnavailable
from apps.evidences.models import Evidence, MediaScanStatus
from apps.evidences.quotas import MEBIBYTE, enforce_media_quota
from apps.evidences.serializers import EvidenceSerializer
from apps.evidences.tasks import generate_evidence_derivatives, retry_pending_media_scans
from apps.projects.models import ProjectMember


@pytest.fixture()
def clean_evidence(auth_client, capture_payload, project_context):
    response = auth_client(project_context["agent"]).post(
        "/api/evidences/",
        capture_payload(),
        format="multipart",
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 201, response.data
    return Evidence.objects.get(pk=response.data["id"])


@pytest.mark.django_db
def test_signed_evidence_media_is_revoked_when_project_membership_is_removed(clean_evidence):
    evidence = clean_evidence
    url = EvidenceSerializer(evidence, context={"user": evidence.author}).data["file_url"]
    client = APIClient()

    assert client.get(url).status_code == 200
    ProjectMember.objects.filter(project=evidence.project, user=evidence.author).update(
        is_active=False
    )
    response = client.get(url)

    assert response.status_code == 404
    assert response.data["error"]["code"] == "signed_media_invalid"


@pytest.mark.django_db
def test_infected_evidence_and_all_derivatives_are_deleted_and_never_served(
    clean_evidence, monkeypatch
):
    evidence = clean_evidence
    original_path = evidence.file.path
    thumbnail_path = evidence.thumbnail.path
    list_version_path = evidence.list_version.path
    Evidence.objects.filter(pk=evidence.pk).update(scan_status=MediaScanStatus.PENDING)
    monkeypatch.setattr(
        "apps.evidences.tasks.scan_file", lambda _field: ("INFECTED", "Eicar-Test-Signature")
    )

    assert generate_evidence_derivatives.run(evidence.pk) is False

    evidence.refresh_from_db()
    assert evidence.scan_status == MediaScanStatus.INFECTED
    assert evidence.scan_result == "Eicar-Test-Signature"
    assert not evidence.file
    assert not evidence.thumbnail
    assert not evidence.list_version
    from pathlib import Path

    assert not Path(original_path).exists()
    assert not Path(thumbnail_path).exists()
    assert not Path(list_version_path).exists()

    url = EvidenceSerializer(evidence, context={"user": evidence.author}).data["thumbnail_url"]
    response = APIClient().get(url)
    assert response.status_code == 423
    assert response.data["error"]["code"] == "media_blocked"
    with override_settings(MAX_MEDIA_USER_QUOTA_MB=1, MAX_MEDIA_PROJECT_QUOTA_MB=10):
        # Un fichier supprimé après détection ne consomme plus de quota disque.
        enforce_media_quota(
            project_id=evidence.project_id,
            actor_id=evidence.author_id,
            new_size=1,
        )


@pytest.mark.django_db
def test_unavailable_required_scanner_keeps_media_in_quarantine(clean_evidence, monkeypatch):
    evidence = clean_evidence
    Evidence.objects.filter(pk=evidence.pk).update(scan_status=MediaScanStatus.PENDING)

    def unavailable(_field):
        raise AntivirusUnavailable("ClamAV offline")

    monkeypatch.setattr("apps.evidences.tasks.scan_file", unavailable)
    with pytest.raises(AntivirusUnavailable):
        generate_evidence_derivatives.run(evidence.pk)

    evidence.refresh_from_db()
    assert evidence.scan_status == MediaScanStatus.ERROR
    response = APIClient().get(
        EvidenceSerializer(evidence, context={"user": evidence.author}).data["file_url"]
    )
    assert response.status_code == 423
    assert response.data["error"]["code"] == "media_scan_pending"


@pytest.mark.django_db
def test_periodic_scan_retry_recovers_a_worker_lost_while_scanning(clean_evidence):
    evidence = clean_evidence
    Evidence.objects.filter(pk=evidence.pk).update(
        scan_status=MediaScanStatus.SCANNING,
        updated_at=timezone.now() - timedelta(minutes=3),
    )

    with patch("apps.evidences.tasks.generate_evidence_derivatives.delay") as enqueue:
        retried = retry_pending_media_scans.run()

    assert retried == 1
    enqueue.assert_called_once_with(evidence.pk)


@pytest.mark.django_db
def test_user_media_quota_is_checked_before_an_upload(clean_evidence):
    evidence = clean_evidence
    with override_settings(MAX_MEDIA_USER_QUOTA_MB=1, MAX_MEDIA_PROJECT_QUOTA_MB=10):
        Evidence.objects.filter(pk=evidence.pk).update(size_bytes=MEBIBYTE)
        with pytest.raises(KemtaAPIError) as raised:
            enforce_media_quota(
                project_id=evidence.project_id,
                actor_id=evidence.author_id,
                new_size=1,
            )

    assert raised.value.status_code == 413
    assert raised.value.code == "media_quota_exceeded"
    assert raised.value.details["scope"] == "user"
    assert raised.value.details["used_bytes"] == MEBIBYTE


@pytest.mark.django_db
def test_project_media_quota_counts_all_authors(clean_evidence, make_user):
    evidence = clean_evidence
    other_user = make_user(phone_number="+237691778899")
    Evidence.objects.filter(pk=evidence.pk).update(author=other_user, size_bytes=MEBIBYTE)
    with (
        override_settings(MAX_MEDIA_USER_QUOTA_MB=10, MAX_MEDIA_PROJECT_QUOTA_MB=1),
        pytest.raises(KemtaAPIError) as raised,
    ):
        enforce_media_quota(
            project_id=evidence.project_id,
            actor_id=evidence.author_id,
            new_size=1,
        )

    assert raised.value.details["scope"] == "project"
    assert raised.value.details["used_bytes"] == MEBIBYTE
