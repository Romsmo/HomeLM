"""KI-erzeugte Plugin-Vorschläge: landen in data/plugins/pending/ und sind dort NIE aktiv.

Aktiviert werden sie ausschließlich von Hand (siehe docs/plugins-pending.md): Code prüfen,
Ordner nach data/plugins/active/ verschieben, den Namen in CAT_PLUGINS aufnehmen, neu starten.
Dieser Code importiert, startet oder führt Dateien aus pending/ unter keinen Umständen aus.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.memory.notes import slug
from cat.ws.protocol import StageShow

MAX_CODE = 30_000
MAX_DESCRIPTION = 2_000
MAX_PENDING = 50


class PendingPlugins:
    def __init__(self, root: Path) -> None:
        self.pending = root / "pending"
        self.active = root / "active"

    def list(self) -> list[str]:
        if not self.pending.is_dir():
            return []
        return sorted(p.name for p in self.pending.iterdir() if p.is_dir())

    def propose(self, name: str, description: str, code: str) -> Path:
        code, description = code.strip(), description.strip()
        if not code:
            raise ToolError("Der Plugin-Code ist leer.")
        if len(code) > MAX_CODE:
            raise ToolError(f"Der Plugin-Code ist zu lang (erlaubt {MAX_CODE} Zeichen).")
        if len(description) > MAX_DESCRIPTION:
            raise ToolError("Die Beschreibung ist zu lang.")
        if len(self.list()) >= MAX_PENDING:
            raise ToolError("Es warten schon zu viele Vorschläge. Bitte erst welche prüfen.")
        base = slug(name, "plugin").replace("-", "_")
        folder, n = self.pending / base, 2
        while folder.exists() or (self.active / folder.name).exists():
            folder = self.pending / f"{base}_{n}"  # nie einen vorhandenen Vorschlag überschreiben
            n += 1
        folder.mkdir(parents=True)
        (folder / "plugin.py").write_text(code + "\n", encoding="utf-8")
        (folder / "README.md").write_text(
            f"# {name}\n\n**Status: NICHT AKTIV.** Von Cat vorgeschlagen, noch ungeprüft.\n\n"
            f"{description}\n\nPrüfen und aktivieren: siehe docs/plugins-pending.md\n",
            encoding="utf-8",
        )
        (folder / "meta.json").write_text(
            json.dumps(
                {"name": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "state": "pending"}
            ),
            encoding="utf-8",
        )
        return folder


def build_pending_tools(pending: PendingPlugins) -> list[Tool]:
    async def propose_plugin(args: dict[str, Any], ctx: ToolContext) -> str:
        name, description, code = args.get("name"), args.get("description"), args.get("code")
        if not all(isinstance(v, str) for v in (name, description, code)):
            raise ToolError("Parameter 'name', 'description' und 'code' werden benötigt.")
        folder = await asyncio.to_thread(pending.propose, str(name), str(description), str(code))
        shown = (
            f"**Nicht aktiv.** Vorschlag `{folder.name}`\n\n{description}\n\n```python\n{code}\n```"
        )
        item = ctx.stage.add("markdown", f"Plugin-Vorschlag: {folder.name}", content=shown)
        await ctx.emit(StageShow(item=item))
        return (
            f"Der Vorschlag liegt in data/plugins/pending/{folder.name}/ und ist NICHT aktiv. "
            "Der Nutzer muss ihn prüfen und von Hand freigeben (docs/plugins-pending.md). "
            "Sage ihm das ausdrücklich."
        )

    return [
        Tool(
            name="propose_plugin",
            description=(
                "Schlägt ein neues Cat-Plugin als Python-Code vor (z. B. neue Integration). Der "
                "Vorschlag wird nur abgelegt und angezeigt, er wird NIE automatisch aktiv oder "
                "ausgeführt: Der Nutzer prüft und aktiviert ihn von Hand. Code muss die Plugin-"
                "Schnittstelle erfüllen (PLUGIN-Objekt mit name, start, stop, tools, widgets, "
                "intents)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Kurzer Name, z. B. 'muellkalender'.",
                    },
                    "description": {"type": "string", "description": "Was das Plugin tut."},
                    "code": {"type": "string", "description": "Inhalt von plugin.py."},
                },
                "required": ["name", "description", "code"],
            },
            handler=propose_plugin,
        )
    ]
