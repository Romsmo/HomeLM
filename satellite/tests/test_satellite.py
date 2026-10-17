import asyncio
import json
from typing import Any

import pytest
import websockets
from websockets.datastructures import Headers
from websockets.frames import Close
from websockets.http11 import Response

from cat_satellite.audio import beep_pcm
from cat_satellite.client import AuthRejected, Mode, Satellite
from cat_satellite.config import Config, ConfigError, parse_config

TOKEN = "t" * 32
BASE = {
    "server_url": "ws://192.168.0.10:8090/ws/voice",
    "token": TOKEN,
    "device_id": "kueche-pi",
    "room": "Küche",
}


# --- Konfiguration ---


def test_valid_config_defaults() -> None:
    cfg = parse_config(BASE, env={})
    assert cfg.wakeword_model == "hey_jarvis" and cfg.wakeword_threshold == 0.5 and cfg.beep


def test_token_from_environment_wins() -> None:
    cfg = parse_config({**BASE, "token": "x" * 30}, env={"CAT_SATELLITE_TOKEN": "e" * 40})
    assert cfg.token == "e" * 40
    assert parse_config(
        {k: v for k, v in BASE.items() if k != "token"}, env={"CAT_SATELLITE_TOKEN": "e" * 40}
    )


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"server_url": "http://x"}, "ws://"),
        ({"server_url": ""}, "ws://"),
        ({"server_url": "ws://example.com/ws/voice"}, "wss://"),
        ({"token": "kurz"}, "(?i)token"),
        ({"token": ""}, "token"),
        ({"device_id": "Ungültig Name"}, "device_id"),
        ({"room": "  "}, "room"),
        ({"wakeword_threshold": 2}, "wakeword_threshold"),
        ({"input_device": True}, "input_device"),
    ],
)
def test_invalid_config_is_rejected_with_clear_message(
    change: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ConfigError, match=fragment):
        parse_config({**BASE, **change}, env={})


def test_lan_ws_and_public_wss_are_allowed() -> None:
    for url in ("ws://localhost:8090/ws/voice", "ws://10.1.2.3/ws/voice", "ws://172.20.0.5/x"):
        assert parse_config({**BASE, "server_url": url}, env={}).server_url == url
    assert parse_config({**BASE, "server_url": "wss://cat.example.org/ws/voice"}, env={})


def test_safe_url_hides_credentials() -> None:
    cfg = parse_config({**BASE, "server_url": "wss://user:geheim@cat.example.org/ws"}, env={})
    assert "geheim" not in cfg.safe_url


def test_beep_is_short_and_smooth() -> None:
    pcm = beep_pcm()
    assert 4000 < len(pcm) < 8000
    assert pcm[:2] == b"\x00\x00"  # beginnt leise (kein Knacken)


# --- Test-Doubles ---


class FakeMic:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    def push(self, *frames: bytes) -> None:
        for frame in frames:
            self.queue.put_nowait(frame)

    async def frames(self):  # type: ignore[no-untyped-def]
        while True:
            yield await self.queue.get()


class FakeSpeaker:
    def __init__(self) -> None:
        self.log: list[Any] = []

    async def open(self, rate: int) -> None:
        self.log.append(("open", rate))

    async def write(self, pcm: bytes) -> None:
        self.log.append(("write", pcm))

    async def close(self) -> None:
        self.log.append(("close",))

    async def beep(self) -> None:
        self.log.append(("beep",))

    def audio(self) -> list[bytes]:
        return [e[1] for e in self.log if e[0] == "write"]


class FakeWake:
    """Löst aus, wenn der Block genau WAKE ist."""

    def __init__(self) -> None:
        self.resets = 0
        self.seen: list[bytes] = []

    def process(self, frame: bytes) -> bool:
        self.seen.append(frame)
        return frame == b"WAKE"

    def reset(self) -> None:
        self.resets += 1


class FakeWs:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[Any] = asyncio.Queue()
        self.sent: list[Any] = []

    def server_says(self, *items: Any) -> None:
        for item in items:
            self.inbox.put_nowait(json.dumps(item) if isinstance(item, dict) else item)

    def close_from_server(self, error: Exception | None = None) -> None:
        self.inbox.put_nowait(error if error else None)

    async def send(self, data: Any) -> None:
        self.sent.append(data)

    def __aiter__(self) -> "FakeWs":
        return self

    async def __anext__(self) -> Any:
        item = await self.inbox.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        return item

    def frames_sent(self) -> list[bytes]:
        return [m for m in self.sent if isinstance(m, bytes)]

    def messages_sent(self) -> list[dict[str, Any]]:
        return [json.loads(m) for m in self.sent if isinstance(m, str)]


class FakeConnect:
    def __init__(self, ws: FakeWs | None = None, error: Exception | None = None) -> None:
        self.ws = ws or FakeWs()
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> "FakeConnect":
        self.calls.append((url, kwargs))
        return self

    async def __aenter__(self) -> FakeWs:
        if self.error:
            raise self.error
        return self.ws

    async def __aexit__(self, *exc: Any) -> None:
        return None


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def settle(times: int = 6) -> None:
    for _ in range(times):
        await asyncio.sleep(0.01)


def cfg(**kw: Any) -> Config:
    return parse_config({**BASE, **kw}, env={})


class Rig:
    def __init__(self, **cfg_kw: Any) -> None:
        self.mic, self.speaker, self.wake = FakeMic(), FakeSpeaker(), FakeWake()
        self.connect = FakeConnect()
        self.ws = self.connect.ws
        self.clock = Clock()
        self.modes: list[Mode] = []
        self.sat = Satellite(
            cfg(**cfg_kw),
            self.mic,
            self.speaker,
            self.wake,
            connect=self.connect,
            clock=self.clock,
            on_mode=lambda m: self.modes.append(m),
        )
        self.task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.sat.session())
        await settle()
        self.ws.server_says({"type": "voice.ready", "stt": "small"})
        await settle()

    async def stop(self) -> None:
        assert self.task is not None
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


@pytest.fixture
async def rig():
    r = Rig()
    await r.start()
    yield r
    await r.stop()


# --- Ablauf ---


async def test_sends_token_and_hello_after_ready(rig: Rig) -> None:
    url, kwargs = rig.connect.calls[0]
    assert url == "ws://192.168.0.10:8090/ws/voice"
    assert kwargs["additional_headers"] == {"Authorization": f"Bearer {TOKEN}"}
    hello = rig.ws.messages_sent()[0]
    assert hello == {"type": "hello", "device_id": "kueche-pi", "room": "Küche"}


async def test_nothing_leaves_the_device_before_the_wake_word(rig: Rig) -> None:
    rig.mic.push(b"a", b"b", b"c")
    await settle()
    assert rig.ws.frames_sent() == [] and rig.wake.seen == [b"a", b"b", b"c"]
    assert rig.sat.mode is Mode.WAKE


async def test_full_conversation_wake_to_spoken_answer_and_back(rig: Rig) -> None:
    rig.mic.push(b"x", b"WAKE")
    await settle()
    assert ("beep",) in rig.speaker.log and rig.sat.mode is Mode.STREAM
    rig.mic.push(b"s1", b"s2")
    await settle()
    assert rig.ws.frames_sent() == [b"s1", b"s2"]  # erst nach dem Wake-Word wird gestreamt

    rig.ws.server_says(
        {"type": "voice.state", "state": "listening"},
        {"type": "voice.state", "state": "thinking"},
    )
    await settle()
    assert rig.sat.mode is Mode.THINK
    rig.mic.push(b"verworfen")
    await settle()
    assert b"verworfen" not in rig.ws.frames_sent()  # während der Antwort wird nichts gesendet

    rig.ws.server_says(
        {"type": "voice.transcript", "text": "Licht an"},
        {"type": "voice.state", "state": "speaking"},
        {"type": "tts.start", "rate": 22050, "channels": 1, "format": "s16le"},
        b"\x01\x00" * 10,
        b"\x02\x00" * 10,
        {"type": "voice.reply", "text": "Okay."},
        {"type": "tts.end", "expects_reply": False},
        {"type": "voice.latency", "pause_ms": 1500, "stt_ms": 400, "first_token_ms": 410,
         "first_audio_ms": 520, "total_ms": 600, "via_fastpath": True},
        {"type": "voice.state", "state": "idle"},
    )  # fmt: skip
    await settle(10)
    assert ("open", 22050) in rig.speaker.log and ("close",) in rig.speaker.log
    assert rig.speaker.audio() == [b"\x01\x00" * 10, b"\x02\x00" * 10]
    assert rig.sat.mode is Mode.WAKE
    assert rig.modes[:4] == [Mode.BEEP, Mode.STREAM, Mode.THINK, Mode.PLAY]


async def test_audio_during_playback_does_not_retrigger_the_wake_word(rig: Rig) -> None:
    rig.mic.push(b"WAKE")
    await settle()
    rig.ws.server_says(
        {"type": "voice.state", "state": "thinking"},
        {"type": "tts.start", "rate": 22050, "channels": 1, "format": "s16le"},
    )
    await settle()
    seen_before = len(rig.wake.seen)
    rig.mic.push(b"WAKE")  # Cat hört sich selbst: wird nicht ausgewertet
    await settle()
    assert len(rig.wake.seen) == seen_before and rig.sat.mode is Mode.PLAY


async def test_cooldown_after_answer_blocks_immediate_retrigger(rig: Rig) -> None:
    rig.mic.push(b"WAKE")
    await settle()
    rig.ws.server_says({"type": "voice.empty"})
    await settle()
    assert rig.sat.mode is Mode.WAKE and rig.wake.resets >= 1
    rig.mic.push(b"WAKE")  # direkt danach: noch in der Sperrzeit
    await settle()
    assert rig.sat.mode is Mode.WAKE and ("beep",) in rig.speaker.log
    assert rig.speaker.log.count(("beep",)) == 1
    rig.clock.now += 5  # Sperrzeit vorbei
    rig.mic.push(b"WAKE")
    await settle()
    assert rig.sat.mode is Mode.STREAM and rig.speaker.log.count(("beep",)) == 2


async def test_continue_conversation_after_a_question(rig: Rig) -> None:
    rig.mic.push(b"WAKE")
    await settle()
    rig.ws.server_says(
        {"type": "voice.state", "state": "thinking"},
        {"type": "tts.start", "rate": 22050, "channels": 1, "format": "s16le"},
        b"\x01\x00",
        {"type": "tts.end", "expects_reply": True},
        {"type": "voice.state", "state": "idle"},
    )
    await settle(10)
    assert rig.sat.mode is Mode.STREAM  # Mikro bleibt offen, kein neues Wake-Word nötig
    rig.mic.push(b"antwort")
    await settle()
    assert b"antwort" in rig.ws.frames_sent()
    rig.ws.server_says({"type": "voice.timeout"})  # niemand sagt etwas: zurück
    await settle()
    assert rig.sat.mode is Mode.WAKE


@pytest.mark.parametrize(
    "event", [{"type": "voice.timeout"}, {"type": "voice.empty"}, {"type": "error", "message": "x"}]
)
async def test_failures_and_silence_return_to_wake(rig: Rig, event: dict[str, Any]) -> None:
    rig.mic.push(b"WAKE")
    await settle()
    assert rig.sat.mode is Mode.STREAM
    rig.ws.server_says(event)
    await settle()
    assert rig.sat.mode is Mode.WAKE


async def test_server_silence_triggers_watchdog() -> None:
    r = Rig(server_timeout_s=5)
    await r.start()
    try:
        r.mic.push(b"WAKE")
        await settle()
        assert r.sat.mode is Mode.STREAM
        r.clock.now += 30  # der Server meldet sich nie
        await asyncio.sleep(1.3)  # Wachhund prüft jede Sekunde
        assert r.sat.mode is Mode.WAKE
    finally:
        await r.stop()


async def test_server_closing_the_connection_ends_the_session() -> None:
    r = Rig()
    await r.start()
    r.ws.close_from_server()
    with pytest.raises(ConnectionError):
        await asyncio.wait_for(r.task, 2)  # type: ignore[arg-type]


async def test_close_code_1008_means_rejected() -> None:
    r = Rig()
    await r.start()
    r.ws.close_from_server(websockets.exceptions.ConnectionClosedError(Close(1008, "nein"), None))
    with pytest.raises(AuthRejected):
        await asyncio.wait_for(r.task, 2)  # type: ignore[arg-type]


async def test_http_403_at_handshake_means_rejected() -> None:
    r = Rig()
    r.connect.error = websockets.exceptions.InvalidStatus(
        Response(403, "Forbidden", Headers(), b"")
    )
    with pytest.raises(AuthRejected):
        await r.sat.session()


async def test_run_reconnects_with_backoff_and_stops_on_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = Rig()
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) >= 3:
            r.sat.stop_requested = True

    monkeypatch.setattr("cat_satellite.client.asyncio.sleep", fake_sleep)
    r.connect.error = OSError("kein Netz")
    await asyncio.wait_for(r.sat.run(), 5)
    assert delays == [2.0, 4.0, 8.0]  # wächst, damit ein toter Server nicht bedrängt wird
    assert len(r.connect.calls) == 3
