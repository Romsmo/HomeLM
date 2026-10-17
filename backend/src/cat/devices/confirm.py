"""Bestätigung für Geräte mit Risikostufe "high", im Backend erzwungen."""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from cat.ws.protocol import ConfirmRequest, ConfirmResolved, ServerEvent

log = logging.getLogger("cat.confirm")


class ConfirmManager:
    """Hält offene Rückfragen. Eine Rückfrage gilt genau einmal, nur mit ihrer eigenen ID."""

    def __init__(
        self,
        emit: Callable[[ServerEvent], Awaitable[None]],
        has_clients: Callable[[], bool],
        timeout_s: float = 60.0,
    ) -> None:
        self._emit = emit
        self._has_clients = has_clients
        self._timeout = timeout_s
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request(self, device: str, command: str, summary: str) -> bool:
        """True nur bei ausdrücklicher Zustimmung. Ohne Oberfläche, Ablehnung, Timeout: False."""
        if not self._has_clients():
            log.info("Keine Oberfläche verbunden: Bestätigung für %s abgelehnt", device)
            return False
        confirm_id = uuid.uuid4().hex
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[confirm_id] = future
        try:
            await self._emit(
                ConfirmRequest(
                    id=confirm_id,
                    device=device,
                    command=command,
                    summary=summary,
                    expires_in=int(self._timeout),
                )
            )
            try:
                return await asyncio.wait_for(future, timeout=self._timeout)
            except TimeoutError:
                return False
        finally:
            self._pending.pop(confirm_id, None)
            await self._emit(ConfirmResolved(id=confirm_id))

    def resolve(self, confirm_id: str, approved: bool) -> bool:
        """Antwort aus der Oberfläche. Unbekannte oder schon beantwortete IDs werden ignoriert."""
        future = self._pending.get(confirm_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True
