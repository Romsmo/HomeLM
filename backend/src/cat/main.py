import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cat import __version__
from cat.config import Settings, get_settings

log = logging.getLogger("cat")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title="Cat", version=__version__)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # Muss zuletzt eingehängt werden, damit API-Routen Vorrang haben.
    static_dir = settings.static_dir
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:
        log.info("Kein Frontend unter %s, nur API aktiv", static_dir)

    return app


app = create_app()
