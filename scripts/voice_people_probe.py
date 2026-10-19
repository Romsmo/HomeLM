"""Prüft Aktivierungsphrase, Füllsätze und Personenerkennung über den echten /ws/voice des laufenden Cat.

Im Backend-Container (nutzt dessen Passwort aus der Umgebung, zeigt es nie):

    cd /srv/homelm
    docker compose exec -T backend python - < scripts/voice_people_probe.py

Die Sprache kommt von Piper (zwei verschiedene Stimmen = zwei "Personen"), also ohne Mikrofon. Das
Skript legt dabei die Testpersonen "Probe Eins" und "Probe Zwei" an und löscht sie am Ende wieder.
"""

import asyncio
import json
import os
import sys
import time
import urllib.request as u
from pathlib import Path

import websockets

from cat.config import Settings
from cat.voice.audio import SAMPLE_RATE, resample, silence
from cat.voice.tts import PiperTts

BASE = os.environ.get("CAT_PROBE_URL", "http://127.0.0.1:8000")
VOICE_B = "de_DE-kerstin-low"


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def login() -> str:
    request = u.Request(
        f"{BASE}/api/login",
        json.dumps({"password": os.environ["CAT_PASSWORD"]}).encode(),
        {"Content-Type": "application/json"},
    )
    return u.urlopen(request, timeout=10).headers["Set-Cookie"].split(";")[0]


def api(cookie: str, path: str, method: str = "GET") -> object:
    request = u.Request(BASE + path, method=method, headers={"Cookie": cookie})
    return json.loads(u.urlopen(request, timeout=20).read() or b"{}")


async def speak(tts: PiperTts, text: str) -> bytes:
    parts = [chunk async for chunk in tts.synthesize(text)]
    return resample(b"".join(parts), tts.sample_rate, SAMPLE_RATE)


class Client:
    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws = ws
        self.events: list[dict] = []

    async def say(self, pcm: bytes, label: str, wait_s: float = 120.0) -> list[dict]:
        """Eine Äußerung senden und warten, bis Cat wieder zuhört. Gibt die neuen Ereignisse zurück."""
        start = len(self.events)
        data = silence(0.4) + pcm + silence(2.2)
        for i in range(0, len(data), 1024):
            await self.ws.send(data[i : i + 1024])
        deadline = time.monotonic() + wait_s
        idle_after = False
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), 1.0)
            except TimeoutError:
                if idle_after:
                    break
                continue
            if isinstance(raw, bytes):
                continue
            event = json.loads(raw)
            self.events.append(event)
            kind = event["type"]
            if kind in ("voice.ignored", "voice.empty", "voice.timeout"):
                idle_after = True
            if kind == "voice.state" and event["state"] == "idle" and any(
                e["type"] in ("voice.transcript", "voice.ignored", "voice.empty", "voice.woke")
                for e in self.events[start:]
            ):
                idle_after = True
        new = self.events[start:]
        transcript = next((e["text"] for e in new if e["type"] == "voice.transcript"), None)
        reply = next((e["text"] for e in new if e["type"] == "voice.reply"), None)
        flags = [e["type"].split(".")[1] for e in new if e["type"] in ("voice.ignored", "voice.woke", "voice.window")]
        latency = next((e for e in new if e["type"] == "voice.latency"), None)
        say(f"\n[{label}]\n  verstanden: {transcript}\n  Cat: {reply}\n  Signale: {', '.join(flags) or '-'}")
        if latency:
            say(f"  Zeiten: STT {latency['stt_ms']} ms, erstes Wort {latency['first_token_ms']} ms, gesamt {latency['total_ms']} ms")
        return new


async def connect(cookie: str) -> websockets.ClientConnection:
    ws = await websockets.connect(
        BASE.replace("http", "ws") + "/ws/voice",
        additional_headers={"Cookie": cookie},
        max_size=8_000_000,
    )
    ready = json.loads(await ws.recv())
    assert ready["type"] == "voice.ready", ready
    return ws


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    tts_a = PiperTts(settings.models_dir / "piper" / f"{settings.tts_voice}.onnx")
    await tts_a.load()
    voice_b = settings.models_dir / "piper" / f"{VOICE_B}.onnx"
    if not voice_b.exists():
        from piper.download_voices import download_voice

        voice_b.parent.mkdir(parents=True, exist_ok=True)
        download_voice(VOICE_B, voice_b.parent)
    tts_b = PiperTts(voice_b)
    await tts_b.load()

    cookie = login()
    info = api(cookie, "/api/voice")
    say(f"Sprachinfo: {json.dumps(info, ensure_ascii=False)}")
    people = api(cookie, "/api/people")
    say(f"Personen vorher: {[p['name'] for p in people['people']]}, Stimmerkennung: {people['voice_available']}")

    # 1. Ohne Aktivierungsphrase: verworfen
    c = Client(await connect(cookie))
    await c.say(await speak(tts_a, "Wie spät ist es eigentlich"), "A ohne Phrase (soll ignoriert werden)")
    # 2. Nur die Phrase: kurze Rückmeldung
    await c.say(await speak(tts_a, "Hey Cat"), "A nur die Phrase (soll Ja? sagen)")
    # 3. Mit Phrase und Anfrage (Füllsatz im Log), danach Frage nach dem Namen
    await c.say(await speak(tts_a, "Hey Cat, wie viele Minuten hat eine Stunde?"), "A Anfrage")
    await c.say(await speak(tts_a, "Probe Eins"), "A nennt den Namen")
    await c.say(await speak(tts_a, "Ja, gerne"), "A erlaubt die Stimme")
    await c.ws.close()

    # 4. Neue Sitzung, gleiche Stimme: wiedererkannt und begrüßt
    c = Client(await connect(cookie))
    await c.say(await speak(tts_a, "Hey Cat, wie viele Tage hat eine Woche?"), "A neue Sitzung (soll begrüßt werden)")
    await c.ws.close()

    # 5. Andere Stimme: unbekannt, Frage nach dem Namen
    c = Client(await connect(cookie))
    await c.say(await speak(tts_b, "Hey Cat, wie viele Tage hat eine Woche?"), "B fremde Stimme")
    await c.say(await speak(tts_b, "Probe Zwei"), "B nennt den Namen")
    await c.say(await speak(tts_b, "Nein"), "B lehnt die Stimmspeicherung ab")
    await c.ws.close()

    # Aufräumen
    for person in api(cookie, "/api/people")["people"]:
        if person["name"].startswith("Probe"):
            api(cookie, f"/api/people/{person['id']}", "DELETE")
    say(f"\nPersonen nachher: {[p['name'] for p in api(cookie, '/api/people')['people']]}")


asyncio.run(main())
