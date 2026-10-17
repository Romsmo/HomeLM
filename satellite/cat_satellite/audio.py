"""Audio-Ein- und -Ausgabe. Die Schnittstellen erlauben Tests ohne Hardware."""

import asyncio
import math
import struct
from collections.abc import AsyncIterator
from typing import Any, Protocol

RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms: so viel will openWakeWord je Schritt, der Server nimmt jede Größe
BEEP_RATE = 22050


class AudioInput(Protocol):
    def frames(self) -> AsyncIterator[bytes]:
        """PCM16 mono 16 kHz, je FRAME_SAMPLES Abtastwerte."""
        ...


class AudioOutput(Protocol):
    async def open(self, rate: int) -> None: ...

    async def write(self, pcm: bytes) -> None: ...

    async def close(self) -> None:
        """Ausspielen beenden: wartet, bis alles gespielt ist."""
        ...

    async def beep(self) -> None: ...


def beep_pcm(rate: int = BEEP_RATE, hz: float = 880.0, seconds: float = 0.12) -> bytes:
    """Kurzer Signalton mit weichem Ein- und Ausblenden (kein Knacken)."""
    count = int(rate * seconds)
    samples = []
    for i in range(count):
        envelope = min(1.0, i / (rate * 0.01), (count - i) / (rate * 0.03))
        samples.append(int(12000 * envelope * math.sin(2 * math.pi * hz * i / rate)))
    return struct.pack(f"<{count}h", *samples)


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())


class SoundDeviceInput:
    """Mikrofon über PortAudio (sounddevice). Der Callback läuft in einem eigenen Thread."""

    def __init__(self, device: str | int | None = None) -> None:
        self._device = device

    async def frames(self) -> AsyncIterator[bytes]:
        import sounddevice as sd

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if status:
                return  # Überlauf: lieber eine Lücke als Verzögerung aufbauen
            data = bytes(indata)
            loop.call_soon_threadsafe(_put_latest, queue, data)

        stream = sd.RawInputStream(
            samplerate=RATE,
            blocksize=FRAME_SAMPLES,
            channels=1,
            dtype="int16",
            device=self._device,
            callback=callback,
        )
        with stream:
            while True:
                yield await queue.get()


def _put_latest(queue: asyncio.Queue[bytes], data: bytes) -> None:
    if queue.full():
        queue.get_nowait()  # ältesten Block verwerfen
    queue.put_nowait(data)


class SoundDeviceOutput:
    """Lautsprecher über PortAudio. Schreiben blockiert, daher im Thread."""

    def __init__(self, device: str | int | None = None, beep_enabled: bool = True) -> None:
        self._device = device
        self._beep = beep_enabled
        self._stream: Any = None

    async def open(self, rate: int) -> None:
        import sounddevice as sd

        await self.close()
        self._stream = sd.RawOutputStream(
            samplerate=rate, channels=1, dtype="int16", device=self._device
        )
        self._stream.start()

    async def write(self, pcm: bytes) -> None:
        if self._stream is not None:
            await asyncio.to_thread(self._stream.write, pcm)

    async def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:

            def finish() -> None:
                stream.stop()  # stop() spielt den Puffer noch aus
                stream.close()

            await asyncio.to_thread(finish)

    async def beep(self) -> None:
        if not self._beep:
            return
        await self.open(BEEP_RATE)
        await self.write(beep_pcm())
        await self.close()
