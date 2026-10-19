import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any, Protocol

from cat.agent.tools import ToolTrace
from cat.audit import AuditLog
from cat.auth import Auth
from cat.config import Settings
from cat.devices.allowlist import load_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.service import DeviceService
from cat.files import Inbox
from cat.intents.fillers import FillerBank
from cat.intents.learned import Learner
from cat.memory.service import MemoryService
from cat.plugins.pending import PendingPlugins
from cat.sandbox.client import SandboxClient
from cat.satellites import SatelliteRegistry
from cat.stage.store import StageStore
from cat.voice.pipeline import VoiceEngine
from cat.ws.hub import Hub
from cat.ws.protocol import ChatMessage, ProviderState, ServerEvent, WidgetUpdate

log = logging.getLogger("cat")


class Responder(Protocol):
    """Erzeugt die Assistentenantwort als Strom von Textteilen."""

    def reply(
        self, history: list[ChatMessage], spoken: bool = False, room: str | None = None
    ) -> AsyncIterator[str]: ...


class AppState:
    """Prozessweiter Zustand (ein Nutzer, ein Haushalt)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.auth = Auth(settings)
        self.hub = Hub()
        self.chat: list[ChatMessage] = []
        self.turn_tooled = False  # hat die laufende Runde Werkzeuge benutzt?
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
        self.provider_state = ProviderState(
            name=settings.local_model or settings.llm_model, offline=False
        )
        self.memory = MemoryService(
            settings.memory_dir, settings.sessions_dir, settings.session_log
        )
        self.voice: VoiceEngine | None = None
        self.satellites = SatelliteRegistry.load(settings.satellites_file)
        self.sandbox = SandboxClient(settings.sandbox_dir)
        self.inbox = Inbox(settings.inbox_dir)
        self.pending_plugins = PendingPlugins(settings.plugins_dir)
        self.fillers = FillerBank(settings.fillers_file, settings.filler)
        self.last_activity = 0.0  # time.monotonic() der letzten Nutzeranfrage
        self.learner = Learner(
            settings.learned_file, self.devices, settings.learn_after, settings.learn
        )
        # Wird vom Plugin-Manager gesetzt (Phase 3): Widget neu laden, True bei Erfolg.
        self.widget_refresher: Callable[[str], Awaitable[bool]] | None = None

    async def set_provider(self, name: str, offline: bool) -> None:
        """Vom Fallback-Anbieter aufgerufen, wenn das antwortende Modell wechselt."""
        self.provider_state = ProviderState(name=name, offline=offline)
        await self.emit(self.provider_state)

    async def learn_from(
        self,
        question: str,
        trace: list[ToolTrace],
        room: str | None = None,
        previous_device: str | None = None,
        context: list[tuple[str, str]] | None = None,
    ) -> None:
        """Nach einer vom Modell gelösten Anfrage: daraus lernen und es dem Nutzer sagen."""
        self.turn_tooled = bool(trace)
        try:
            learned = self.learner.observe(question, trace, room, previous_device, context)
        except Exception:
            log.exception("Lernen fehlgeschlagen")
            return
        if learned is None:
            return
        note = ChatMessage(
            id=uuid.uuid4().hex,
            role="system",
            text=f'Gemerkt: Auf "{learned.key}" antworte ich künftig sofort, ohne Sprachmodell. '
            'Im Widget "Gelernt" lässt sich das wieder löschen.',
            ts=time.time(),
        )
        self.chat.append(note)
        await self.emit(note)

    async def emit(self, event: ServerEvent) -> None:
        await self.hub.broadcast(event)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
