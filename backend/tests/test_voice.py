import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cat.config import Settings
from cat.main import create_app
from cat.voice.audio import (
    SAMPLE_RATE,
    duration_s,
    float32_to_pcm16,
    pcm16_to_float32,
    read_wav,
    resample,
    silence,
    write_wav,
)
from cat.voice.pipeline import Reply, VoiceEngine, VoiceSession
from cat.voice.sentences import SentenceChunker
from cat.voice.tts import speakable
from cat.voice.vad import WINDOW, Segmenter, VadConfig
from tests.conftest import PASSWORD
from tests.helpers import drain_replay

# --- Audio ---


def test_pcm_roundtrip_and_clipping() -> None:
    samples = np.array([0.0, 0.5, -0.5, 1.5, -1.5], dtype=np.float32)
    pcm = float32_to_pcm16(samples)
    back = pcm16_to_float32(pcm)
    assert len(pcm) == 10 and abs(back[1] - 0.5) < 1e-3
    assert back[3] > 0.99 and back[4] < -0.99  # übersteuert wird begrenzt, nicht umgebrochen
    assert len(pcm16_to_float32(b"\x01\x02\x03")) == 1  # ungerades Restbyte wird verworfen


def test_wav_roundtrip_and_stereo_downmix() -> None:
    pcm = float32_to_pcm16(np.sin(np.linspace(0, 100, 1600)).astype(np.float32))
    data, rate = read_wav(write_wav(pcm, 16000))
    assert data == pcm and rate == 16000
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(np.array([1000, 3000] * 10, dtype="<i2").tobytes())
    mono, rate = read_wav(buf.getvalue())
    assert rate == 8000 and np.frombuffer(mono, dtype="<i2")[0] == 2000


def test_resample_changes_length_and_keeps_duration() -> None:
    pcm = silence(1.0, 22050)
    out = resample(pcm, 22050, 16000)
    assert abs(duration_s(out) - 1.0) < 0.01
    assert resample(pcm, 16000, 16000) == pcm and resample(b"", 8000) == b""


# --- Satzteilung und Sprechtext ---


def test_sentence_chunker_streams_whole_sentences() -> None:
    c = SentenceChunker()
    out: list[str] = []
    for part in ["Das Licht ist ", "jetzt an. Soll ich", " noch etwas tun? Ja", ", gern!"]:
        out += c.feed(part)
    assert out == ["Das Licht ist jetzt an.", "Soll ich noch etwas tun?"]
    assert c.flush() == "Ja, gern!" and c.flush() is None


def test_sentence_chunker_keeps_abbreviations_numbers_and_short_bits_together() -> None:
    c = SentenceChunker()
    out = c.feed("Es sind 21,5 Grad, z. B. im Wohnzimmer. Ja. Draußen ist es kälter als drinnen.")
    out += [c.flush() or ""]
    assert out[0].startswith("Es sind 21,5 Grad, z. B. im Wohnzimmer.")
    assert "Ja." not in out  # zu kurz: wird mit dem nächsten Satz verbunden
    assert any("Draußen" in s for s in out)


def test_speakable_strips_markdown_links_and_emojis() -> None:
    text = "**Fertig** 😀: siehe [Doku](http://x.de) und `code`\n\n- Punkt"
    assert speakable(text) == "Fertig : siehe Doku und code - Punkt"
    assert speakable("   ") == ""
    assert speakable("Es sind 12,2 °C, 71 % und 14 km/h.") == (
        "Es sind 12,2 Grad, 71 Prozent und 14 Kilometer pro Stunde."
    )


# --- Segmentierung (mit künstlicher Sprachwahrscheinlichkeit) ---


class FakeVad:
    """Liefert Wahrscheinlichkeiten aus einer Liste: 1.0 = Sprache, 0.0 = Stille."""

    def __init__(self, probs: list[float]) -> None:
        self.probs = probs
        self.i = 0
        self.resets = 0

    def __call__(self, frame: np.ndarray) -> float:
        assert len(frame) == WINDOW
        p = self.probs[self.i] if self.i < len(self.probs) else 0.0
        self.i += 1
        return p

    def reset(self) -> None:
        self.resets += 1


def stream(windows: int) -> bytes:
    return b"\x01\x00" * WINDOW * windows


def run(seg: Segmenter, windows: int) -> list[Any]:
    events = []
    data = stream(windows)
    for i in range(0, len(data), 700):  # krumme Blockgrößen: es darf nichts verloren gehen
        events += seg.feed(data[i : i + 700])
    return events


WIN_S = WINDOW / SAMPLE_RATE


def test_utterance_ends_after_configured_pause() -> None:
    speech, pause = 20, 60  # ca. 0,64 s Sprache, 1,9 s Pause
    seg = Segmenter(FakeVad([1.0] * speech), VadConfig(silence_s=1.0))
    events = run(seg, speech + pause)
    assert [e.kind for e in events] == ["start", "end"]
    end = events[1]
    assert end.speech_s == pytest.approx(speech * WIN_S, abs=0.05)
    # Die Schlusspause wird bis auf einen kurzen Nachlauf abgeschnitten.
    assert duration_s(end.pcm) < speech * WIN_S + 0.4 + 0.05


def test_short_noise_is_discarded() -> None:
    seg = Segmenter(FakeVad([1.0] * 3), VadConfig(silence_s=0.5, min_speech_s=0.3))
    assert [e.kind for e in run(seg, 60)] == ["start"]  # kein "end": zu kurz


def test_short_pauses_inside_a_sentence_do_not_split() -> None:
    probs = [1.0] * 15 + [0.0] * 20 + [1.0] * 15  # 0,64 s Pause < 1,0 s
    seg = Segmenter(FakeVad(probs), VadConfig(silence_s=1.0))
    events = run(seg, 150)
    assert [e.kind for e in events] == ["start", "end"]
    assert events[1].speech_s == pytest.approx(30 * WIN_S, abs=0.05)


def test_hysteresis_keeps_speech_alive_on_dips() -> None:
    probs = [0.9, 0.9] + [0.4] * 40 + [0.9] * 10  # 0,4 liegt über "release" (0,35)
    seg = Segmenter(FakeVad(probs), VadConfig(silence_s=0.5, release=0.35))
    events = run(seg, 100)
    assert [e.kind for e in events] == ["start", "end"]
    assert events[1].speech_s < 12 * WIN_S + 0.1  # gezählt werden nur echte Sprachfenster


def test_preroll_keeps_the_start_of_the_sentence() -> None:
    seg = Segmenter(FakeVad([0.0] * 30 + [1.0] * 20), VadConfig(silence_s=0.4, preroll_s=0.4))
    events = run(seg, 90)
    end = next(e for e in events if e.kind == "end")
    assert duration_s(end.pcm) >= (20 + 12) * WIN_S - 0.05  # Sprache plus ca. 0,4 s Vorlauf


def test_max_length_cuts_endless_speech_and_timeout_fires_once() -> None:
    seg = Segmenter(FakeVad([1.0] * 1000), VadConfig(max_utterance_s=1.0))
    events = run(seg, 100)
    assert [e.kind for e in events][:2] == ["start", "end"]
    assert duration_s(events[1].pcm) <= 1.1
    quiet = Segmenter(FakeVad([]), VadConfig(no_speech_timeout_s=1.0))
    assert [e.kind for e in run(quiet, 200)] == ["timeout"]  # genau einmal


def test_segmenter_resets_vad_state_between_utterances() -> None:
    vad = FakeVad([1.0] * 20)
    seg = Segmenter(vad, VadConfig(silence_s=0.3))
    before = vad.resets
    run(seg, 60)
    assert vad.resets > before


# --- Pipeline mit Fakes ---


class FakeStt:
    def __init__(self, text: str = "Mach das Licht in der Küche an") -> None:
        self.text = text
        self.prompts: list[str] = []
        self.model_name = "fake"

    async def transcribe(self, pcm: bytes, prompt: str = "") -> str:
        self.prompts.append(prompt)
        await asyncio.sleep(0.05)  # unter Windows feuern Timer < 15 ms sofort
        return self.text


class FakeTts:
    sample_rate = 22050
    voice_name = "fake-voice"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self.spoken.append(text)
        yield b"\x01\x00" * 100
        yield b"\x02\x00" * 100


def make_engine(stt: FakeStt | None = None, probs: list[float] | None = None) -> VoiceEngine:
    engine = VoiceEngine(
        stt or FakeStt(),  # type: ignore[arg-type]
        FakeTts(),
        lambda: FakeVad(probs if probs is not None else [1.0] * 12),
        VadConfig(silence_s=0.3),
        prompt=lambda: "Smart Home: Küche.",
    )
    engine.ready = True
    return engine


class Collector:
    def __init__(self) -> None:
        self.json: list[dict[str, Any]] = []
        self.audio: list[bytes] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.json.append(payload)

    async def send_audio(self, chunk: bytes) -> None:
        self.audio.append(chunk)

    def types(self) -> list[str]:
        return [e["type"] for e in self.json]


async def talk(session: VoiceSession, windows: int = 40) -> None:
    await session.feed(stream(windows))
    for _ in range(200):
        if not session._busy:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Sitzung wurde nicht fertig")


async def test_utterance_flows_through_stt_dialog_tts_with_latency() -> None:
    engine, out = make_engine(), Collector()

    async def handle(text: str, room: str | None, on_delta: Any) -> Reply:
        for part in ["Okay, Küchenlicht ", "ist an. ", "Sonst noch etwas?"]:
            await on_delta(part)
            await asyncio.sleep(0)
        return Reply("Okay, Küchenlicht ist an. Sonst noch etwas?", 0.05)

    session = VoiceSession(engine, handle, out.send_json, out.send_audio, room="Küche")
    await talk(session)
    assert out.types()[:3] == ["voice.state", "voice.state", "voice.transcript"]
    assert [e["state"] for e in out.json if e["type"] == "voice.state"] == [
        "listening",
        "thinking",
        "speaking",
        "idle",
    ]
    assert next(e for e in out.json if e["type"] == "voice.transcript")["text"].startswith("Mach")
    assert engine.tts.spoken == ["Okay, Küchenlicht ist an.", "Sonst noch etwas?"]  # type: ignore[attr-defined]
    assert len(out.audio) == 4  # zwei Sätze zu je zwei Stücken
    start = next(e for e in out.json if e["type"] == "tts.start")
    assert start["rate"] == 22050 and start["format"] == "s16le"
    assert next(e for e in out.json if e["type"] == "tts.end")["expects_reply"] is True
    lat = next(e for e in out.json if e["type"] == "voice.latency")
    assert lat["pause_ms"] == 300 and lat["stt_ms"] >= 30
    assert lat["first_token_ms"] >= lat["stt_ms"] + 50
    assert lat["first_audio_ms"] is not None and lat["total_ms"] >= lat["first_audio_ms"]
    assert engine.stt.prompts == ["Smart Home: Küche."]  # type: ignore[attr-defined]


async def test_audio_during_processing_is_ignored_and_session_recovers() -> None:
    engine, out = make_engine(), Collector()
    calls: list[str] = []

    async def handle(text: str, room: str | None, on_delta: Any) -> Reply:
        calls.append(text)
        await asyncio.sleep(0.1)
        return Reply("Ok.", 0.1)

    session = VoiceSession(engine, handle, out.send_json, out.send_audio)
    await session.feed(stream(40))
    await session.feed(stream(40))  # während Cat denkt: wird verworfen
    for _ in range(200):
        if not session._busy:
            break
        await asyncio.sleep(0.01)
    assert len(calls) == 1
    session._segmenter._prob.i = 0  # type: ignore[attr-defined]  # Fake-VAD spielt wieder von vorn
    await talk(session)  # danach funktioniert die nächste Äußerung wieder
    assert len(calls) == 2


async def test_empty_transcript_gives_no_reply() -> None:
    engine, out = make_engine(FakeStt("")), Collector()

    async def handle(*_: Any) -> Reply:
        raise AssertionError("darf nicht aufgerufen werden")

    await talk(VoiceSession(engine, handle, out.send_json, out.send_audio))
    assert "voice.empty" in out.types() and "tts.start" not in out.types()
    assert out.json[-1]["state"] == "idle" or out.types()[-1] == "voice.state"


async def test_errors_are_reported_and_session_returns_to_idle() -> None:
    engine, out = make_engine(), Collector()

    async def handle(*_: Any) -> Reply:
        raise RuntimeError("kaputt")

    session = VoiceSession(engine, handle, out.send_json, out.send_audio)
    await talk(session)
    assert "error" in out.types() and "voice.latency" in out.types()
    assert not session._busy


async def test_not_ready_engine_ignores_audio() -> None:
    engine, out = make_engine(), Collector()
    engine.ready = False
    session = VoiceSession(engine, lambda *_: None, out.send_json, out.send_audio)  # type: ignore[arg-type]
    await session.feed(stream(40))
    assert out.json == []


async def test_timeout_when_nobody_speaks() -> None:
    engine = make_engine(probs=[])
    engine.vad_config = VadConfig(no_speech_timeout_s=0.5)
    out = Collector()
    session = VoiceSession(engine, lambda *_: None, out.send_json, out.send_audio)  # type: ignore[arg-type]
    await session.feed(stream(40))
    assert "voice.timeout" in out.types()


# --- WebSocket-Endpunkt ---


def voice_app(tmp_path: Path, voice: bool = True) -> Any:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        learn=False,
        summarize_sessions=False,
        voice=False,
    )
    app = create_app(settings)
    if voice:
        app.state.cat.voice = make_engine()
    return app


def login(client: TestClient) -> None:
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200


def test_voice_socket_requires_login_and_enabled_voice(tmp_path: Path) -> None:
    with TestClient(voice_app(tmp_path)) as c:
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws/voice"):
            pass
        assert c.get("/api/voice").status_code == 401
    with TestClient(voice_app(tmp_path, voice=False)) as c:
        login(c)
        info = c.get("/api/voice").json()
        assert info["enabled"] is False and info["ready"] is False
        with pytest.raises(WebSocketDisconnect), c.websocket_connect("/ws/voice"):
            pass


def test_voice_info_reports_models(tmp_path: Path) -> None:
    with TestClient(voice_app(tmp_path)) as c:
        login(c)
        assert c.get("/api/voice").json() == {
            "enabled": True,
            "ready": True,
            "error": None,
            "stt": "fake",
            "voice": "fake-voice",
        }


def test_spoken_question_in_spoken_answer_out_over_websocket(tmp_path: Path) -> None:
    app = voice_app(tmp_path)
    with TestClient(app) as c:
        login(c)
        with c.websocket_connect("/ws") as dash, c.websocket_connect("/ws/voice") as ws:
            drain_replay(dash)
            assert json.loads(ws.receive_text())["type"] == "voice.ready"
            ws.send_text(json.dumps({"type": "hello", "room": "Küche"}))
            ws.send_bytes(stream(40))
            events: list[dict[str, Any]] = []
            audio = 0
            while True:
                msg = ws.receive()
                if msg.get("bytes") is not None:
                    audio += 1
                    continue
                event = json.loads(msg["text"])
                events.append(event)
                if event["type"] == "voice.latency":
                    break
            types = [e["type"] for e in events]
            assert "voice.transcript" in types and "voice.reply" in types and "tts.start" in types
            assert audio >= 2
            reply = next(e for e in events if e["type"] == "voice.reply")["text"]
            assert reply.startswith("Echo: Mach das Licht")
            # Das Dashboard sieht Frage und Antwort im Chat und die Zustände des Orbs.
            seen = []
            for _ in range(40):
                e = json.loads(dash.receive_text())
                seen.append(e)
                if e["type"] == "voice.state" and e["state"] == "idle" and len(seen) > 6:
                    break
            assert any(e["type"] == "chat.message" and e["role"] == "user" for e in seen)
            states = [e["state"] for e in seen if e["type"] == "voice.state"]
            assert "listening" in states and "speaking" in states


def test_oversized_audio_frame_is_rejected(tmp_path: Path) -> None:
    with TestClient(voice_app(tmp_path)) as c:
        login(c)
        with c.websocket_connect("/ws/voice") as ws:
            ws.receive_text()
            ws.send_bytes(b"\x00" * (64 * 1024 + 2))
            assert json.loads(ws.receive_text())["type"] == "error"


def test_loading_models_report_instead_of_hanging(tmp_path: Path) -> None:
    app = voice_app(tmp_path)
    app.state.cat.voice.ready = False
    with TestClient(app) as c:
        login(c)
        with c.websocket_connect("/ws/voice") as ws:
            assert "laden" in json.loads(ws.receive_text())["message"]


# --- Echte Modelle (nur wenn lokal vorhanden: CAT_TEST_MODELS=<Ordner mit piper/ und whisper/>) ---

MODELS = Path(os.environ.get("CAT_TEST_MODELS", "")) if os.environ.get("CAT_TEST_MODELS") else None
needs_models = pytest.mark.skipif(
    MODELS is None or not (MODELS / "piper" / "de_DE-thorsten-medium.onnx").exists(),
    reason="Sprachmodelle nicht vorhanden (CAT_TEST_MODELS)",
)


@needs_models
async def test_real_models_roundtrip_speech_vad_stt() -> None:
    from cat.voice.stt import WhisperStt
    from cat.voice.tts import PiperTts
    from cat.voice.vad import SileroVad

    assert MODELS is not None
    tts = PiperTts(MODELS / "piper" / "de_DE-thorsten-medium.onnx")
    stt = WhisperStt("base", MODELS / "whisper")
    await asyncio.gather(tts.load(), stt.load())
    parts = [c async for c in tts.synthesize("Mach bitte das Licht in der Küche an.")]
    speech = resample(b"".join(parts), tts.sample_rate, SAMPLE_RATE)

    seg = Segmenter(SileroVad(), VadConfig(silence_s=1.0))
    events = []
    data = silence(1.0) + speech + silence(2.0)
    for i in range(0, len(data), 1024):
        events += seg.feed(data[i : i + 1024])
    assert [e.kind for e in events] == ["start", "end"]  # Silero erkennt Sprache und Pause
    text = (await stt.transcribe(events[1].pcm, "Smart Home: Küche, Wohnzimmer, Licht.")).lower()
    assert "licht" in text and "an" in text and "k" in text
    # Reine Stille ergibt keinen Text (keine erfundenen Sätze).
    assert await stt.transcribe(silence(2.0)) == ""
