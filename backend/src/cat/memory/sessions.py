"""Gesprächsverlauf je Sitzung (JSON-Zeilen) und Zusammenfassung alter Gespräche in Notizen."""

import asyncio
import json
import logging
import time
from pathlib import Path

from cat.llm.base import LLMError, LLMProvider, TextDelta
from cat.memory.notes import NoteStore

log = logging.getLogger("cat.memory")

MAX_TRANSCRIPT = 12000
SUMMARY_SYSTEM = (
    "Du fasst ein Gespräch zwischen einem Haushaltsmitglied und dem Assistenten Cat zusammen. "
    "Schreibe auf Deutsch 3 bis 8 kurze Stichpunkte (Markdown-Liste) mit dem, was später "
    "nützlich sein kann: Wünsche, Vorlieben, Entscheidungen, offene Aufgaben, Fakten über den "
    "Haushalt. Keine Floskeln, keine Passwörter oder Schlüssel. Wenn nichts Bleibendes "
    "vorkam, antworte mit dem einen Wort: LEER."
)


def new_session_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


class SessionLog:
    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self._dir = directory
        self._enabled = enabled
        self.session_id = new_session_id()

    def new_session(self) -> None:
        self.session_id = new_session_id()

    def _path(self, session_id: str | None = None) -> Path:
        return self._dir / f"{session_id or self.session_id}.jsonl"

    def append(self, role: str, text: str) -> None:
        if not self._enabled or not text.strip():
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps({"ts": time.time(), "role": role, "text": text}, ensure_ascii=False)
            with self._path().open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            log.exception("Sitzungsverlauf nicht schreibbar")

    def read(self, session_id: str) -> list[dict[str, object]]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def old_unsummarized(self, min_age_days: float, now: float | None = None) -> list[str]:
        """Sitzungen, die älter als `min_age_days` sind, nicht laufen und noch keine Notiz haben."""
        if not self._dir.is_dir():
            return []
        now = now or time.time()
        found = []
        for path in sorted(self._dir.glob("*.jsonl")):
            if path.stem == self.session_id or path.with_suffix(".done").exists():
                continue
            if now - path.stat().st_mtime >= min_age_days * 86400:
                found.append(path.stem)
        return found

    def mark_done(self, session_id: str) -> None:
        self._path(session_id).with_suffix(".done").write_text("ok\n", encoding="utf-8")


def transcript(rows: list[dict[str, object]]) -> str:
    names = {"user": "Nutzer", "assistant": "Cat"}
    text = "\n".join(
        f"{names.get(str(r.get('role')), 'System')}: {r.get('text', '')}" for r in rows
    )
    return text[-MAX_TRANSCRIPT:]


async def summarize_old_sessions(
    sessions: SessionLog,
    notes: NoteStore,
    provider: LLMProvider,
    min_age_days: float = 3.0,
) -> int:
    """Fasst alte Sitzungen per LLM zusammen (Thema "gespraeche"). Gibt die Zahl der Notizen zurück.

    Fehler (z. B. kein Internet) lassen die Sitzung unberührt, der nächste Start versucht es erneut.
    """
    written = 0
    for session_id in sessions.old_unsummarized(min_age_days):
        rows = sessions.read(session_id)
        if len([r for r in rows if r.get("role") == "user"]) < 2:
            sessions.mark_done(session_id)  # zu kurz, nichts Bleibendes zu erwarten
            continue
        try:
            parts = [
                event.text
                async for event in provider.stream(
                    SUMMARY_SYSTEM, [{"role": "user", "content": transcript(rows)}], []
                )
                if isinstance(event, TextDelta)
            ]
        except LLMError as exc:
            log.warning("Zusammenfassung von %s nicht möglich: %s", session_id, exc)
            return written
        summary = "".join(parts).strip()
        if summary and summary.upper() != "LEER":
            date = f"{session_id[:4]}-{session_id[4:6]}-{session_id[6:8]}"
            await asyncio.to_thread(
                notes.write,
                f"Gespräch {date} {session_id[9:13]}",
                summary,
                "gespraeche",
                ["gespräch"],
            )
            written += 1
        sessions.mark_done(session_id)
    return written
