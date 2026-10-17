"""Schickt Fragen an das LAUFENDE Cat (wie die Weboberfläche, über /ws) und zeigt die Antworten.

Im Backend-Container (nutzt dessen Passwort aus der Umgebung, zeigt es nie):

    cd /srv/homelm
    docker compose exec -T backend python - "Ist Romans Rollo offen?" < scripts/chat_probe.py

Anders als scripts/local_eval.py arbeitet das auf dem echten Zustand (echte Geräte, laufende Plugins,
Chatverlauf). Es steuert nur, was Sie fragen; für Tests am besten Fragen, die nur lesen.
"""

import asyncio
import json
import os
import sys
import time
import urllib.request as u

import websockets


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    base = os.environ.get("CAT_PROBE_URL", "http://127.0.0.1:8000")
    request = u.Request(
        f"{base}/api/login",
        json.dumps({"password": os.environ["CAT_PASSWORD"]}).encode(),
        {"Content-Type": "application/json"},
    )
    cookie = u.urlopen(request, timeout=10).headers["Set-Cookie"].split(";")[0]
    async with websockets.connect(
        base.replace("http", "ws") + "/ws", additional_headers={"Cookie": cookie}, max_size=8_000_000
    ) as ws:
        for question in sys.argv[1:]:
            started = time.perf_counter()
            await ws.send(json.dumps({"type": "chat.message", "text": question}))
            answer, assistant_id = "", None
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), 300))
                if event["type"] == "chat.message" and event["role"] == "assistant":
                    assistant_id = event["id"]
                    answer = event["text"]  # Fast-Path: die fertige Antwort kommt auf einmal
                elif event["type"] == "chat.delta" and event["id"] == assistant_id:
                    answer += event["delta"]
                elif event["type"] == "chat.done" and event["id"] == assistant_id:
                    break
                elif event["type"] == "error":
                    answer = f"Fehler: {event['message']}"
                    break
            say(f"\n> {question}\n  ({time.perf_counter() - started:.1f} s)\n  {answer.strip()}")


asyncio.run(main())
