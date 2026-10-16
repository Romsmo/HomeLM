import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any, Protocol

from cat.auth import Auth
from cat.config import Settings
from cat.stage.store import StageStore
from cat.ws.hub import Hub
from cat.ws.protocol import ChatMessage, ServerEvent, WidgetUpdate


class Responder(Protocol):
    """Erzeugt die Assistentenantwort als Strom von Textteilen."""

    def reply(self, history: list[ChatMessage]) -> AsyncIterator[str]: ...


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
        # Wird vom Plugin-Manager gesetzt (Phase 3): Widget neu laden, True bei Erfolg.
        self.widget_refresher: Callable[[str], Awaitable[bool]] | None = None

    async def emit(self, event: ServerEvent) -> None:
        await self.hub.broadcast(event)

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
