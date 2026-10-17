"""Wake-Word-Erkennung auf dem Satelliten (openWakeWord, lokal, ohne Netzwerk)."""

import logging
from typing import Any, Protocol

import numpy as np

log = logging.getLogger("cat_satellite")


class WakeWord(Protocol):
    def process(self, frame: bytes) -> bool:
        """True, wenn dieser Audio-Block (80 ms, PCM16 16 kHz) das Wake-Word auslöst."""
        ...

    def reset(self) -> None: ...


class OpenWakeWordDetector:
    """openWakeWord mit ONNX (läuft auf dem Pi ohne TensorFlow Lite).

    `model` ist der Name eines mitgelieferten Modells ("hey_jarvis", "alexa", "hey_mycroft",
    "hey_rhasspy", ...) oder der Pfad zu einem eigenen .onnx-Modell (z. B. "Hey Cat",
    siehe docs/wakeword.md). Die mitgelieferten Modelle sind nur für nichtkommerziellen Gebrauch
    lizenziert (CC BY-NC-SA 4.0), für ein Wohnzimmer zu Hause ist das in Ordnung.
    """

    def __init__(self, model: str, threshold: float = 0.5) -> None:
        import openwakeword
        from openwakeword.model import Model

        self._threshold = threshold
        is_file = model.endswith((".onnx", ".tflite"))
        if not is_file:
            try:
                openwakeword.utils.download_models([model])  # holt das Modell, falls es fehlt
            except TypeError:
                openwakeword.utils.download_models()  # ältere Version ohne Namensliste
        self._model: Any = Model(wakeword_models=[model], inference_framework="onnx")

    def process(self, frame: bytes) -> bool:
        samples = np.frombuffer(frame, dtype="<i2")
        scores = self._model.predict(samples)
        return bool(scores) and max(scores.values()) >= self._threshold

    def reset(self) -> None:
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
