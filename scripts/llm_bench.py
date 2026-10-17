"""Misst das lokale Modell mit dem ECHTEN Prompt und den echten Werkzeugen von Cat.

Im Backend-Container (greift direkt auf Ollama zu, ändert nichts an Cat):

    cd /srv/homelm
    docker compose exec -T backend python - 3 6 < scripts/llm_bench.py

Die Zahlen sind Thread-Anzahlen (num_thread), die nacheinander verglichen werden. Je Anzahl und
Frage werden Prompt-Token, Verarbeitungszeit des Prompts, Ausgabe-Token und Token pro Sekunde
ausgegeben (Werte von Ollama selbst). Jede Frage läuft zweimal: der zweite Lauf zeigt den
Normalfall mit bereits verarbeitetem Prompt-Anfang.
"""

import asyncio
import json
import os
import sys
import tempfile
import time

import httpx

from cat.agent.prompt import build_context, build_local_prompt
from cat.agent.responder import build_responder
from cat.config import Settings
from cat.plugins.manager import PluginManager
from cat.plugins.registry import PluginServices, build_plugins
from cat.state import AppState

QUESTIONS = [
    "Ist das Deckenlicht Roman an?",
    "Schalte das Deckenlicht von Roman aus",
    "Erzähl mir in zwei Sätzen etwas über Katzen",
]


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    threads = [int(a) for a in sys.argv[1:]] or [3]
    settings = Settings(data_dir=tempfile.mkdtemp(prefix="cat-bench-"))  # type: ignore[call-arg]
    state = AppState(settings)

    async def ignore(_: object) -> None: ...

    plugins = PluginManager(
        build_plugins(settings, PluginServices(devices=state.devices)), settings, ignore  # type: ignore[arg-type]
    )
    responder = build_responder(state, extra_tools=plugins.tools())
    agent = responder._agent  # type: ignore[attr-defined]
    tools = agent._registry.schemas()
    system = build_local_prompt(settings.claude_url != "")
    say(f"Modell {settings.local_model}, {len(tools)} Werkzeuge, Prompt {len(system)} Zeichen")

    url = settings.ollama_url.rstrip("/") + "/api/chat"
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as http:
        for n in threads:
            say(f"\n=== num_thread {n} ===")
            for question in QUESTIONS:
                for run in (1, 2):
                    body = {
                        "model": settings.local_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": f"[{build_context()}]\n\n{question}"},
                        ],
                        "tools": tools,
                        "stream": False,
                        "think": False,
                        "keep_alive": settings.local_keep_alive,
                        "options": {
                            "num_ctx": settings.local_num_ctx,
                            "num_thread": n,
                            "num_predict": 120,
                            "temperature": 0.3,
                        },
                    }
                    started = time.perf_counter()
                    data = (await http.post(url, json=body)).json()
                    total = time.perf_counter() - started
                    pe, ps = data.get("prompt_eval_count", 0), data.get("prompt_eval_duration", 1) / 1e9
                    ge, gs = data.get("eval_count", 0), data.get("eval_duration", 1) / 1e9
                    load = data.get("load_duration", 0) / 1e9
                    call = data["message"].get("tool_calls")
                    what = json.dumps(call[0]["function"], ensure_ascii=False)[:70] if call else "Text"
                    say(
                        f"  Lauf {run} | gesamt {total:5.1f}s (Laden {load:4.1f}s) | Prompt {pe:4d} Tok in "
                        f"{ps:5.1f}s = {pe / ps if ps else 0:4.0f}/s | Ausgabe {ge:3d} Tok in {gs:5.1f}s = "
                        f"{ge / gs if gs else 0:4.1f}/s | {what} | {question[:28]}"
                    )


asyncio.run(main())
os._exit(0)
