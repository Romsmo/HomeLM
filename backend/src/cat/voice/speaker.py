"""Sprechererkennung: ein Stimm-Fingerabdruck (Embedding) je Äußerung, verglichen per Cosinus.

Das Modell ist WeSpeaker CAM++ (ONNX, 29 MB, trainiert auf VoxCeleb: viele Sprachen und Mikrofone).
Es läuft mit onnxruntime auf der CPU (wie die Spracherkennung), ohne torch. Die Merkmale sind
Kaldi-Fbank (80 Bänder, 25 ms Fenster, 10 ms Schritt, Mittelwert abgezogen), berechnet mit
`kaldi-native-fbank`. Gemessen an den Beispielen von sherpa-onnx: gleiche Person 0,69 bis 0,81,
verschiedene Personen 0,10 bis 0,49 (Cosinus).

Wichtig: Der Fingerabdruck ist ein biometrisches Merkmal. Er bleibt lokal (data/people.json), wird
nur nach ausdrücklicher Zustimmung gespeichert und nie zum Freigeben von Dingen benutzt (keine
Türen, Schlösser oder Bestätigungen): Er macht Antworten persönlicher, mehr nicht.
"""

import hashlib
import logging
import os
import urllib.request
from pathlib import Path

import numpy as np

log = logging.getLogger("cat.voice")

MODEL_NAME = "wespeaker_en_voxceleb_CAM++.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
    + MODEL_NAME
)
MODEL_SHA256 = "c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef"
SAMPLE_RATE = 16000
MIN_SECONDS = 1.0  # kürzere Äußerungen ("Ja.") sind zu unsicher
MAX_SECONDS = 12.0  # mehr bringt nichts und kostet Rechenzeit


def model_path(models_dir: Path) -> Path:
    return models_dir / "speaker" / MODEL_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_model(models_dir: Path) -> Path | None:
    """Das Modell bereitstellen (einmal herunterladen, Prüfsumme kontrollieren).
    Gibt None zurück, wenn es nicht geht: dann bleibt die Stimmerkennung aus, sonst nichts."""
    target = model_path(models_dir)
    try:
        if target.exists() and _sha256(target) == MODEL_SHA256:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        log.info("Sprechererkennung: lade das Modell (29 MB) einmalig herunter")
        tmp = target.with_suffix(".part")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as resp, tmp.open("wb") as out:
            while block := resp.read(1 << 20):
                out.write(block)
        if _sha256(tmp) != MODEL_SHA256:
            tmp.unlink(missing_ok=True)
            log.warning("Sprechererkennung: Prüfsumme des Modells stimmt nicht, Modell verworfen")
            return None
        os.replace(tmp, target)
        return target
    except Exception as exc:
        log.warning("Sprechererkennung nicht verfügbar (%s)", type(exc).__name__)
        return None


class SpeakerEncoder:
    """Stimm-Fingerabdruck einer Äußerung (512 Zahlen, Länge 1)."""

    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 2
        self._session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name

    def embed_samples(self, samples: np.ndarray) -> np.ndarray | None:
        """`samples`: Float im Bereich -1..1, 16 kHz, mono."""
        import kaldi_native_fbank as knf

        if len(samples) < MIN_SECONDS * SAMPLE_RATE:
            return None
        samples = samples[: int(MAX_SECONDS * SAMPLE_RATE)]
        opts = knf.FbankOptions()
        opts.frame_opts.dither = 0
        opts.frame_opts.snip_edges = True
        opts.frame_opts.samp_freq = SAMPLE_RATE
        opts.frame_opts.window_type = "hamming"
        opts.mel_opts.num_bins = 80
        fbank = knf.OnlineFbank(opts)
        fbank.accept_waveform(SAMPLE_RATE, (samples * 32768.0).tolist())
        fbank.input_finished()
        count = fbank.num_frames_ready
        if count < 50:
            return None
        frames = np.stack([fbank.get_frame(i) for i in range(count)]).astype(np.float32)
        frames -= frames.mean(axis=0, keepdims=True)
        out = self._session.run(None, {self._input: frames[None]})[0][0]
        norm = float(np.linalg.norm(out))
        return (out / norm).astype(np.float32) if norm > 0 else None

    def embed(self, pcm: bytes) -> list[float] | None:
        """`pcm`: 16 kHz, 16 Bit, mono (wie überall in Cat)."""
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        vector = self.embed_samples(samples)
        return None if vector is None else [round(float(x), 4) for x in vector]


def cosine(a: list[float], b: list[float]) -> float:
    x, y = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(x @ y) / denom if denom else 0.0
