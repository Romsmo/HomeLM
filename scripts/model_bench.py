"""Vergleicht lokale Modelle an Cats echten Aufgaben (nur Werkzeugwahl, nichts wird ausgeführt).

Im Backend-Container (nutzt Cats Systemprompt, Werkzeugschemas und Ollama-Optionen):

    cd /srv/homelm
    docker compose exec -T backend python - qwen3:4b-instruct-2507-q4_K_M granite4:3b < scripts/model_bench.py

Je Modell und Aufgabe: richtiges Werkzeug und richtige Argumente (ja/nein), Zeit, Prompt-Token,
Ausgabe-Token, Token pro Sekunde (aus den Ollama-Zahlen). Die Modelle müssen in Ollama liegen
(`docker exec homelm-ollama ollama pull <name>`). Jedes Testmodell wird danach entladen.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.plugins.manager import PluginManager
from cat.plugins.registry import PluginServices, build_plugins
from cat.state import AppState

REPEATS = 2


def has(args: dict[str, Any], key: str, *needles: str) -> bool:
    value = str(args.get(key, "")).lower()
    return all(n in value for n in needles)


# (Frage, erwartetes Werkzeug oder None für reinen Text, Prüfung der Argumente)
CASES: list[tuple[str, str | None, Any]] = [
    ("Mach das Deckenlicht von Roman aus", "set_state",
     lambda a: has(a, "device", "roman") and str(a.get("command", "")).lower() in {"off", "aus"}),
    ("Fahr Romans Rollo auf 30 Prozent", "set_state",
     lambda a: has(a, "device", "roll") and "30" in str(a.get("command", ""))),
    ("Dimme das Terrassenlicht auf 40 Prozent", "set_state",
     lambda a: has(a, "device", "terras") and "40" in str(a.get("command", ""))),
    ("Ist das Deckenlicht von Roman an?", "get_state", lambda a: has(a, "device", "roman")),
    ("Welche Rollos und Markisen sind offen?", "list_devices",
     lambda a: str(a.get("state", "")).lower() in {"offen", "open"}),
    ("Welche Lichter sind an?", "list_devices",
     lambda a: str(a.get("state", "")).lower() in {"an", "on", "ein"}),
    ("Welche Automationen gibt es für das Treppenhaus?", "list_automations", lambda a: True),
    ("Welche Automationen sind aktiv?", "list_automations", lambda a: True),
    ("Wie wird das Wetter morgen?", "get_weather", lambda a: True),
    ("Merk dir, dass ich morgens Hafermilch trinke.", "memory_write", lambda a: True),
    ("Wie viele Minuten hat eine Stunde?", None, lambda a: True),
    ("Wer hat Goethes Faust geschrieben?", None, lambda a: True),
]


def parse_compact(text: str) -> tuple[str | None, dict]:
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    parts = [p.strip() for p in line.split("|")]
    if len(parts) >= 2 and parts[0] in ("S", "G", "L", "A"):
        if parts[0] == "A":
            args = {"query": parts[1]} if parts[1] else {}
            if len(parts) >= 3:
                args["state"] = parts[2]
            return "list_automations", args
        if parts[0] == "S" and len(parts) >= 3:
            return "set_state", {"device": parts[1], "command": parts[2]}
        if parts[0] == "G":
            return "get_state", {"device": parts[1]}
        if parts[0] == "L":
            args = {"query": parts[1]}
            if len(parts) >= 3:
                args["state"] = parts[2]
            return "list_devices", args
    return None, {}


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    short = "--short" in sys.argv  # Versuch: kurze Werkzeug- und Parameternamen (weniger Ausgabe-Token)
    models = [a for a in sys.argv[1:] if not a.startswith("--")]
    source = Path(os.environ.get("CAT_DATA_DIR", "/data"))
    scratch = Path(tempfile.mkdtemp(prefix="cat-bench-"))
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
    system, schemas = agent._system_prompt(), agent._registry.schemas()
    base = settings.ollama_url.rstrip("/")
    schemas = agent._registry.schemas(agent._hidden)  # wie im Betrieb (Geräte als Kurzzeile)
    alias = {"set_state": "set", "get_state": "get", "list_devices": "list"}
    keys = {"device": "d", "command": "c", "state": "s", "query": "q"}
    back = {v: k for k, v in alias.items()}
    if short:
        schemas = json.loads(json.dumps(schemas))
        for sch in schemas:
            fn = sch["function"]
            fn["name"] = alias.get(fn["name"], fn["name"])
            props = fn.get("parameters", {}).get("properties", {})
            fn["parameters"]["properties"] = {keys.get(k, k): v for k, v in props.items()}
            fn["parameters"]["required"] = [keys.get(k, k) for k in fn["parameters"].get("required", [])]
        system = system.replace("set_state", "set").replace("get_state", "get").replace(
            "list_devices", "list"
        )
    say(f"Prompt: {len(system)} Zeichen, {len(schemas)} Werkzeuge: " + ", ".join(
        s["function"]["name"] for s in schemas))
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as http:
        for model in models:
            ok = n = 0
            times: list[float] = []
            rates: list[float] = []
            say(f"\n=== {model}")
            for question, want_tool, check in CASES:
                for _ in range(REPEATS):
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
                            "num_predict": 160,
                            "temperature": 0.3,
                        },
                    }
                    started = time.perf_counter()
                    resp = await http.post(base + "/api/chat", json=body)
                    wall = time.perf_counter() - started
                    data = resp.json()
                    if "error" in data:
                        say(f"  FEHLER {data['error'][:120]}")
                        break
                    msg = data.get("message", {})
                    calls = msg.get("tool_calls") or []
                    got = calls[0]["function"]["name"] if calls else None
                    args = calls[0]["function"].get("arguments", {}) if calls else {}
                    if not calls:
                        got, args = parse_compact(msg.get("content", ""))
                    if short and got:
                        got = back.get(got, got)
                        inv = {v: k for k, v in keys.items()}
                        args = {inv.get(k, k): v for k, v in args.items()}
                    good = got == want_tool and (want_tool is None or check(args))
                    if want_tool is None and got == "ask_claude":
                        good = True
                    ok += good
                    n += 1
                    times.append(wall)
                    out_tok = data.get("eval_count", 0)
                    dur = data.get("eval_duration", 1) / 1e9
                    if out_tok > 5:
                        rates.append(out_tok / dur)
                    shown = f"{got}({json.dumps(args, ensure_ascii=False)})" if got else (
                        "Text: " + msg.get("content", "").strip().replace("\n", " ")[:50])
                    say(
                        f"  {'OK ' if good else 'NEIN'} {wall:5.1f} s {out_tok:3d} Tok  "
                        f"{question[:40]:40s} -> {shown[:80]}"
                    )
            if n:
                say(
                    f"  Treffer {ok}/{n}, Zeit im Schnitt {sum(times) / len(times):.1f} s, "
                    f"Ausgabe {sum(rates) / max(len(rates), 1):.1f} Token/s, "
                    f"Prompt {data.get('prompt_eval_count', '?')} Token"
                )
            await http.post(base + "/api/generate", json={"model": model, "keep_alive": 0})
    shutil.rmtree(scratch, ignore_errors=True)


asyncio.run(main())
