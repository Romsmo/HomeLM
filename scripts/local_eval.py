"""Prüft das lokale Modell (und bei Bedarf die Weitergabe an Claude) mit echten Fragen.

Läuft im Backend-Container, nutzt dessen Konfiguration (CAT_LOCAL_MODEL, CAT_CLAUDE_URL, ...) und
arbeitet auf einer KOPIE von Konfiguration und Gedächtnis, damit Testfragen wie "merk dir ..."
nichts Echtes ändern:

    cd /srv/homelm
    docker compose exec -T backend python - < scripts/local_eval.py
    docker compose exec -T backend python - "Was ist 17 mal 23?" "Zeig eine Uhr" < scripts/local_eval.py

Ohne Argumente laufen die eingebauten Fragen. Ausgegeben werden je Frage: Antwort, Zeit bis zum
ersten Wort, Gesamtzeit, aufgerufene Werkzeuge und ob Claude gefragt wurde.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.state import AppState
from cat.ws.protocol import ChatMessage

DEFAULT_QUESTIONS = [
    "Wie viele Minuten hat eine Stunde?",
    "Welche Geräte kennst du?",
    "Merk dir bitte, dass ich morgens Kaffee mit Hafermilch trinke.",
    "Was trinke ich morgens?",
    "Was ist 17 mal 23 plus 4?",
    "Schreibe mir ein kurzes Gedicht über den Herbst.",
    "Zeig mir auf der Stage eine animierte Uhr.",
]


def say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


async def main() -> None:
    questions = sys.argv[1:] or DEFAULT_QUESTIONS
    source = Path(os.environ.get("CAT_DATA_DIR", "/data"))
    scratch = Path(tempfile.mkdtemp(prefix="cat-eval-"))
    for name in ("config", "memory"):
        if (source / name).exists():
            shutil.copytree(source / name, scratch / name)
    settings = Settings(data_dir=scratch)  # type: ignore[call-arg]
    state = AppState(settings)
    responder = build_responder(state)
    say(
        f"Modell: {settings.local_model or settings.llm_model}, "
        f"Claude: {'an (' + settings.claude_url + ')' if settings.claude_url else 'aus'}"
    )
    history: list[ChatMessage] = []
    audit_seen = 0
    for question in questions:
        history.append(ChatMessage(id=uuid.uuid4().hex, role="user", text=question, ts=time.time()))
        started = time.perf_counter()
        first: float | None = None
        parts: list[str] = []
        async for delta in responder.reply(list(history)):
            if first is None and delta.strip():
                first = time.perf_counter() - started
            parts.append(delta)
        total = time.perf_counter() - started
        answer = "".join(parts)
        history.append(ChatMessage(id=uuid.uuid4().hex, role="assistant", text=answer, ts=0.0))
        lines = []
        if settings.audit_file.exists():
            lines = settings.audit_file.read_text(encoding="utf-8").splitlines()
        tools = [json.loads(line) for line in lines[audit_seen:]]
        audit_seen = len(lines)
        names = ", ".join(
            f"{t['tool']}{'' if t['ok'] else ' (Fehler)'}" for t in tools if t["tool"] != "fastpath"
        )
        say(f"\n> {question}")
        say(f"  erstes Wort {first if first is None else round(first, 1)} s, gesamt {total:.1f} s")
        say(f"  Werkzeuge: {names or '-'}")
        say("  Antwort: " + answer.strip().replace("\n", "\n           "))
    shutil.rmtree(scratch, ignore_errors=True)


asyncio.run(main())
