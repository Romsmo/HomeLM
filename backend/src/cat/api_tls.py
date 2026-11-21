"""HTTPS im Heimnetz: Auskunft und Download der CA für Geräte (docs/https.md).

Das Mikrofon geht im Browser nur über HTTPS. Cat hat dafür einen eigenen HTTPS-Port mit einem
Zertifikat einer eigenen CA. Diese Schnittstelle sagt dem Handy, wohin es wechseln soll, und gibt
die **öffentliche** CA-Datei zum Installieren heraus (nie den Schlüssel; der liegt außerhalb von
`data/`). Beides nur nach der Anmeldung.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from cat.auth import require_auth
from cat.config import Settings

router = APIRouter(dependencies=[Depends(require_auth)])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.cat.settings
    return settings


def ca_path(settings: Settings) -> Path | None:
    """`ca.crt` liegt neben dem Serverzertifikat; ohne TLS-Einrichtung gibt es keine."""
    if settings.tls_cert is None or settings.tls_key is None:
        return None
    path = settings.tls_cert.parent / "ca.crt"
    return path if path.is_file() else None


@router.get("/api/tls")
async def tls_info(request: Request) -> dict[str, object]:
    settings = _settings(request)
    available = settings.tls_cert is not None and settings.tls_cert.is_file()
    return {
        "https": available,
        "port": settings.tls_host_port,
        "ca": ca_path(settings) is not None,
    }


@router.get("/api/ca.crt")
async def download_ca(request: Request) -> FileResponse:
    path = ca_path(_settings(request))
    if path is None:
        raise HTTPException(404, "Keine eigene CA eingerichtet (docs/https.md)")
    return FileResponse(
        path,
        media_type="application/x-x509-ca-cert",
        filename="cat-heimnetz-ca.crt",
        headers={"X-Content-Type-Options": "nosniff"},
    )
