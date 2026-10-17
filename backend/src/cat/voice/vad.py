"""Spracherkennung (VAD) mit Silero und Segmentierung in Äußerungen.

Das Silero-Modell (ONNX, Version 6) liefert faster-whisper mit; es wird hier direkt mit
onnxruntime betrieben, ohne torch. Eingabe je Fenster: 64 Abtastwerte Kontext plus 512 neue
(32 ms bei 16 kHz) und der LSTM-Zustand (h, c).
"""

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from cat.voice.audio import SAMPLE_RATE, pcm16_to_float32

log = logging.getLogger("cat.voice")

WINDOW = 512
CONTEXT = 64


class SileroVad:
    """Sprachwahrscheinlichkeit je 32-ms-Fenster, mit Zustand über Fenster hinweg."""

    def __init__(self, model_path: Path | None = None) -> None:
        import onnxruntime as ort

        if model_path is None:
            import faster_whisper

            model_path = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        window = np.concatenate([self._context, frame.astype(np.float32)])[None, :]
        prob, self._h, self._c = self._session.run(
            None, {"input": window, "h": self._h, "c": self._c}
        )
        self._context = frame[-CONTEXT:].astype(np.float32)
        return float(np.asarray(prob).reshape(-1)[0])


@dataclass(frozen=True)
class VadConfig:
    threshold: float = 0.5  # ab hier gilt ein Fenster als Sprache
    release: float = 0.35  # darunter zählt es als Stille (Hysterese gegen Flackern)
    silence_s: float = 1.5  # Pause bis zum Ende der Äußerung (einstellbar)
    min_speech_s: float = 0.3  # kürzere Geräusche werden verworfen
    max_utterance_s: float = 20.0
    preroll_s: float = 0.4  # Vorlauf vor dem ersten Sprachfenster, damit der Anfang bleibt
    no_speech_timeout_s: float = 8.0  # so lange auf den Sprechbeginn warten


@dataclass(frozen=True)
class SegmentEvent:
    kind: Literal["start", "end", "timeout"]
    pcm: bytes = b""  # nur bei "end": die ganze Äußerung als PCM16
    speech_s: float = 0.0


class Segmenter:
    """Zerlegt einen PCM-Strom in Äußerungen: Beginn, Ende nach Pause, Zeitüberschreitung."""

    def __init__(
        self, prob: Callable[[np.ndarray], float], config: VadConfig | None = None
    ) -> None:
        self._prob = prob
        self.config = config or VadConfig()
        self._window_s = WINDOW / SAMPLE_RATE
        self.reset()

    def reset(self) -> None:
        reset = getattr(self._prob, "reset", None)
        if callable(reset):
            reset()
        self._pending = b""
        self._preroll: deque[bytes] = deque(
            maxlen=max(1, round(self.config.preroll_s / self._window_s))
        )
        self._speech: list[bytes] = []
        self._in_speech = False
        self._speech_windows = 0
        self._silent_windows = 0
        self._elapsed_s = 0.0
        self._timed_out = False

    def feed(self, pcm: bytes) -> list[SegmentEvent]:
        events: list[SegmentEvent] = []
        self._pending += pcm
        step = WINDOW * 2
        while len(self._pending) >= step:
            chunk, self._pending = self._pending[:step], self._pending[step:]
            events.extend(self._window(chunk))
        return events

    def _window(self, chunk: bytes) -> list[SegmentEvent]:
        cfg = self.config
        p = self._prob(pcm16_to_float32(chunk))
        self._elapsed_s += self._window_s
        if not self._in_speech:
            if p >= cfg.threshold:
                self._in_speech = True
                self._speech = [*self._preroll, chunk]
                self._preroll.clear()
                self._speech_windows = 1
                self._silent_windows = 0
                return [SegmentEvent("start")]
            self._preroll.append(chunk)
            if not self._timed_out and self._elapsed_s >= cfg.no_speech_timeout_s:
                self._timed_out = True
                return [SegmentEvent("timeout")]
            return []

        self._speech.append(chunk)
        if p >= cfg.release:
            self._silent_windows = 0
            if p >= cfg.threshold:
                self._speech_windows += 1
        else:
            self._silent_windows += 1
        too_long = len(self._speech) * self._window_s >= cfg.max_utterance_s
        paused = self._silent_windows * self._window_s >= cfg.silence_s
        if not (paused or too_long):
            return []
        speech_s = self._speech_windows * self._window_s
        # Die lange Schlusspause nicht mitschicken (spart Erkennungszeit), nur ein kurzer Nachlauf.
        keep = min(self._silent_windows, round(0.25 / self._window_s))
        pcm_out = b"".join(self._speech[: len(self._speech) - self._silent_windows + keep])
        self._finish()
        if speech_s < cfg.min_speech_s:
            return []  # nur ein Geräusch
        return [SegmentEvent("end", pcm_out, speech_s)]

    def _finish(self) -> None:
        self._in_speech = False
        self._speech = []
        self._speech_windows = 0
        self._silent_windows = 0
        self._elapsed_s = 0.0  # für den nächsten Satz wieder die volle Wartezeit
        self._timed_out = False
        reset = getattr(self._prob, "reset", None)
        if callable(reset):
            reset()
