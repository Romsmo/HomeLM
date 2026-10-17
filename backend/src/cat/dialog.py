import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from cat.state import AppState
from cat.voice.pipeline import Reply
from cat.ws.protocol import (
    ChatDelta,
    ChatDone,
    ChatMessage,
    ErrorEvent,
    VoiceState,
)

log = logging.getLogger("cat.dialog")

OnDelta = Callable[[str], Awaitable[None]]
LOCK_WAIT_S = 30.0


class EchoResponder:
    """Phase 1: gibt die Nutzernachricht wortweise zurück (kein LLM)."""

    async def reply(
        self, history: list[ChatMessage], spoken: bool = False, room: str | None = None
    ) -> AsyncIterator[str]:
        last = history[-1].text
        words = f"Echo: {last}".split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(0.02)
            yield word if i == 0 else f" {word}"


def _now() -> float:
    return time.time()


async def handle_user_text(
    state: AppState,
    text: str,
    room: str | None = None,
    *,
    spoken: bool = False,
    on_delta: OnDelta | None = None,
    manage_voice_state: bool = True,
    wait: bool = False,
) -> Reply:
    """Nimmt eine Nutzernachricht an, streamt die Antwort und pflegt den Verlauf.

    Gelernte Kurzbefehle erledigen Wiederholtes zuerst (ohne LLM). `room` ist der Raum des
    Satelliten (er gilt für Kurzbefehle und als Kontext für das Modell).
    `spoken=True`: Die Antwort wird vorgelesen (kurz, ohne Markdown). `on_delta` bekommt die
    Textteile der Antwort (für die satzweise Sprachausgabe). Gibt den Antworttext zurück.
    """
    if state.run_lock.locked() and not wait:
        await state.emit(ErrorEvent(message="Cat antwortet noch, bitte kurz warten."))
        return Reply("")
    started = time.perf_counter()
    try:
        # Sprache wartet, bis ein laufendes Gespräch (z. B. ein anderer Satellit) fertig ist.
        await asyncio.wait_for(state.run_lock.acquire(), timeout=LOCK_WAIT_S if wait else None)
    except TimeoutError:
        await state.emit(ErrorEvent(message="Cat ist gerade beschäftigt, bitte noch einmal."))
        return Reply("")
    try:
        user = ChatMessage(id=uuid.uuid4().hex, role="user", text=text, ts=_now())
        state.chat.append(user)
        state.memory.sessions.append("user", text)
        await state.emit(user)
        if manage_voice_state:
            await state.emit(VoiceState(state="thinking"))

        if state.learner.enabled:
            fast = await _try_learned(state, text, room)
            if fast is not None:
                if on_delta:
                    await on_delta(fast)
                if manage_voice_state:
                    await state.emit(VoiceState(state="idle"))
                return Reply(fast, time.perf_counter() - started, fastpath=True)

        assistant_id = uuid.uuid4().hex
        assistant = ChatMessage(id=assistant_id, role="assistant", text="", ts=_now())
        # Leere Nachricht anlegen, damit das Frontend die Blase sofort zeigt.
        await state.emit(assistant)
        parts: list[str] = []
        first_output: float | None = None
        try:
            responder = state.responder or EchoResponder()
            async for delta in responder.reply(list(state.chat), spoken=spoken, room=room):
                if first_output is None:
                    first_output = time.perf_counter() - started
                parts.append(delta)
                await state.emit(ChatDelta(id=assistant_id, delta=delta))
                if on_delta:
                    await on_delta(delta)
        except Exception:
            log.exception("Antwort fehlgeschlagen")
            await state.emit(ErrorEvent(message="Die Antwort ist fehlgeschlagen. Details im Log."))
        finally:
            assistant.text = "".join(parts)
            if assistant.text:
                state.chat.append(assistant)
                state.memory.sessions.append("assistant", assistant.text)
            await state.emit(ChatDone(id=assistant_id))
            if manage_voice_state:
                await state.emit(VoiceState(state="idle"))
        return Reply(assistant.text, first_output)
    finally:
        state.run_lock.release()


async def _try_learned(state: AppState, text: str, room: str | None) -> str | None:
    """Antwort eines gelernten Kurzbefehls (ohne Sprachmodell), sonst None."""
    try:
        result = await state.learner.handle(text, room)
    except Exception:
        log.exception("Gelernter Kurzbefehl fehlgeschlagen, der Agent übernimmt")
        return None
    if result is None:
        return None
    answer = ChatMessage(id=uuid.uuid4().hex, role="assistant", text=result.text, ts=_now())
    state.chat.append(answer)
    state.memory.sessions.append("assistant", answer.text)
    await state.emit(answer)
    await state.emit(ChatDone(id=answer.id))
    await state.audit.record(
        "learned_shortcut",
        {"text": text, "device": result.device_id, "command": result.command},
        result.text,
        source="learned",
    )
    return result.text
