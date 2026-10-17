"""SQLite-Index (FTS5) über den Notizen. Wegwerf-Cache: Die Markdown-Dateien sind die Wahrheit.

Der Index wird bei jeder Suche mit dem Dateistand abgeglichen (Größe und Änderungszeit), eine
manuelle Neuindizierung ist nie nötig. Eine Vektorsuche ist als Schnittstelle vorbereitet.
"""

import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cat.intents.text import fold, tokenize
from cat.memory.notes import Note, NoteStore, parse_note

_STOP = frozenset(
    """
    der die das den dem des ein eine einen einer und oder aber ich du er sie es wir ihr mein meine
    meinen meinem dein ist sind war bin bist hat habe haben wie was wer wo wann warum wieso welche
    welcher welches mit von zu zum zur im in am an auf aus bei nach fuer mir mich dir dich
    dass nicht kein keine auch noch schon mal bitte
    """.split()
)


@dataclass(frozen=True)
class Hit:
    note: Note
    score: float


class VectorIndex(Protocol):
    """Vorbereitete Schnittstelle für eine spätere Vektorsuche (z. B. sqlite-vec)."""

    def search(self, query: str, limit: int) -> Sequence[tuple[str, float]]: ...


class NullVectorIndex:
    """Platzhalter: keine Vektorsuche. Ersetzbar, ohne den Rest zu ändern."""

    def search(self, query: str, limit: int) -> Sequence[tuple[str, float]]:
        return []


def fts_query(text: str) -> str | None:
    """Baut eine tolerante FTS5-Anfrage: Wortanfänge (ersetzen ein Stemming), ODER-verknüpft."""
    terms: list[str] = []
    for token in tokenize(text):
        if len(token) < 3 or token in _STOP or token.isdigit():
            continue
        stem = token[: max(4, len(token) - 2)] if len(token) > 5 else token
        if re.fullmatch(r"[a-z0-9]+", stem):
            terms.append(f'"{stem}"*')
    return " OR ".join(dict.fromkeys(terms)) or None


class NoteIndex:
    def __init__(self, store: NoteStore, db_path: Path, vectors: VectorIndex | None = None) -> None:
        self._store = store
        self._db_path = db_path
        self.vectors: VectorIndex = vectors or NullVectorIndex()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Verbindung mit Commit am Ende und garantiertem Schließen."""
        db = sqlite3.connect(self._db_path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS files("
                "path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)"
            )
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5("
                "path UNINDEXED, topic, title, tags, body, "
                "tokenize='unicode61 remove_diacritics 2')"
            )

    def sync(self) -> int:
        """Gleicht den Index mit den Dateien ab. Gibt die Zahl geänderter Notizen zurück."""
        on_disk = {}
        for path in self._store.files():
            stat = path.stat()
            on_disk[path.relative_to(self._store.root).as_posix()] = (
                stat.st_mtime_ns,
                stat.st_size,
            )
        changed = 0
        with self._connect() as db:
            known = {
                r[0]: (r[1], r[2]) for r in db.execute("SELECT path, mtime_ns, size FROM files")
            }
            for gone in set(known) - set(on_disk):
                db.execute("DELETE FROM notes WHERE path = ?", (gone,))
                db.execute("DELETE FROM files WHERE path = ?", (gone,))
                changed += 1
            for relative, signature in on_disk.items():
                if known.get(relative) == signature:
                    continue
                note = parse_note(
                    relative, (self._store.root / relative).read_text(encoding="utf-8")
                )
                db.execute("DELETE FROM notes WHERE path = ?", (relative,))
                db.execute(
                    "INSERT INTO notes(path, topic, title, tags, body) VALUES (?, ?, ?, ?, ?)",
                    (
                        relative,
                        fold(note.topic),
                        fold(note.title),
                        fold(" ".join(note.tags)),
                        fold(note.body),
                    ),
                )
                db.execute(
                    "INSERT OR REPLACE INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
                    (relative, *signature),
                )
                changed += 1
        return changed

    def search(self, query: str, limit: int = 5, topic: str | None = None) -> list[Hit]:
        match = fts_query(query)
        if match is None:
            return []
        self.sync()
        sql = (
            "SELECT path, bm25(notes, 0, 2.0, 4.0, 3.0, 1.0) AS rank FROM notes WHERE notes MATCH ?"
        )
        params: list[object] = [match]
        if topic:
            sql += " AND topic = ?"
            params.append(fold(topic))
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        hits = []
        for relative, rank in rows:
            note = self._store.read(relative)
            if note is not None:
                hits.append(
                    Hit(note, -float(rank))
                )  # bm25: kleiner = besser; hier: größer = besser
        return hits
