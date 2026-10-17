"""Spracherkennung mit faster-whisper (CTranslate2, int8, CPU)."""

import asyncio
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from cat.voice.audio import SAMPLE_RATE, pcm16_to_float32

log = logging.getLogger("cat.voice")

# Whisper erfindet bei Stille gern Standardsätze. Solche Treffer verwerfen wir.
_HALLUCINATIONS = re.compile(
    r"^(untertitel|vielen dank fürs zuschauen|danke fürs zuschauen|tschüss|bis zum nächsten mal"
    r"|copyright|amara\.org)",
    re.IGNORECASE,
)


def lower_priority(nice: int) -> None:
    """Der Rechen-Thread läuft mit niedriger Priorität, damit Nextcloud und Co. Vorrang haben."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), nice)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass  # nicht unter Windows oder ohne Recht: dann eben normale Priorität


class WhisperStt:
    def __init__(
        self,
        model: str = "base",
        download_root: Path | None = None,
        compute_type: str = "int8",
        threads: int = 4,
        language: str = "de",
        nice: int = 10,
    ) -> None:
        self._model_name = model
        self._root = download_root
        self._compute = compute_type
        self._threads = threads
        self._language = language
        self._model: Any = None
        # Ein eigener Thread: Modell ist nicht thread-sicher, und so bleibt `nice` gesetzt.
        self._pool = ThreadPoolExecutor(1, "stt", lower_priority, (nice,))

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self._model_name,
            device="cpu",
            compute_type=self._compute,
            cpu_threads=self._threads,
            download_root=str(self._root) if self._root else None,
        )
        # Warmlauf: Der erste Aufruf ist sonst spürbar langsamer.
        self._transcribe(bytes(SAMPLE_RATE * 2), "")

    async def load(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._pool, self._load)

    def _transcribe(self, pcm: bytes, prompt: str) -> str:
        segments, _ = self._model.transcribe(
            pcm16_to_float32(pcm),
            language=self._language,
            beam_size=1,
            vad_filter=False,  # die Segmentierung hat schon Silero erledigt
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            temperature=0.0,
            no_speech_threshold=0.6,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return "" if _HALLUCINATIONS.match(text) else text

    async def transcribe(self, pcm: bytes, prompt: str = "") -> str:
        if self._model is None:
            raise RuntimeError("Das Erkennungsmodell ist noch nicht geladen")
        return await asyncio.get_running_loop().run_in_executor(
            self._pool, self._transcribe, pcm, prompt
        )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
