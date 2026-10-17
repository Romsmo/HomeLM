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


async def handle_user_text(state: AppState, text: str, room: str | None = None) -> None:
    """Nimmt eine Nutzernachricht an, streamt die Antwort und pflegt den Verlauf.

    Gerätebefehle erledigt zuerst der Fast-Path (ohne LLM). `room` ist der Raum des Satelliten.
    """
    if state.run_lock.locked():
        await state.emit(ErrorEvent(message="Cat antwortet noch, bitte kurz warten."))
        return
    async with state.run_lock:
        user = ChatMessage(id=uuid.uuid4().hex, role="user", text=text, ts=_now())
        state.chat.append(user)
        await state.emit(user)
        await state.emit(VoiceState(state="thinking"))

        if state.settings.fastpath and await _try_fastpath(state, text, room):
            await state.emit(VoiceState(state="idle"))
            return

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


async def _try_fastpath(state: AppState, text: str, room: str | None) -> bool:
    """True, wenn der Fast-Path den Befehl beantwortet hat (dann kein LLM-Aufruf)."""
    try:
        result = await state.fastpath.handle(text, room)
    except Exception:
        log.exception("Fast-Path fehlgeschlagen, der Agent übernimmt")
        return False
    if result is None:
        return False
    answer = ChatMessage(id=uuid.uuid4().hex, role="assistant", text=result.text, ts=_now())
    state.chat.append(answer)
    await state.emit(answer)
    await state.emit(ChatDone(id=answer.id))
    await state.audit.record(
        "fastpath",
        {"text": text, "device": result.device_id, "command": result.command},
        result.text,
        source="fastpath",
    )
    return True
