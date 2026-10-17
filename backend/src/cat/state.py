import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any, Protocol

from cat.audit import AuditLog
from cat.auth import Auth
from cat.config import Settings
from cat.devices.allowlist import load_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.service import DeviceService
from cat.intents.fastpath import FastPath
from cat.intents.vocabulary import load_vocabulary
from cat.memory.service import MemoryService
from cat.plugins.pending import PendingPlugins
from cat.sandbox.client import SandboxClient
from cat.satellites import SatelliteRegistry
from cat.stage.store import StageStore
from cat.voice.pipeline import VoiceEngine
from cat.ws.hub import Hub
from cat.ws.protocol import ChatMessage, ProviderState, ServerEvent, WidgetUpdate


class Responder(Protocol):
    """Erzeugt die Assistentenantwort als Strom von Textteilen."""

    def reply(self, history: list[ChatMessage], spoken: bool = False) -> AsyncIterator[str]: ...


class AppState:
    """Prozessweiter Zustand (ein Nutzer, ein Haushalt)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.auth = Auth(settings)
        self.hub = Hub()
        self.chat: list[ChatMessage] = []
        self.stage = StageStore()
        self.widgets: dict[str, WidgetUpdate] = {}
        self.run_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task[None]] = set()
        self.responder: Responder | None = None
        self.audit = AuditLog(settings.audit_file)
        self.confirm = ConfirmManager(self.emit, lambda: bool(self.hub.connections))
        self.devices = DeviceService(
            load_allowlist(settings.devices_file),
            settings.device_control,
            self.emit,
            self.audit,
            self.confirm,
        )
        self.provider_state = ProviderState(name=settings.llm_model, offline=False)
        self.memory = MemoryService(
            settings.memory_dir, settings.sessions_dir, settings.session_log
        )
        self.voice: VoiceEngine | None = None
        self.satellites = SatelliteRegistry.load(settings.satellites_file)
        self.sandbox = SandboxClient(settings.sandbox_dir)
        self.pending_plugins = PendingPlugins(settings.plugins_dir)
        self.fastpath = FastPath(self.devices, load_vocabulary(settings.synonyms_file))
        # Wird vom Plugin-Manager gesetzt (Phase 3): Widget neu laden, True bei Erfolg.
        self.widget_refresher: Callable[[str], Awaitable[bool]] | None = None

    async def set_provider(self, name: str, offline: bool) -> None:
        """Vom Fallback-Anbieter aufgerufen, wenn das antwortende Modell wechselt."""
        self.provider_state = ProviderState(name=name, offline=offline)
        await self.emit(self.provider_state)

    async def emit(self, event: ServerEvent) -> None:
        await self.hub.broadcast(event)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
