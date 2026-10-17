"""Offline-Fallback: Wenn der Cloud-Anbieter nicht erreichbar ist, antwortet ein lokales Modell."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from cat.llm.base import LLMError, LLMEvent, LLMProvider, Message, ToolSchema

log = logging.getLogger("cat.llm")


class FallbackProvider:
    """Versucht zuerst `primary`; ist es nicht erreichbar, übernimmt `fallback`.

    - Umgeschaltet wird nur bei `LLMError.unavailable` und nur, solange noch nichts ausgegeben
      wurde (mitten in einer Antwort wird nie gewechselt).
    - Nach einem Ausfall geht es `cooldown_s` Sekunden direkt zum Fallback, damit nicht jede
      Nachricht erst in den Timeout läuft. Danach wird die Cloud wieder versucht.
    - Falsche Schlüssel oder Modellnamen (kein `unavailable`) erreichen den Nutzer unverändert.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        primary_name: str,
        fallback_name: str,
        cooldown_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        on_change: Callable[[str, bool], Awaitable[None]] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._names = (primary_name, fallback_name)
        self._cooldown = cooldown_s
        self._clock = clock
        self._on_change = on_change
        self._down_until = 0.0
        self.active = primary_name
        self.offline = False

    async def _set_active(self, offline: bool) -> None:
        name = self._names[1] if offline else self._names[0]
        if (name, offline) == (self.active, self.offline):
            return
        self.active, self.offline = name, offline
        log.info("LLM-Anbieter: %s%s", name, " (Offline-Fallback)" if offline else "")
        if self._on_change:
            await self._on_change(name, offline)

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSchema]
    ) -> AsyncIterator[LLMEvent]:
        if self._clock() >= self._down_until:
            started = False
            try:
                async for event in self._primary.stream(system, messages, tools):
                    if not started:
                        started = True
                        self._down_until = 0.0
                        await self._set_active(False)
                    yield event
                if not started:
                    await self._set_active(False)
                return
            except LLMError as exc:
                if not exc.unavailable or started:
                    raise
                self._down_until = self._clock() + self._cooldown
                log.warning("Cloud-Modell nicht erreichbar, Offline-Fallback übernimmt")
        await self._set_active(True)
        async for event in self._fallback.stream(system, messages, tools):
            yield event
