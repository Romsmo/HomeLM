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
from cat.intents.text import has_control_cue, is_question
from cat.memory.reflect import Fact, Reflector
from cat.memory.service import MemoryService
from cat.people.service import PeopleService
from cat.people.store import PeopleStore, Person
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
        self.reflector = Reflector(settings.reflect_idle_s)
        self.current_speaker: Person | None = None  # wer in der laufenden Runde spricht
        self.people = PeopleService(
            PeopleStore(settings.people_file),
            enabled=settings.people,
            accept=settings.speaker_threshold,
            uncertain=settings.speaker_uncertain,
            margin=settings.speaker_margin,
            ttl_s=settings.people_ttl_h * 3600,
            ask_voice=settings.people_voice_ask,
            ask_chat=settings.people_chat_ask,
            is_request=lambda text: (
                self.devices.mentions_device(text) or is_question(text) or has_control_cue(text)
            ),
            on_new=self._person_created,
            on_forget=self._person_forgotten,
        )
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

    async def _person_created(self, person: Person) -> None:
        """Profil-Notiz für eine neue Person (Fakten über sie bekommen ihren Namen als Tag)."""
        day = time.strftime("%Y-%m-%d")
        text = f"{person.name} gehört zum Haushalt (von Cat am {day} kennengelernt)."
        await asyncio.to_thread(
            self.memory.remember, person.name, text, "personen", ["person", person.name]
        )

    async def _person_forgotten(self, person: Person) -> None:
        """Notizen über die Person löschen (Profil und mit ihrem Namen markierte Fakten)."""

        def purge() -> None:
            for note in self.memory.store.all():
                if (
                    note.topic == "personen"
                    and note.title == person.name
                    or person.name in note.tags
                ):
                    self.memory.store.delete(note.path)
            self.memory.index.sync()

        await asyncio.to_thread(purge)

    def export_learned(self) -> None:
        """Gelernte Kurzbefehle als Notiz ins Gedächtnis (für Obsidian und Claude lesbar)."""
        rows = [r for r in self.learner.listing() if r["active"]]
        if not rows:
            return
        body = "\n".join(f"- „{r['phrase']}“: {r['does']}" for r in rows)
        try:
            self.memory.store.delete("gelerntes/kurzbefehle.md")
            self.memory.store.write(
                "Kurzbefehle",
                "Diese Formulierungen führt Cat sofort ohne Sprachmodell aus:\n" + body,
                "gelerntes",
                ["auto", "kurzbefehle"],
            )
            self.memory.index.sync()
        except Exception:
            log.warning("Kurzbefehle konnten nicht ins Gedächtnis geschrieben werden")

    async def save_fact(self, fact: Fact, speaker: str | None = None) -> bool:
        """Einen selbst erkannten Fakt als Notiz ablegen und dem Nutzer sagen, was gemerkt wurde."""
        tags = ["auto", *([speaker] if speaker else [])]
        await asyncio.to_thread(self.memory.remember, fact.title, fact.text, fact.topic, tags)
        note = ChatMessage(
            id=uuid.uuid4().hex,
            role="system",
            text=f'Gemerkt: {fact.text} Sag "vergiss {fact.title}", wenn das nicht stimmt.',
            ts=time.time(),
        )
        self.chat.append(note)
        await self.emit(note)
        return True

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
        await asyncio.to_thread(self.export_learned)

    async def emit(self, event: ServerEvent) -> None:
        await self.hub.broadcast(event)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
