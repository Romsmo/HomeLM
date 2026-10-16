import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from cat.state import AppState
from cat.ws.protocol import (
    ChatDelta,
    ChatDone,
    ChatMessage,
    ErrorEvent,
    VoiceState,
)

log = logging.getLogger("cat.dialog")


class EchoResponder:
    """Phase 1: gibt die Nutzernachricht wortweise zurück (kein LLM)."""

    async def reply(self, history: list[ChatMessage]) -> AsyncIterator[str]:
        last = history[-1].text
        words = f"Echo: {last}".split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(0.02)
            yield word if i == 0 else f" {word}"


def _now() -> float:
    return time.time()


async def handle_user_text(state: AppState, text: str) -> None:
    """Nimmt eine Nutzernachricht an, streamt die Antwort und pflegt den Verlauf."""
    if state.run_lock.locked():
        await state.emit(ErrorEvent(message="Cat antwortet noch, bitte kurz warten."))
        return
    async with state.run_lock:
        user = ChatMessage(id=uuid.uuid4().hex, role="user", text=text, ts=_now())
        state.chat.append(user)
        await state.emit(user)
        await state.emit(VoiceState(state="thinking"))

        assistant_id = uuid.uuid4().hex
        assistant = ChatMessage(id=assistant_id, role="assistant", text="", ts=_now())
        # Leere Nachricht anlegen, damit das Frontend die Blase sofort zeigt.
        await state.emit(assistant)
        parts: list[str] = []
        try:
            responder = state.responder or EchoResponder()
            async for delta in responder.reply(list(state.chat)):
                parts.append(delta)
                await state.emit(ChatDelta(id=assistant_id, delta=delta))
        except Exception:
            log.exception("Antwort fehlgeschlagen")
            await state.emit(ErrorEvent(message="Die Antwort ist fehlgeschlagen. Details im Log."))
        finally:
            assistant.text = "".join(parts)
            if assistant.text:
                state.chat.append(assistant)
            await state.emit(ChatDone(id=assistant_id))
            await state.emit(VoiceState(state="idle"))
