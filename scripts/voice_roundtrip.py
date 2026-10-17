"""Schickt eine WAV-Datei (oder einen gesprochenen Satz) durch die Sprachpipeline.

    uv run python scripts/voice_roundtrip.py frage.wav antwort.wav
    uv run python scripts/voice_roundtrip.py --say "Wie warm ist es draußen" antwort.wav

Ablauf wie im Betrieb: VAD -> Whisper -> Dialog (Fast-Path oder Agent) -> Piper. Die Antwort wird
als WAV gespeichert, Erkennung, Antworttext und Latenzen je Stufe werden ausgegeben. Konfiguration
über die üblichen CAT_*-Variablen (u. a. CAT_DATA_DIR, CAT_STT_MODEL, CAT_VOICE_*); CAT_VOICE wird
hier automatisch eingeschaltet.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from cat.config import Settings  # noqa: E402
from cat.dialog import handle_user_text  # noqa: E402
from cat.main import create_app  # noqa: E402
from cat.voice.audio import SAMPLE_RATE, read_wav, resample, silence, write_wav  # noqa: E402
from cat.voice.pipeline import VoiceSession  # noqa: E402

CHUNK = 1024  # Bytes je Schritt (ca. 32 ms), so schickt auch ein Satellit


async def run(args: argparse.Namespace) -> int:
    settings = Settings(voice=True)  # type: ignore[call-arg]
    app = create_app(settings)
    state = app.state.cat
    async with app.router.lifespan_context(app):
        engine = state.voice
        for _ in range(600):  # Modelle laden im Hintergrund (beim ersten Mal kann das dauern)
            if engine.ready or engine.error:
                break
            await asyncio.sleep(0.5)
        if not engine.ready:
            print(f"Sprachmodelle nicht bereit: {engine.error}", file=sys.stderr)
            return 1

        if args.say:
            parts = [chunk async for chunk in engine.tts.synthesize(args.say)]
            pcm = resample(b"".join(parts), engine.tts.sample_rate, SAMPLE_RATE)
        else:
            raw, rate = read_wav(await asyncio.to_thread(Path(args.input).read_bytes))
            pcm = resample(raw, rate, SAMPLE_RATE)
        pcm = silence(0.5) + pcm + silence(args.silence + 1.0)

        events: list[dict] = []
        audio: list[bytes] = []
        rate_out = engine.tts.sample_rate

        async def send_json(payload: dict) -> None:
            events.append(payload)

        async def send_audio(chunk: bytes) -> None:
            audio.append(chunk)

        async def handle(text: str, room: str | None, on_delta):  # type: ignore[no-untyped-def]
            return await handle_user_text(
                state, text, room, spoken=True, on_delta=on_delta, manage_voice_state=False
            )

        session = VoiceSession(engine, handle, send_json, send_audio, room=args.room)
        for i in range(0, len(pcm), CHUNK):
            await session.feed(pcm[i : i + CHUNK])
        for _ in range(600):  # auf die Antwort warten
            if any(e["type"] == "voice.latency" for e in events):
                break
            await asyncio.sleep(0.1)
        await session.close()

    for event in events:
        if event["type"] in ("voice.transcript", "voice.reply", "voice.empty", "error"):
            print(json.dumps(event, ensure_ascii=False))
    latency = next((e for e in events if e["type"] == "voice.latency"), None)
    if latency:
        print("Latenz (ms, ab Ende der Äußerung):")
        for key in ("pause_ms", "stt_ms", "first_token_ms", "first_audio_ms", "total_ms"):
            print(f"  {key:15} {latency[key]}")
        print(f"  Kurzbefehl      {latency['via_fastpath']}")
    if audio:
        await asyncio.to_thread(Path(args.output).write_bytes, write_wav(b"".join(audio), rate_out))
        seconds = len(b"".join(audio)) / (2 * rate_out)
        print(f"Antwort gespeichert: {args.output} ({seconds:.1f} s)")
        return 0
    print("Keine Sprachausgabe erzeugt", file=sys.stderr)
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "files", nargs="+", help="[Eingabe.wav] Antwort.wav (ohne --say mit Eingabe)"
    )
    parser.add_argument("--say", help="statt einer Datei: diesen Satz zuerst synthetisieren")
    parser.add_argument("--room", help="Raum des Sprechers (Standardraum für den Fast-Path)")
    parser.add_argument("--silence", type=float, default=1.6, help="angehängte Stille in Sekunden")
    args = parser.parse_args()
    expected = 1 if args.say else 2
    if len(args.files) != expected:
        parser.error("Mit --say nur die Antwort-Datei angeben, sonst Eingabe- und Antwort-Datei")
    args.input = None if args.say else args.files[0]
    args.output = args.files[-1]
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
