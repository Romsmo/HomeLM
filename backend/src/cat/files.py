"""Eingang für Dateien, die der Nutzer per Drag-and-drop in Cat ablegt (`data/inbox`).

Dateien werden nur gespeichert und gelesen, nie ausgeführt. Der Name wird bereinigt (kein Pfad,
keine Steuerzeichen), Größe und Gesamtmenge sind begrenzt, und beim Ausliefern bekommen sie
`nosniff` und eine Sandbox-CSP (siehe api_files.py).
"""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_INBOX_BYTES = 500 * 1024 * 1024
MAX_NAME_CHARS = 100

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
TEXT_EXT = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml", ".xml",
    ".ini", ".toml", ".py", ".js", ".ts", ".html", ".css", ".sql", ".sh", ".conf",
}  # fmt: skip
MARKDOWN_EXT = {".md", ".markdown"}

_BAD = re.compile(r"[^\w.\- äöüÄÖÜß()]+")


class FileError(ValueError):
    """Meldung, die dem Nutzer gezeigt werden darf."""


@dataclass(frozen=True)
class StoredFile:
    name: str
    size: int
    kind: str  # "image", "text", "other"
    modified: float


def clean_name(raw: str) -> str:
    """Nur der Dateiname, ohne Pfad und Sonderzeichen; nie leer, nie versteckt."""
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _BAD.sub("_", name).strip(" .")
    if not name:
        name = "datei"
    if len(name) > MAX_NAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        ext = f".{ext}"[:12] if dot else ""
        name = (stem or name)[: MAX_NAME_CHARS - len(ext)] + ext
    return name


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return "other"


class Inbox:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _unique(self, name: str) -> str:
        if not (self.root / name).exists():
            return name
        stem, ext = Path(name).stem, Path(name).suffix
        for i in range(2, 1000):
            candidate = f"{stem} ({i}){ext}"
            if not (self.root / candidate).exists():
                return candidate
        raise FileError("Zu viele Dateien mit gleichem Namen.")

    def used_bytes(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())

    def new_path(self, raw_name: str) -> Path:
        """Zielpfad für einen Upload (Ordner wird angelegt, Name ist eindeutig)."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / self._unique(clean_name(raw_name))

    def describe(self, path: Path) -> StoredFile:
        stat = path.stat()
        return StoredFile(path.name, stat.st_size, kind_of(path.name), stat.st_mtime)

    def list(self, limit: int = 50) -> list[StoredFile]:
        if not self.root.is_dir():
            return []
        files = [
            self.describe(p)
            for p in self.root.iterdir()
            if p.is_file() and not p.name.startswith(".")
        ]
        return sorted(files, key=lambda f: f.modified, reverse=True)[:limit]

    def path_of(self, name: str) -> Path:
        """Pfad einer vorhandenen Datei; Namen mit Pfadanteilen werden abgelehnt."""
        if name != clean_name(name) or name.startswith("."):
            raise FileError("Ungültiger Dateiname.")
        path = self.root / name
        if not path.is_file():
            raise FileError(f"Die Datei '{name}' gibt es nicht.")
        return path

    def delete(self, name: str) -> None:
        self.path_of(name).unlink()

    def read_text(self, name: str, max_chars: int = 6000) -> tuple[str, bool]:
        """Text einer Datei (gekürzt, ob gekürzt wurde). Nur Textarten."""
        path = self.path_of(name)
        if kind_of(name) != "text":
            raise FileError(
                f"'{name}' ist keine Textdatei (nur z. B. .txt, .md, .csv, .json). "
                "Bilder und PDFs kann nur Claude ansehen."
            )
        with path.open("rb") as fh:
            raw = fh.read(max_chars * 4 + 4)
        text = raw.decode("utf-8", errors="replace")
        return text[:max_chars], len(text) > max_chars or path.stat().st_size > len(raw)


def age_text(modified: float, now: float | None = None) -> str:
    seconds = max(0, int((now or time.time()) - modified))
    if seconds < 90:
        return "gerade eben"
    if seconds < 5400:
        return f"vor {seconds // 60} Min"
    if seconds < 172800:
        return f"vor {seconds // 3600} Std"
    return f"vor {seconds // 86400} Tagen"


def build_file_tools(inbox: Inbox) -> list[Tool]:
    """Werkzeuge für den Agenten: abgelegte Dateien auflisten und Textdateien lesen."""

    async def list_files(_: dict[str, Any], __: ToolContext) -> str:
        files = await asyncio.to_thread(inbox.list, 20)
        if not files:
            return "Es sind keine Dateien abgelegt."
        return "\n".join(
            f"{f.name} | {f.kind} | {max(1, f.size // 1024)} KB | {age_text(f.modified)}"
            for f in files
        )

    async def read_file(args: dict[str, Any], _: ToolContext) -> str:
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("Parameter 'name' fehlt.")
        limit = args.get("max_chars")
        limit = limit if isinstance(limit, int) and 200 <= limit <= 12000 else 6000
        try:
            text, cut = await asyncio.to_thread(inbox.read_text, name, limit)
        except FileError as exc:
            raise ToolError(str(exc)) from exc
        return text + ("\n[gekürzt]" if cut else "")

    return [
        Tool(
            name="list_files",
            description=(
                "Zeigt die Dateien, die der Nutzer in Cat abgelegt hat (Name, Art, Größe, Alter), "
                "neueste zuerst."
            ),
            parameters={"type": "object", "properties": {}},
            handler=list_files,
        ),
        Tool(
            name="read_file",
            description=(
                "Liest eine abgelegte Textdatei (txt, md, csv, json, ...). Bilder und PDFs "
                "kann nur Claude ansehen."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Dateiname aus list_files."},
                    "max_chars": {"type": "integer", "description": "Höchstens so viele Zeichen."},
                },
                "required": ["name"],
            },
            handler=read_file,
        ),
    ]
