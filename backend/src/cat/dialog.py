import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from cat.claude.text import is_explicit_request, needs_claude
from cat.intents.fillers import category_for
from cat.people.service import NONE
from cat.state import AppState
from cat.voice.pipeline import Reply
from cat.ws.protocol import (
    ChatDelta,
    ChatDone,
    ChatFiller,
    ChatMessage,
    ErrorEvent,
    VoiceState,
)

log = logging.getLogger("cat.dialog")

OnDelta = Callable[[str], Awaitable[None]]
LOCK_WAIT_S = 30.0
LOCK_GRACE_S = 0.5


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


async def _fillers(
    state: AppState,
    text: str,
    assistant_id: str,
    answered: asyncio.Event,
    on_filler: OnDelta | None,
) -> None:
    """Sagt einen passenden Füllsatz, wenn die Antwort nach `filler_delay_s` noch fehlt, und bei
    langem Warten noch bis zu zweimal einen weiteren (andere Art, damit es nicht doppelt klingt)."""
    settings = state.settings
    try:
        await asyncio.wait_for(answered.wait(), settings.filler_delay_s)
        return
    except TimeoutError:
        pass
    claude = bool(settings.claude_url) and (is_explicit_request(text) or needs_claude(text))
    category = category_for(text, device_related=state.devices.mentions_device(text), claude=claude)
    topic = state.devices.topic_words(text)
    for attempt in range(3):
        phrase = state.fillers.pick(category if attempt == 0 else "think", topic)
        if phrase:
            log.info("Füllsatz (%s, Versuch %d): %s", category, attempt + 1, phrase)
            await state.emit(ChatFiller(id=assistant_id, text=phrase))
            if on_filler:
                await on_filler(phrase)
        try:
            await asyncio.wait_for(answered.wait(), settings.filler_repeat_s)
            return
        except TimeoutError:
            continue


async def handle_user_text(
    state: AppState,
    text: str,
    room: str | None = None,
    *,
    spoken: bool = False,
    on_delta: OnDelta | None = None,
    on_filler: OnDelta | None = None,
    channel: str = "chat",
    voice_pcm: bytes | None = None,
    manage_voice_state: bool = True,
    wait: bool = False,
) -> Reply:
    """Nimmt eine Nutzernachricht an, streamt die Antwort und pflegt den Verlauf.

    Gelernte Kurzbefehle erledigen Wiederholtes zuerst (ohne LLM). `room` ist der Raum des
    Satelliten (er gilt für Kurzbefehle und als Kontext für das Modell).
    `spoken=True`: Die Antwort wird vorgelesen (kurz, ohne Markdown). `on_delta` bekommt die
    Textteile der Antwort (für die satzweise Sprachausgabe). Gibt den Antworttext zurück.
    """
    started = time.perf_counter()
    state.touch()
    try:
        # Sprache wartet, bis ein laufendes Gespräch (z. B. ein anderer Satellit) fertig ist.
        # Der Chat hat eine kurze Gnadenfrist: Ein gelernter Kurzbefehl meldet "fertig", bevor er
        # die Sperre löst, und die nächste Nachricht kommt oft sofort.
        await asyncio.wait_for(
            state.run_lock.acquire(), timeout=LOCK_WAIT_S if wait else LOCK_GRACE_S
        )
    except TimeoutError:
        if not wait:
            await state.emit(ErrorEvent(message="Cat antwortet noch, bitte kurz warten."))
            return Reply("")
        await state.emit(ErrorEvent(message="Cat ist gerade beschäftigt, bitte noch einmal."))
        return Reply("")
    try:
        user = ChatMessage(id=uuid.uuid4().hex, role="user", text=text, ts=_now())
        state.chat.append(user)
        state.memory.sessions.append("user", text)
        await state.emit(user)
        if manage_voice_state:
            await state.emit(VoiceState(state="thinking"))

        checked = time.perf_counter()
        identity = await state.people.identify_voice(channel, voice_pcm) if voice_pcm else NONE
        if state.people.enabled:
            reply = await state.people.intercept(channel, text)
            if reply is not None:  # Vorstellung, Ja/Nein auf eine Frage oder "vergiss meine Stimme"
                user.tooled = True
                return await _say_directly(state, reply, on_delta, started, manage_voice_state)
        state.current_speaker = state.people.speaker_for(channel)
        taught = await state.teach.intercept(text)
        if taught is not None:  # Erklärung, Korrektur oder "merk dir": nie an das Modell
            user.tooled = True
            return await _say_directly(state, taught, on_delta, started, manage_voice_state)

        if state.learner.enabled:
            fast = await _try_learned(state, text, room)
            if fast is not None:
                user.tooled = True
                if on_delta:
                    await on_delta(fast)
                if manage_voice_state:
                    await state.emit(VoiceState(state="idle"))
                return Reply(fast, time.perf_counter() - started, fastpath=True)

        responding = time.perf_counter()
        state.turn_tooled = False
        assistant_id = uuid.uuid4().hex
        assistant = ChatMessage(id=assistant_id, role="assistant", text="", ts=_now())
        # Leere Nachricht anlegen, damit das Frontend die Blase sofort zeigt.
        await state.emit(assistant)
        parts: list[str] = []
        first_output: float | None = None
        answered = asyncio.Event()
        greeting = state.people.greeting(channel, identity)
        if greeting:
            parts.append(greeting)
            await state.emit(ChatDelta(id=assistant_id, delta=greeting))
            if on_delta:
                await on_delta(greeting)
        filler_task = (
            asyncio.create_task(_fillers(state, text, assistant_id, answered, on_filler))
            if state.fillers.enabled
            else None
        )
        try:
            responder = state.responder or EchoResponder()
            async for delta in responder.reply(list(state.chat), spoken=spoken, room=room):
                if first_output is None:
                    first_output = time.perf_counter() - started
                    answered.set()
                parts.append(delta)
                await state.emit(ChatDelta(id=assistant_id, delta=delta))
                if on_delta:
                    await on_delta(delta)
            question = state.people.follow_up(channel, identity) if parts else None
            if question:
                extra = f"\n\n{question}" if not on_delta else f" {question}"
                parts.append(extra)
                await state.emit(ChatDelta(id=assistant_id, delta=extra))
                if on_delta:
                    await on_delta(extra)
        except Exception:
            log.exception("Antwort fehlgeschlagen")
            await state.emit(ErrorEvent(message="Die Antwort ist fehlgeschlagen. Details im Log."))
        finally:
            answered.set()
            if filler_task is not None:
                filler_task.cancel()
                await asyncio.gather(filler_task, return_exceptions=True)
            assistant.text = "".join(parts)
            if state.settings.reflect and parts and not state.turn_tooled:
                who = state.current_speaker
                state.reflector.observe(
                    text, who.name if who else None, state.devices.mentions_device(text)
                )
            assistant.tooled = user.tooled = state.turn_tooled
            log.info(
                "Dialog: vorher %.2f s, Lernprüfung %.2f s, Antwort %.1f s (erste Ausgabe %s)",
                checked - started,
                responding - checked,
                time.perf_counter() - responding,
                f"{first_output:.1f} s" if first_output is not None else "-",
            )
            if assistant.text:
                state.chat.append(assistant)
                state.memory.sessions.append("assistant", assistant.text)
            await state.emit(ChatDone(id=assistant_id))
            if manage_voice_state:
                await state.emit(VoiceState(state="idle"))
        return Reply(assistant.text, first_output)
    finally:
        state.run_lock.release()


async def _say_directly(
    state: AppState,
    text: str,
    on_delta: OnDelta | None,
    started: float,
    manage_voice_state: bool,
) -> Reply:
    """Eine feste Antwort ohne Sprachmodell (Vorstellung, Rückfragen, Vergessen)."""
    answer = ChatMessage(id=uuid.uuid4().hex, role="assistant", text=text, ts=_now(), tooled=True)
    state.chat.append(answer)
    state.memory.sessions.append("assistant", text)
    await state.emit(answer)
    await state.emit(ChatDone(id=answer.id))
    if on_delta:
        await on_delta(text)
    if manage_voice_state:
        await state.emit(VoiceState(state="idle"))
    return Reply(text, time.perf_counter() - started, fastpath=True)


async def _try_learned(state: AppState, text: str, room: str | None) -> str | None:
    """Antwort eines gelernten Kurzbefehls (ohne Sprachmodell), sonst None."""
    try:
        result = await state.learner.handle(text, room)
    except Exception:
        log.exception("Gelernter Kurzbefehl fehlgeschlagen, der Agent übernimmt")
        return None
    if result is None:
        return None
    answer = ChatMessage(
        id=uuid.uuid4().hex, role="assistant", text=result.text, ts=_now(), tooled=True
    )
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
