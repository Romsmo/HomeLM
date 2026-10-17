"""Audio-Grundlagen: 16 kHz, 16 Bit, mono, little endian (so sendet der Satellit)."""

import io
import wave

import numpy as np

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """PCM16 little endian -> float32 im Bereich -1..1 (ungerade Restbytes werden verworfen)."""
    usable = len(pcm) - (len(pcm) % BYTES_PER_SAMPLE)
    return np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768.0


def float32_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def duration_s(pcm: bytes, rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / (BYTES_PER_SAMPLE * rate)


def resample(pcm: bytes, source_rate: int, target_rate: int = SAMPLE_RATE) -> bytes:
    """Einfaches lineares Resampling (für Sprache ausreichend)."""
    if source_rate == target_rate or not pcm:
        return pcm
    samples = pcm16_to_float32(pcm)
    count = int(len(samples) * target_rate / source_rate)
    positions = np.linspace(0, len(samples) - 1, num=count)
    return float32_to_pcm16(np.interp(positions, np.arange(len(samples)), samples))


def read_wav(data: bytes) -> tuple[bytes, int]:
    """WAV-Datei -> (PCM16 mono, Abtastrate). Stereo wird zu mono gemittelt."""
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getsampwidth() != BYTES_PER_SAMPLE:
            raise ValueError("Nur 16-Bit-WAV wird unterstützt")
        rate, channels = wav.getframerate(), wav.getnchannels()
        frames = wav.readframes(wav.getnframes())
    if channels > 1:
        samples = np.frombuffer(frames, dtype="<i2").reshape(-1, channels).mean(axis=1)
        frames = samples.astype("<i2").tobytes()
    return frames, rate


def write_wav(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(BYTES_PER_SAMPLE)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def silence(seconds: float, rate: int = SAMPLE_RATE) -> bytes:
    return bytes(int(seconds * rate) * BYTES_PER_SAMPLE)
