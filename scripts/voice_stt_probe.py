"""Misst nur die Spracherkennung über den echten /ws/voice: dreimal "Hey Cat", Zeit je Äußerung.

Im Backend-Container (nutzt dessen Passwort aus der Umgebung):

    cd /srv/homelm
    docker compose exec -T backend python - < scripts/voice_stt_probe.py
"""

import asyncio
import json
import os
import sys
import urllib.request as u

import websockets

from cat.config import Settings
from cat.voice.audio import SAMPLE_RATE, resample, silence
from cat.voice.tts import PiperTts

BASE = os.environ.get("CAT_PROBE_URL", "http://127.0.0.1:8000")
PHRASES = ["Hey Cat", "Hey Cat", "Hallo Cat", "Okay Cat", "Hey Cat"]


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    tts = PiperTts(settings.models_dir / "piper" / f"{settings.tts_voice}.onnx")
    await tts.load()
    request = u.Request(
        f"{BASE}/api/login",
        json.dumps({"password": os.environ["CAT_PASSWORD"]}).encode(),
        {"Content-Type": "application/json"},
    )
    cookie = u.urlopen(request, timeout=10).headers["Set-Cookie"].split(";")[0]
    ws = await websockets.connect(
        BASE.replace("http", "ws") + "/ws/voice", additional_headers={"Cookie": cookie}
    )
    await ws.recv()
    stt: list[int] = []
    for text in PHRASES:
        parts = [c async for c in tts.synthesize(text)]
        pcm = silence(0.4) + resample(b"".join(parts), tts.sample_rate, SAMPLE_RATE) + silence(2.0)
        for i in range(0, len(pcm), 1024):
            await ws.send(pcm[i : i + 1024])
        while True:
            raw = await asyncio.wait_for(ws.recv(), 60)
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            if event["type"] == "voice.latency":
                stt.append(event["stt_ms"])
                break
        await asyncio.sleep(1.0)
    sys.stdout.write(f"STT je Äußerung (ms): {stt}, Mittel {sum(stt) // len(stt)} ms\n")
    await ws.close()


asyncio.run(main())
