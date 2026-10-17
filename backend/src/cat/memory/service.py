"""Gedächtnis-Dienst: Notizen, Index, Kontext für den Agenten und Werkzeuge."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.memory.index import Hit, NoteIndex
from cat.memory.notes import NoteError, NoteStore
from cat.memory.sessions import SessionLog

log = logging.getLogger("cat.memory")

# Nichts, was wie ein Geheimnis aussieht, ins Gedächtnis schreiben (die Dateien liegen im Klartext).
_SECRET = re.compile(
    r"sk-[A-Za-z0-9_\-]{16,}|oh\.[A-Za-z0-9_\-]{20,}|eyJ[A-Za-z0-9_\-]{20,}\."
    r"|\b(?:passwort|password|kennwort|pin|token|api[-_ ]?key)\s*(?:ist|=|:)\s*\S+",
    re.IGNORECASE,
)
CONTEXT_HITS = 3
CONTEXT_CHARS = 500


class MemoryService:
    def __init__(self, root: Path, sessions_dir: Path, log_sessions: bool = True) -> None:
        self.store = NoteStore(root)
        self.index = NoteIndex(self.store, root / "index.sqlite")
        self.sessions = SessionLog(sessions_dir, enabled=log_sessions)

    # --- Lesen ---

    def search(self, query: str, limit: int = 5, topic: str | None = None) -> list[Hit]:
        return self.index.search(query, limit, topic)

    def context_for(self, user_text: str) -> str:
        """Relevante Erinnerungen als Text für den Systemprompt (leer, wenn nichts passt)."""
        try:
            hits = self.index.search(user_text, CONTEXT_HITS)
        except Exception:
            log.exception("Gedächtnissuche fehlgeschlagen")
            return ""
        if not hits:
            return ""
        lines = [
            f"- [{h.note.topic}] {h.note.title}: {_shorten(h.note.body, CONTEXT_CHARS)}"
            for h in hits
        ]
        return (
            "Erinnerungen aus dem Gedächtnis (können veraltet sein; nutze sie nur, wenn sie zur "
            "Frage passen, und erfinde nichts dazu):\n" + "\n".join(lines)
        )

    # --- Schreiben ---

    def remember(
        self, title: str, text: str, topic: str = "allgemein", tags: list[str] | None = None
    ) -> str:
        if _SECRET.search(title) or _SECRET.search(text):
            raise NoteError(
                "Das sieht nach einem Passwort oder Schlüssel aus. "
                "Solche Angaben speichere ich nicht."
            )
        note = self.store.write(title, text, topic, tags)
        self.index.sync()
        return note.path


def _shorten(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def build_memory_tools(memory: MemoryService) -> list[Tool]:
    async def memory_search(args: dict[str, Any], _: ToolContext) -> str:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("Parameter 'query' fehlt.")
        topic = args.get("topic")
        hits = await asyncio.to_thread(
            memory.search, query, 5, topic if isinstance(topic, str) and topic else None
        )
        if not hits:
            return "Dazu habe ich keine Erinnerung gefunden."
        return "\n\n".join(
            f"[{h.note.topic}] {h.note.title} ({h.note.date})\n{_shorten(h.note.body, 800)}"
            for h in hits
        )

    async def memory_write(args: dict[str, Any], _: ToolContext) -> str:
        title, text = args.get("title"), args.get("text")
        if not isinstance(title, str) or not isinstance(text, str):
            raise ToolError("Parameter 'title' und 'text' werden benötigt.")
        topic = args.get("topic") if isinstance(args.get("topic"), str) else "allgemein"
        raw_tags = args.get("tags")
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else None
        try:
            path = await asyncio.to_thread(memory.remember, title, text, topic or "allgemein", tags)
        except NoteError as exc:
            raise ToolError(str(exc)) from exc
        return f"Gemerkt unter '{path}'."

    async def memory_list(args: dict[str, Any], _: ToolContext) -> str:
        topic = args.get("topic")
        notes = await asyncio.to_thread(
            memory.store.all, topic if isinstance(topic, str) and topic else None
        )
        if not notes:
            return (
                "Das Gedächtnis ist leer."
                if not topic
                else f"Im Thema '{topic}' ist nichts gespeichert."
            )
        return "\n".join(
            f"{n.topic} | {n.title} | {n.date} | {', '.join(n.tags)}" for n in notes[:100]
        )

    return [
        Tool(
            name="memory_search",
            description=(
                "Sucht im Gedächtnis (Notizen über den Haushalt, Vorlieben, frühere Gespräche). "
                "Nutze es, wenn die Antwort von Wissen über den Nutzer oder früher "
                "Besprochenem abhängt."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchbegriffe."},
                    "topic": {"type": "string", "description": "Optional: nur dieses Thema."},
                },
                "required": ["query"],
            },
            handler=memory_search,
        ),
        Tool(
            name="memory_write",
            description=(
                "Merkt sich etwas dauerhaft. Nur auf ausdrückliche Bitte ('merk dir ...') oder bei "
                "klar dauerhaften Fakten wie Vorlieben. Keine Passwörter, Schlüssel oder "
                "Tagesnotizen. "
                "Gleicher Titel im gleichen Thema ergänzt die Notiz."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Kurzer Titel, z. B. 'Kaffee'."},
                    "text": {"type": "string", "description": "Der Inhalt als ein bis zwei Sätze."},
                    "topic": {"type": "string", "description": "Thema, z. B. 'vorlieben'."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "text"],
            },
            handler=memory_write,
        ),
        Tool(
            name="memory_list",
            description="Listet gespeicherte Notizen (Thema, Titel, Datum, Tags).",
            parameters={"type": "object", "properties": {"topic": {"type": "string"}}},
            handler=memory_list,
        ),
    ]
