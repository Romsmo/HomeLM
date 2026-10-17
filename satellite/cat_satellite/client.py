"""Der Satellit: wartet auf das Wake-Word, streamt Sprache zum Server, spielt die Antwort ab.

Zustände:
  WAKE    wartet auf das Wake-Word (Audio bleibt lokal, nichts geht ans Netz)
  BEEP    Signalton läuft, Audio wird verworfen
  STREAM  Mikrofon-Audio geht an den Server (bis der Server das Sprachende erkannt hat)
  THINK   Server arbeitet, Audio wird verworfen
  PLAY    Antwort wird abgespielt, Audio wird verworfen (kein Echo, keine Selbstauslösung)
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

import websockets

from cat_satellite.audio import AudioInput, AudioOutput
from cat_satellite.config import Config
from cat_satellite.wakeword import WakeWord

log = logging.getLogger("cat_satellite")


class Mode(Enum):
    WAKE = "wake"
    BEEP = "beep"
    STREAM = "stream"
    THINK = "think"
    PLAY = "play"


Connect = Callable[..., Any]  # websockets.connect oder ein Test-Ersatz


class AuthRejected(Exception):
    """Der Server hat das Token abgelehnt (Verbindung mit Code 1008 geschlossen)."""


class Satellite:
    def __init__(
        self,
        config: Config,
        mic: AudioInput,
        speaker: AudioOutput,
        wakeword: WakeWord,
        connect: Connect = websockets.connect,
        clock: Callable[[], float] = time.monotonic,
        on_mode: Callable[[Mode], Awaitable[None] | None] | None = None,
    ) -> None:
        self._cfg = config
        self._mic = mic
        self._speaker = speaker
        self._wake = wakeword
        self._connect = connect
        self._clock = clock
        self._on_mode = on_mode
        self.mode = Mode.WAKE
        self._continue = False
        self._blocked_until = 0.0
        self._last_event = 0.0
        self._speaking = False
        self.stop_requested = False

    # --- Zustände ---

    async def _set(self, mode: Mode) -> None:
        if mode is not self.mode:
            log.debug("Zustand %s -> %s", self.mode.value, mode.value)
            self.mode = mode
            if self._on_mode:
                result = self._on_mode(mode)
                if asyncio.iscoroutine(result):
                    await result

    async def _to_wake(self, cooldown: bool = True) -> None:
        """Zurück in den Wartezustand. Nach einem Gespräch gilt eine kurze Sperrzeit, damit der
        Satellit nicht durch den Nachhall der eigenen Antwort sofort neu auslöst."""
        self._continue = False
        self._wake.reset()
        self._blocked_until = self._clock() + self._cfg.cooldown_s if cooldown else 0.0
        await self._set(Mode.WAKE)

    # --- Verbindung ---

    async def run(self) -> None:
        """Dauerbetrieb: bei Verbindungsabbruch mit wachsender Wartezeit neu verbinden."""
        delay = 2.0
        while not self.stop_requested:
            try:
                await self.session()
                delay = 2.0
            except AuthRejected:
                log.error(
                    "Der Server lehnt die Verbindung ab: Token prüfen (satellites.yaml) "
                    "und ob die Sprachfunktion am Server an ist (CAT_VOICE)."
                )
                delay = 30.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Verbindung unterbrochen (%s), neuer Versuch in %.0f s", exc, delay)
            await self._to_wake(cooldown=False)
            if self.stop_requested:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def session(self) -> None:
        """Eine Verbindung bis zum Abbruch (wirft AuthRejected oder ConnectionError)."""
        headers = {"Authorization": f"Bearer {self._cfg.token}"}
        log.info(
            "Verbinde mit %s als %s (Raum %s)",
            self._cfg.safe_url,
            self._cfg.device_id,
            self._cfg.room,
        )
        try:
            async with self._connect(
                self._cfg.server_url,
                additional_headers=headers,
                ping_interval=20,
                max_size=4 * 1024 * 1024,
                open_timeout=10,
            ) as ws:
                await self._to_wake(cooldown=False)
                await self._serve(ws)
        except websockets.exceptions.InvalidStatus as exc:
            raise AuthRejected from exc  # der Server lehnt schon den Handshake ab (HTTP 403)
        except websockets.exceptions.ConnectionClosed as exc:
            if exc.rcvd is not None and exc.rcvd.code == 1008:
                raise AuthRejected from exc
            raise ConnectionError("Verbindung geschlossen") from exc

    async def _serve(self, ws: Any) -> None:
        ready = asyncio.Event()
        tasks = [
            asyncio.create_task(self._receive(ws, ready)),
            asyncio.create_task(self._microphone(ws, ready)),
            asyncio.create_task(self._watchdog(ready)),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            if not task.cancelled() and (error := task.exception()) is not None:
                raise error
        raise ConnectionError("Verbindung vom Server beendet")

    # --- Mikrofon ---

    async def _microphone(self, ws: Any, ready: asyncio.Event) -> None:
        await ready.wait()
        async for frame in self._mic.frames():
            if self.stop_requested:
                return
            mode = self.mode
            if mode is Mode.WAKE:
                if self._clock() < self._blocked_until:
                    continue
                if self._wake.process(frame):
                    log.info("Wake-Word erkannt")
                    await self._begin()
            elif mode is Mode.STREAM:
                await ws.send(frame)
            # BEEP, THINK, PLAY: Audio verwerfen

    async def _begin(self) -> None:
        await self._set(Mode.BEEP)
        self._last_event = self._clock()
        try:
            await self._speaker.beep()
        except Exception:
            log.exception("Signalton fehlgeschlagen")
        if self.mode is Mode.BEEP:
            self._last_event = self._clock()
            await self._set(Mode.STREAM)

    # --- Server-Ereignisse ---

    async def _receive(self, ws: Any, ready: asyncio.Event) -> None:
        async for message in ws:
            self._last_event = self._clock()
            if isinstance(message, bytes):
                if self._speaking:
                    await self._speaker.write(message)
                continue
            try:
                event = json.loads(message)
            except json.JSONDecodeError:
                continue
            await self._handle(ws, event, ready)

    async def _handle(self, ws: Any, event: dict[str, Any], ready: asyncio.Event) -> None:
        kind = event.get("type")
        if kind == "voice.ready":
            await ws.send(
                json.dumps(
                    {"type": "hello", "device_id": self._cfg.device_id, "room": self._cfg.room}
                )
            )
            ready.set()
            log.info("Bereit (Erkennung auf dem Server: %s)", event.get("stt"))
        elif kind == "voice.state":
            state = event.get("state")
            if state == "thinking":
                await self._set(Mode.THINK)
            elif state == "idle" and not self._speaking:
                if self._continue:
                    self._continue = False
                    await self._set(Mode.STREAM)  # Rückfrage: Mikro bleibt offen
                else:
                    await self._to_wake()
        elif kind == "tts.start":
            await self._set(Mode.PLAY)
            self._speaking = True
            await self._speaker.open(int(event.get("rate", 22050)))
        elif kind == "tts.end":
            self._speaking = False
            await self._speaker.close()
            self._continue = bool(event.get("expects_reply"))
        elif kind in ("voice.timeout", "voice.empty"):
            await self._to_wake()
        elif kind == "voice.transcript":
            log.info("Erkannt: %s", event.get("text"))
        elif kind == "voice.reply":
            log.info("Antwort: %s", event.get("text"))
        elif kind == "voice.latency":
            log.info("Latenz: %s", {k: v for k, v in event.items() if k != "type"})
        elif kind == "error":
            log.warning("Server-Fehler: %s", event.get("message"))
            if not self._speaking:
                await self._to_wake()

    async def _watchdog(self, ready: asyncio.Event) -> None:
        """Antwortet der Server nicht mehr, wartet der Satellit wieder auf das Wake-Word."""
        await ready.wait()
        while True:
            await asyncio.sleep(1.0)
            busy = self.mode in (Mode.STREAM, Mode.THINK, Mode.PLAY)
            if busy and self._clock() - self._last_event > self._cfg.server_timeout_s:
                log.warning("Server antwortet nicht, zurück in den Wartezustand")
                self._speaking = False
                await self._speaker.close()
                await self._to_wake()
