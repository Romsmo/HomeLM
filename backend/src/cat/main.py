import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cat import __version__, auth
from cat.agent.responder import build_responder
from cat.config import Settings, get_settings
from cat.plugins.manager import PluginManager
from cat.plugins.registry import PluginServices, build_plugins
from cat.state import AppState
from cat.ws import endpoint
from cat.ws.protocol import WidgetUpdate

log = logging.getLogger("cat")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    state = AppState(settings)

    async def publish(update: WidgetUpdate) -> None:
        state.widgets[update.id] = update
        await state.emit(update)

    plugins = PluginManager(
        build_plugins(settings, PluginServices(devices=state.devices)), settings, publish
    )
    state.widget_refresher = plugins.refresh
    if settings.responder == "agent":
        state.responder = build_responder(state, extra_tools=plugins.tools())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await plugins.start()
        try:
            yield
        finally:
            await plugins.stop()

    app = FastAPI(title="Cat", version=__version__, lifespan=lifespan)
    app.state.cat = state
    app.state.auth = state.auth

    if not state.auth.configured:
        log.warning("CAT_PASSWORD ist nicht gesetzt: Login ist deaktiviert")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth.router)
    app.include_router(endpoint.router)

    # Muss zuletzt eingehängt werden, damit API-Routen Vorrang haben.
    static_dir = settings.static_dir
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:
        log.info("Kein Frontend unter %s, nur API aktiv", static_dir)

    return app


app = create_app()
