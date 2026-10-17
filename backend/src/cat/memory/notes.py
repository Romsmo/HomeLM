"""Notizen als Markdown-Dateien: die Quelle der Wahrheit des Gedächtnisses.

Aufbau: data/memory/<thema>/<titel>.md mit Frontmatter (title, date, tags). Die Dateien sind für
Menschen lesbar (z. B. in Obsidian) und hängen von keinem Modell oder Anbieter ab.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from cat.intents.text import fold

MAX_TITLE = 80
MAX_BODY = 8000
MAX_TAGS = 10
MAX_NOTES = 5000
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


class NoteError(Exception):
    """Ungültige Eingabe fürs Gedächtnis; die Meldung darf dem Nutzer gezeigt werden."""


@dataclass(frozen=True)
class Note:
    path: str  # relativ zu data/memory, mit Schrägstrich
    topic: str
    title: str
    date: str
    tags: list[str] = field(default_factory=list)
    body: str = ""


def slug(text: str, fallback: str = "notiz") -> str:
    """Dateisicherer Name: a-z, 0-9 und Bindestriche. Verhindert Pfadtricks ("../")."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return cleaned[:60] or fallback


def parse_note(relative: str, text: str) -> Note:
    meta: dict[str, object] = {}
    body = text
    match = _FRONT.match(text)
    if match:
        try:
            loaded = yaml.safe_load(match.group(1)) or {}
            meta = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            meta = {}
        body = match.group(2)
    parts = relative.split("/")
    topic = parts[0] if len(parts) > 1 else "allgemein"
    raw_tags = meta.get("tags")
    tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    title = str(meta.get("title") or Path(relative).stem.replace("-", " "))
    return Note(
        path=relative,
        topic=topic,
        title=title,
        date=str(meta.get("date") or ""),
        tags=tags,
        body=body.strip(),
    )


class NoteStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise NoteError("Ungültiger Pfad.")
        return path

    def write(
        self, title: str, text: str, topic: str = "allgemein", tags: list[str] | None = None
    ) -> Note:
        title = " ".join(title.split())[:MAX_TITLE]
        text = text.strip()
        if not title:
            raise NoteError("Die Notiz braucht einen Titel.")
        if not text:
            raise NoteError("Die Notiz ist leer.")
        if len(text) > MAX_BODY:
            raise NoteError(f"Die Notiz ist zu lang (erlaubt {MAX_BODY} Zeichen).")
        clean_tags = [t.strip()[:30] for t in (tags or []) if t.strip()][:MAX_TAGS]
        topic_slug = slug(topic, "allgemein")
        if self.count() >= MAX_NOTES:
            raise NoteError("Das Gedächtnis ist voll (zu viele Notizen).")
        relative = f"{topic_slug}/{slug(title)}.md"
        path = self._resolve(relative)
        existing = parse_note(relative, path.read_text(encoding="utf-8")) if path.exists() else None
        # Gleicher Titel im gleichen Thema ergänzt die Notiz, statt sie zu überschreiben.
        body = f"{existing.body}\n\n{text}" if existing else text
        front = {
            "title": title,
            "date": existing.date if existing and existing.date else time.strftime("%Y-%m-%d"),
            "tags": sorted({*(existing.tags if existing else []), *clean_tags}),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"---\n{yaml.safe_dump(front, allow_unicode=True, sort_keys=False)}---\n{body}\n"
        path.write_text(content, encoding="utf-8")
        return parse_note(relative, content)

    def read(self, relative: str) -> Note | None:
        path = self._resolve(relative)
        if not path.is_file():
            return None
        return parse_note(relative, path.read_text(encoding="utf-8"))

    def files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.rglob("*.md") if p.is_file())

    def count(self) -> int:
        return len(self.files())

    def all(self, topic: str | None = None) -> list[Note]:
        notes = []
        for path in self.files():
            relative = path.relative_to(self.root).as_posix()
            if topic and relative.split("/")[0] != slug(topic, "allgemein"):
                continue
            notes.append(parse_note(relative, path.read_text(encoding="utf-8")))
        return notes
