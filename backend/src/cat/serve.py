"""Startet Cat: immer HTTP (Port 8000, für Satelliten und Health-Check) und, wenn Zertifikat und
Schlüssel vorhanden sind, zusätzlich HTTPS (Port 8443).

Browser geben das Mikrofon nur auf `https://` oder `localhost` frei. Beide Listener bedienen
dieselbe App im selben Prozess (ein Zustand, ein Chatverlauf); den Lebenszyklus (Plugins,
Sprachmodelle) führt nur der HTTP-Server aus, der HTTPS-Server teilt ihn (`lifespan="off"`).
"""

import asyncio
import contextlib
import logging
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI

from cat.config import Settings

log = logging.getLogger("cat")


class _FollowerServer(uvicorn.Server):
    """Zweiter Server im selben Prozess: Signale fängt allein der erste ein."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def tls_ready(settings: Settings) -> bool:
    """HTTPS nur, wenn beides konfiguriert ist und da liegt (sonst Warnung statt Absturz)."""
    cert, key = settings.tls_cert, settings.tls_key
    if cert is None and key is None:
        return False
    if cert is None or key is None or not cert.is_file() or not key.is_file():
        log.warning("HTTPS ist konfiguriert, aber Zertifikat oder Schlüssel fehlen: nur HTTP aktiv")
        return False
    return True


def build_configs(settings: Settings, app: FastAPI) -> list[uvicorn.Config]:
    log_level = settings.log_level.lower()
    configs = [uvicorn.Config(app, host=settings.host, port=settings.port, log_level=log_level)]
    if tls_ready(settings):
        configs.append(
            uvicorn.Config(
                app,
                host=settings.host,
                port=settings.tls_port,
                ssl_certfile=str(settings.tls_cert),
                ssl_keyfile=str(settings.tls_key),
                lifespan="off",
                log_level=log_level,
            )
        )
    return configs


async def serve(settings: Settings, app: FastAPI) -> None:
    primary, *others = build_configs(settings, app)
    main = uvicorn.Server(primary)
    followers = [_FollowerServer(config) for config in others]
    tasks = [asyncio.create_task(server.serve()) for server in followers]
    try:
        await main.serve()
    finally:
        for server in followers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)


def run() -> None:
    from cat.config import get_settings
    from cat.main import app

    asyncio.run(serve(get_settings(), app))


if __name__ == "__main__":
    run()
