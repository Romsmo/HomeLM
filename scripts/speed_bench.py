"""Misst Prompt-Verarbeitung und Ausgabe-Geschwindigkeit von Ollama-Modellen und -Optionen.

Im Backend-Container (nutzt Cats echten Systemprompt und echte Werkzeugschemas):

    cd /srv/homelm
    docker compose exec -T backend python - < scripts/speed_bench.py

Je Variante (Modell, Threads, Batch): Kaltstart-Verarbeitung des ganzen Prompts (Token/s), danach
eine neue Frage mit bekanntem Anfang (nur die neuen Token) und die Ausgabe-Geschwindigkeit
(Token/s) bei einem Befehl. Jede Variante wird danach entladen.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.plugins.manager import PluginManager
from cat.plugins.registry import PluginServices, build_plugins
from cat.state import AppState

CURRENT = "qwen3:4b-instruct-2507-q4_K_M"
Q4_0 = "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_0"
Q4_K_S = "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_S"
VARIANTS: list[tuple[str, dict]] = [
    (CURRENT, {}),
    (Q4_0, {}),
    (Q4_K_S, {}),
    (CURRENT, {"num_thread": 4}),
    (CURRENT, {"num_thread": 6}),
    (CURRENT, {"num_batch": 1024}),
    (CURRENT, {"num_batch": 256}),
]
QUESTIONS = [
    "Mach das Deckenlicht von Roman aus",
    "Welche Rollos und Markisen sind offen?",
    "Fahr Romans Rollo auf 30 Prozent",
]


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    source = Path(os.environ.get("CAT_DATA_DIR", "/data"))
    scratch = Path(tempfile.mkdtemp(prefix="cat-speed-"))
    for name in ("config", "memory"):
        if (source / name).exists():
            shutil.copytree(source / name, scratch / name)
    settings = Settings(data_dir=scratch)  # type: ignore[call-arg]
    state = AppState(settings)

    async def ignore(_: object) -> None: ...

    plugins = PluginManager(
        build_plugins(settings, PluginServices(devices=state.devices)),  # type: ignore[arg-type]
        settings,
        ignore,
    )
    responder = build_responder(state, extra_tools=plugins.tools())
    agent = responder._agent  # type: ignore[attr-defined]
    system, schemas = agent._system_prompt(), agent._registry.schemas(agent._hidden)
    base = settings.ollama_url.rstrip("/")
    say(f"Prompt: {len(system)} Zeichen, {len(schemas)} Werkzeuge")
    async with httpx.AsyncClient(timeout=httpx.Timeout(400.0)) as http:

        async def ask(model: str, options: dict, question: str) -> dict:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                "tools": schemas,
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {
                    "num_ctx": settings.local_num_ctx,
                    "num_thread": settings.local_threads,
                    "num_predict": 60,
                    "temperature": 0.3,
                    **options,
                },
            }
            return (await http.post(base + "/api/chat", json=body)).json()

        for model, options in VARIANTS:
            label = f"{model.split('/')[-1][:34]:34s} {options or ''}"
            try:
                await http.post(base + "/api/generate", json={"model": model, "keep_alive": 0})
                await asyncio.sleep(3)
                cold = await ask(model, options, QUESTIONS[0])
                rows = [await ask(model, options, q) for q in QUESTIONS[1:] * 2]
            except Exception as exc:  # noqa: BLE001
                say(f"{label}: Fehler {type(exc).__name__}")
                continue
            if "error" in cold:
                say(f"{label}: {cold['error'][:80]}")
                continue
            c_tok = cold.get("prompt_eval_count", 0)
            c_s = cold.get("prompt_eval_duration", 1) / 1e9
            warm_s = sum(r.get("prompt_eval_duration", 0) for r in rows) / len(rows) / 1e9
            warm_n = sum(r.get("prompt_eval_count", 0) for r in rows) / len(rows)
            dec = [r["eval_count"] / (r["eval_duration"] / 1e9) for r in rows if r.get("eval_count", 0) > 5]
            say(
                f"{label} Kaltstart {c_tok} Token in {c_s:4.1f} s ({c_tok / c_s:4.0f} Tok/s) | "
                f"warm {warm_s:3.1f} s ({warm_n:.0f} Token) | Ausgabe {sum(dec) / max(len(dec), 1):4.1f} Tok/s"
            )
            await http.post(base + "/api/generate", json={"model": model, "keep_alive": 0})
    shutil.rmtree(scratch, ignore_errors=True)


asyncio.run(main())
