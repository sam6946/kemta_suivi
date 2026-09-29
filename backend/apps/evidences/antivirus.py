"""Client ClamAV minimal via le protocole TCP INSTREAM (sans dépendance tierce)."""

from __future__ import annotations

import socket
import struct

from django.conf import settings

CHUNK_BYTES = 64 * 1024


class AntivirusUnavailable(RuntimeError):
    """Le scanner requis ne répond pas : le média reste en quarantaine."""


def scan_file(file_field) -> tuple[str, str]:
    """Renvoie `(CLEAN|INFECTED, signature)` ; n'autorise jamais le média en cas d'erreur."""
    host = getattr(settings, "CLAMAV_HOST", "")
    if not host:
        if settings.ANTIVIRUS_REQUIRED:
            raise AntivirusUnavailable("ClamAV n'est pas configuré.")
        return "CLEAN", "scanner_disabled_development"

    try:
        with socket.create_connection(
            (host, settings.CLAMAV_PORT), timeout=settings.CLAMAV_TIMEOUT_SECONDS
        ) as connection:
            connection.settimeout(settings.CLAMAV_TIMEOUT_SECONDS)
            connection.sendall(b"zINSTREAM\0")
            with file_field.open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    connection.sendall(struct.pack(">I", len(chunk)))
                    connection.sendall(chunk)
            connection.sendall(struct.pack(">I", 0))
            response = bytearray()
            while b"\0" not in response and len(response) < 4096:
                data = connection.recv(1024)
                if not data:
                    break
                response.extend(data)
    except (OSError, TimeoutError) as exc:
        raise AntivirusUnavailable("Le service ClamAV est indisponible.") from exc

    result = bytes(response).split(b"\0", 1)[0].decode("utf-8", errors="replace")
    if result.endswith(": OK") or result == "stream: OK":
        return "CLEAN", ""
    if " FOUND" in result:
        signature = result.rsplit(": ", 1)[-1].removesuffix(" FOUND")
        return "INFECTED", signature[:100]
    raise AntivirusUnavailable("Réponse ClamAV invalide.")
