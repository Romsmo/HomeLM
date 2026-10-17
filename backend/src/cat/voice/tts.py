"""Sprachausgabe mit Piper (deutsche Stimme), satzweise."""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from cat.voice.stt import lower_priority

log = logging.getLogger("cat.voice")

_MARKDOWN = re.compile(r"[*_`#>]+|\[([^\]]*)\]\([^)]*\)")
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_SPACES = re.compile(r"\s+")
_UNITS = (("°C", " Grad"), ("°", " Grad"), ("%", " Prozent"), ("km/h", " Kilometer pro Stunde"))


def speakable(text: str) -> str:
    """Macht Text sprechbar: Markdown, Links und Emojis entfernen."""
    text = _MARKDOWN.sub(lambda m: m.group(1) or "", text)
    text = _EMOJI.sub("", text)
    for written, spoken in _UNITS:  # Einheiten ausschreiben, sonst liest Piper sie holprig
        text = text.replace(written, spoken)
    return _SPACES.sub(" ", text).strip()


class PiperTts:
    def __init__(self, voice_path: Path, nice: int = 10) -> None:
        self._path = voice_path
        self._voice: Any = None
        self._pool = ThreadPoolExecutor(1, "tts", lower_priority, (nice,))
        self.sample_rate = 22050

    @property
    def voice_name(self) -> str:
        return self._path.name.removesuffix(".onnx")

    def _load(self) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(self._path)
        self.sample_rate = int(self._voice.config.sample_rate)
        list(self._voice.synthesize("Hallo."))  # Warmlauf

    async def load(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._pool, self._load)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """PCM16-Stücke (je ein Satz), sobald sie fertig sind."""
        if self._voice is None:
            raise RuntimeError("Die Stimme ist noch nicht geladen")
        text = speakable(text)
        if not text:
            return
        loop = asyncio.get_running_loop()
        chunks = iter(self._voice.synthesize(text))
        sentinel = object()
        while True:
            chunk = await loop.run_in_executor(self._pool, next, chunks, sentinel)
            if chunk is sentinel:
                return
            yield chunk.audio_int16_bytes

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
