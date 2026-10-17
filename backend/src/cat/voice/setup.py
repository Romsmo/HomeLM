"""Sprachmodule zusammenbauen und laden (Modelle liegen in data/models)."""

import asyncio
import logging
import time
from pathlib import Path

from cat.config import Settings
from cat.devices.service import DeviceService
from cat.voice.pipeline import VoiceEngine
from cat.voice.stt import WhisperStt
from cat.voice.tts import PiperTts
from cat.voice.vad import SileroVad, VadConfig

log = logging.getLogger("cat.voice")

PROMPT_LIMIT = 220


def recognition_prompt(devices: DeviceService) -> str:
    """Hinweistext für Whisper: Raum- und Gerätenamen verbessern die Erkennung ("Küche" statt
    "Kiche"). Whisper nutzt nur die letzten ~220 Zeichen, daher kurz halten."""
    rooms = sorted({s.room for s in devices.listed_specs})[:12]
    names = [s.name for s in devices.listed_specs][:12]
    if not rooms:
        return ""
    text = "Smart Home: " + ", ".join([*rooms, *names, "Licht", "Rollladen", "Heizung"]) + "."
    return text[-PROMPT_LIMIT:]


def voice_file(settings: Settings) -> Path:
    return settings.models_dir / "piper" / f"{settings.tts_voice}.onnx"


def build_engine(settings: Settings, devices: DeviceService) -> VoiceEngine:
    return VoiceEngine(
        stt=WhisperStt(
            settings.stt_model,
            settings.models_dir / "whisper",
            settings.stt_compute,
            settings.stt_threads,
            nice=settings.voice_nice,
        ),
        tts=PiperTts(voice_file(settings), nice=settings.voice_nice),
        vad_factory=SileroVad,
        vad_config=VadConfig(silence_s=settings.vad_silence_s),
        prompt=lambda: recognition_prompt(devices),
    )


def _download_voice(settings: Settings) -> None:
    from piper.download_voices import download_voice

    target = voice_file(settings).parent
    target.mkdir(parents=True, exist_ok=True)
    download_voice(settings.tts_voice, target)


async def load_engine(engine: VoiceEngine, settings: Settings) -> None:
    """Lädt STT und TTS (einmal beim Start, danach bleiben sie warm im Speicher)."""
    started = time.perf_counter()
    try:
        if not voice_file(settings).exists():
            log.info("Stimme %s fehlt, lade sie herunter", settings.tts_voice)
            await asyncio.to_thread(_download_voice, settings)
        await asyncio.gather(engine.stt.load(), engine.tts.load())  # type: ignore[attr-defined]
    except Exception as exc:
        engine.error = f"Sprachmodelle konnten nicht geladen werden: {type(exc).__name__}"
        log.exception("Sprachmodelle konnten nicht geladen werden")
        return
    engine.ready = True
    log.info(
        "Sprachmodelle bereit (STT %s, Stimme %s) in %.1f s",
        settings.stt_model,
        settings.tts_voice,
        time.perf_counter() - started,
    )
