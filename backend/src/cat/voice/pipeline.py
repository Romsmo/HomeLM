"""Sprachpipeline: Audio rein -> VAD -> STT -> Dialog -> TTS-Stücke raus, mit Latenzmessung."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from cat.voice.sentences import SentenceChunker
from cat.voice.vad import Segmenter, VadConfig
from cat.voice.wake import WakeDetector, WakeWindow

log = logging.getLogger("cat.voice")


class Stt(Protocol):
    async def transcribe(self, pcm: bytes, prompt: str = "") -> str: ...


class Tts(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> Any:  # AsyncIterator[bytes]
        ...


@dataclass(frozen=True)
class Reply:
    """Ergebnis des Dialogs: Antworttext und Zeit bis zur ersten Ausgabe."""

    text: str
    first_output_s: float | None = None
    fastpath: bool = False


# (Text, Raum, on_delta) -> Antwort. Wird von dialog.handle_user_text bedient.
HandleText = Callable[[str, str | None, Callable[[str], Awaitable[None]]], Awaitable[Reply]]
SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]
StateHook = Callable[[str], Awaitable[None]]


@dataclass
class Latency:
    """Zeiten in Millisekunden, gemessen ab dem erkannten Ende der Äußerung."""

    pause_ms: int = 0  # Wartezeit bis zum Sprachende (VAD, einstellbar)
    stt_ms: int = 0
    first_token_ms: int | None = None  # Dialog: erstes Wort bzw. Fast-Path-Antwort
    first_audio_ms: int | None = None  # bis das erste Audio rausgeht
    total_ms: int = 0
    via_fastpath: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_event(self) -> dict[str, Any]:
        return {"type": "voice.latency", **{k: v for k, v in self.__dict__.items() if k != "extra"}}


class VoiceEngine:
    """Geladene Modelle, einmal pro Prozess. Die Sitzungen teilen sie sich."""

    def __init__(
        self,
        stt: Stt,
        tts: Tts,
        vad_factory: Callable[[], Callable[..., float]],
        vad_config: VadConfig | None = None,
        prompt: Callable[[], str] = lambda: "",
    ) -> None:
        self.stt = stt
        self.tts = tts
        self._vad_factory = vad_factory
        self.vad_config = vad_config or VadConfig()
        self.prompt = prompt
        # Ein Sprach-Auftrag zur Zeit: STT und TTS laufen auf der CPU des Heimservers.
        self.lock = asyncio.Lock()
        self.ready = False
        self.error: str | None = None
        self.speaker: Any = None  # SpeakerEncoder, wenn die Stimmerkennung geladen ist

    def new_segmenter(self) -> Segmenter:
        return Segmenter(self._vad_factory(), self.vad_config)


class VoiceSession:
    """Eine Audio-Verbindung (Browser oder Satellit). Halbduplex: Während Cat denkt oder
    spricht, wird eingehendes Audio verworfen (kein Echo, keine Selbstgespräche)."""

    def __init__(
        self,
        engine: VoiceEngine,
        handle_text: HandleText,
        send_json: SendJson,
        send_audio: SendAudio,
        room: str | None = None,
        on_state: StateHook | None = None,
        wake: WakeDetector | None = None,
    ) -> None:
        self._engine = engine
        self._handle_text = handle_text
        self._send_json = send_json
        self._send_audio = send_audio
        self.room = room
        self._on_state = on_state
        self._segmenter = engine.new_segmenter()
        self._busy = False
        self._tasks: set[asyncio.Task[None]] = set()
        # Aktivierungsphrase (nur Browser): ohne sie und ohne offenes Gesprächsfenster
        # wird eine Äußerung verworfen.
        self._wake = wake
        self._sentences: asyncio.Queue[str | None] | None = None
        self.last_pcm: bytes | None = None  # die Äußerung, für die Stimmerkennung
        self.channel = f"voice:{uuid.uuid4().hex[:8]}"
        self._window = WakeWindow(wake.followup_s) if wake else None

    async def _state(self, name: str) -> None:
        await self._send_json({"type": "voice.state", "state": name})
        if self._on_state:
            await self._on_state(name)

    async def feed(self, pcm: bytes) -> None:
        if self._busy or not self._engine.ready:
            return
        for event in self._segmenter.feed(pcm):
            if event.kind == "start":
                await self._state("listening")
            elif event.kind == "timeout":
                await self._send_json({"type": "voice.timeout"})
                await self._state("idle")
            elif event.kind == "end":
                self._busy = True
                task = asyncio.create_task(self._utterance(event.pcm))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                return  # alles Weitere gehört schon zur Antwortphase

    async def _utterance(self, pcm: bytes) -> None:
        latency = Latency(pause_ms=round(self._engine.vad_config.silence_s * 1000))
        t0 = time.perf_counter()
        ignored = False

        def since() -> int:
            return round((time.perf_counter() - t0) * 1000)

        try:
            async with self._engine.lock:
                await self._state("thinking")
                text = await self._engine.stt.transcribe(pcm, self._engine.prompt())
                latency.stt_ms = since()
                if not text:
                    await self._send_json({"type": "voice.empty"})
                    return
                if self._wake is not None and self._window is not None:
                    heard = self._wake.match(text)
                    if heard.woke:
                        text = heard.rest
                    elif not self._window.is_open:
                        ignored = True  # nicht an Cat gerichtet: verwerfen, nichts speichern
                        await self._send_json({"type": "voice.ignored"})
                        return
                    if not text:
                        await self._send_json({"type": "voice.woke"})
                        await self._say(self._wake.ack(), latency, since)
                        await self._open_window()
                        return
                await self._send_json({"type": "voice.transcript", "text": text})
                self.last_pcm = pcm
                await self._answer(text, latency, since)
                await self._open_window()
        except Exception:
            log.exception("Sprachverarbeitung fehlgeschlagen")
            await self._send_json(
                {"type": "error", "message": "Die Sprachverarbeitung ist fehlgeschlagen."}
            )
        finally:
            latency.total_ms = since()
            if not ignored:
                await self._send_json(latency.as_event())
                log.info(
                    "voice latency: pause=%s stt=%s first_token=%s first_audio=%s total=%s ms "
                    "(fastpath=%s)",
                    latency.pause_ms,
                    latency.stt_ms,
                    latency.first_token_ms,
                    latency.first_audio_ms,
                    latency.total_ms,
                    latency.via_fastpath,
                )
            self._segmenter.reset()
            self._busy = False
            await self._state("idle")

    async def say_filler(self, text: str) -> None:
        """Füllsatz sprechen, während Cat noch nachdenkt (nicht Teil der Antwort)."""
        if self._sentences is not None:
            await self._sentences.put(text)

    async def _open_window(self) -> None:
        """Nach einer Antwort darf der Nutzer ohne Phrase weitersprechen."""
        if self._window is not None:
            self._window.open()
            await self._send_json({"type": "voice.window", "seconds": self._window._seconds})

    async def _say(self, text: str, latency: Latency, since: Callable[[], int]) -> None:
        """Einen kurzen Satz sprechen (Rückmeldung), ohne Dialog."""
        started = False
        async for chunk in self._engine.tts.synthesize(text):
            if not started:
                started = True
                latency.first_audio_ms = since()
                await self._state("speaking")
                await self._send_json(
                    {
                        "type": "tts.start",
                        "rate": self._engine.tts.sample_rate,
                        "channels": 1,
                        "format": "s16le",
                    }
                )
            await self._send_audio(chunk)
        if started:
            await self._send_json({"type": "tts.end", "expects_reply": True})

    async def _answer(self, text: str, latency: Latency, since: Callable[[], int]) -> None:
        sentences: asyncio.Queue[str | None] = asyncio.Queue()
        chunker = SentenceChunker()
        self._sentences = sentences
        spoken: list[str] = []
        started = False

        async def on_delta(delta: str) -> None:
            for sentence in chunker.feed(delta):
                await sentences.put(sentence)

        async def speak() -> None:
            nonlocal started
            while (sentence := await sentences.get()) is not None:
                spoken.append(sentence)
                async for chunk in self._engine.tts.synthesize(sentence):
                    if not started:
                        started = True
                        latency.first_audio_ms = since()
                        await self._state("speaking")
                        await self._send_json(
                            {
                                "type": "tts.start",
                                "rate": self._engine.tts.sample_rate,
                                "channels": 1,
                                "format": "s16le",
                            }
                        )
                    await self._send_audio(chunk)

        speaker = asyncio.create_task(speak())
        try:
            reply = await self._handle_text(text, self.room, on_delta)
            if (rest := chunker.flush()) is not None:
                await sentences.put(rest)
        finally:
            self._sentences = None
            await sentences.put(None)
            await speaker
        if reply.first_output_s is not None:
            # Der Dialog beginnt direkt nach der Erkennung: STT-Zeit plus Zeit bis zum ersten Wort.
            latency.first_token_ms = round(latency.stt_ms + reply.first_output_s * 1000)
        latency.via_fastpath = reply.fastpath
        await self._send_json({"type": "voice.reply", "text": reply.text})
        if started:
            await self._send_json(
                {"type": "tts.end", "expects_reply": reply.text.rstrip().endswith("?")}
            )

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
