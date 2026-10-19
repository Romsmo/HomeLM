import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cat import (
    __version__,
    api_files,
    api_fillers,
    api_learned,
    api_memory,
    api_people,
    auth,
)
from cat.agent.responder import build_local_provider, build_responder
from cat.config import Settings, get_settings
from cat.intents.fillers import FillerWorkshop
from cat.llm.base import LLMProvider, TextDelta
from cat.llm.litellm_provider import LiteLLMProvider
from cat.memory.sessions import summarize_old_sessions
from cat.plugins.manager import PluginManager
from cat.plugins.registry import PluginServices, build_plugins
from cat.state import AppState
from cat.voice.setup import build_engine, load_engine
from cat.ws import endpoint
from cat.ws import voice as voice_ws
from cat.ws.protocol import WidgetUpdate

log = logging.getLogger("cat")


def _start_summaries(state: AppState) -> "asyncio.Task[int] | None":
    """Fasst alte Gespräche zusammen, wenn ein LLM konfiguriert ist (sonst nichts, nie Fehler)."""
    settings = state.settings
    if not (settings.summarize_sessions and settings.session_log and settings.responder == "agent"):
        return None
    provider: LLMProvider
    if settings.local_model:
        provider = build_local_provider(state)  # lokal, ohne Internet; Claude sieht das nie
    else:
        provider = LiteLLMProvider(
            settings.llm_model, settings.anthropic_api_key, settings.llm_max_tokens
        )
        if settings.anthropic_api_key is None and settings.llm_model.startswith(
            ("anthropic/", "claude")
        ):
            return None

    async def run() -> int:
        try:
            return await summarize_old_sessions(state.memory.sessions, state.memory.store, provider)
        except Exception:
            log.exception("Zusammenfassung alter Gespräche fehlgeschlagen")
            return 0

    return asyncio.create_task(run())


def _local_generate(state: AppState) -> "Callable[[str], Awaitable[str]]":
    """Kurze Texte vom lokalen Modell (für Hintergrundaufgaben, ohne Werkzeuge)."""
    provider = build_local_provider(state)

    async def generate(prompt: str) -> str:
        """Bricht ab, sobald der Nutzer etwas tut: Ollama beendet die Erzeugung, wenn die
        Verbindung schließt, und die CPU gehört wieder der Spracherkennung und der Antwort."""
        started = state.activity_gen
        parts = []
        stream = provider.stream(
            "Du schreibst kurze, genaue Texte auf Deutsch und hältst dich an das verlangte Format.",
            [{"role": "user", "content": prompt}],
            [],
        )
        try:
            async for event in stream:
                if state.activity_gen != started:
                    raise RuntimeError("unterbrochen: der Nutzer ist aktiv")
                if isinstance(event, TextDelta):
                    parts.append(event.text)
        finally:
            await stream.aclose()
            # Ollama hält nur EIN Gedächtnis des Prompt-Anfangs: Mein Text hat Cats Prompt
            # verdrängt. Im Leerlauf neu vorwärmen, damit die nächste Anfrage nicht 5 s
            # Prompt-Verarbeitung nachholen muss. Ist der Nutzer schon aktiv, entfällt das.
            warm = getattr(state.responder, "warm", None)
            if warm is not None and state.activity_gen == started:
                try:
                    await warm()
                except Exception:
                    log.info("Vorwärmen nach der Hintergrundaufgabe fehlgeschlagen")
        return "".join(parts)

    return generate


def _start_reflection(state: AppState) -> "asyncio.Task[None] | None":
    """Dauerhafte Fakten aus Gesprächen merken, wenn Cat untätig ist (nur mit lokalem Modell)."""
    settings = state.settings
    if not (settings.reflect and settings.local_model and settings.responder == "agent"):
        return None
    return asyncio.create_task(
        state.reflector.run(
            _local_generate(state),
            state.save_fact,
            lambda: state.last_activity,
            state.run_lock.locked,
        )
    )


def _start_fillers(state: AppState) -> "asyncio.Task[None] | None":
    """Füllsätze von selbst erweitern, wenn Cat untätig ist (nur mit lokalem Modell)."""
    settings = state.settings
    if not (settings.filler and settings.filler_generate and settings.local_model):
        return None
    if settings.responder != "agent":
        return None

    def idle() -> bool:
        return not state.run_lock.locked() and time.monotonic() - state.last_activity > 90

    return asyncio.create_task(FillerWorkshop(state.fillers, _local_generate(state), idle).run())


def _start_voice(state: AppState) -> "asyncio.Task[None] | None":
    """Lädt die Sprachmodelle im Hintergrund (Cat ist sofort erreichbar, Sprache folgt)."""
    if not state.settings.voice or state.voice is None:
        return None

    async def start() -> None:
        assert state.voice is not None
        await load_engine(state.voice, state.settings)
        if getattr(state.voice, "speaker", None) is not None:
            state.people.encoder = state.voice.speaker

    return asyncio.create_task(start())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    state = AppState(settings)
    if settings.voice:
        state.voice = build_engine(settings, state.devices)

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
        summary_task = _start_summaries(state)
        voice_task = _start_voice(state)
        filler_task = _start_fillers(state)
        await asyncio.to_thread(state.export_learned)
        reflect_task = _start_reflection(state)
        warm = getattr(state.responder, "warm", None)  # lokales Modell vorladen
        warm_task = asyncio.create_task(warm()) if warm else None
        try:
            yield
        finally:
            if warm_task:
                warm_task.cancel()
            if summary_task:
                summary_task.cancel()
            if voice_task:
                voice_task.cancel()
            if filler_task:
                filler_task.cancel()
            if reflect_task:
                reflect_task.cancel()
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
    app.include_router(api_files.router)
    app.include_router(api_learned.router)
    app.include_router(api_fillers.router)
    app.include_router(api_memory.router)
    app.include_router(api_people.router)
    app.include_router(endpoint.router)
    app.include_router(voice_ws.router)

    # Muss zuletzt eingehängt werden, damit API-Routen Vorrang haben.
    static_dir = settings.static_dir
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:
        log.info("Kein Frontend unter %s, nur API aktiv", static_dir)

    return app


app = create_app()
