from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.sandbox.client import SandboxClient, SandboxError, image_html
from cat.ws.protocol import StageShow

OUTPUT_FOR_MODEL = 3000


def _clip(text: str) -> str:
    return text if len(text) <= OUTPUT_FOR_MODEL else text[:OUTPUT_FOR_MODEL] + "\n… (gekürzt)"


def build_sandbox_tools(client: SandboxClient) -> list[Tool]:
    async def run_python(args: dict[str, Any], ctx: ToolContext) -> str:
        code = args.get("code")
        if not isinstance(code, str):
            raise ToolError("Parameter 'code' fehlt.")
        timeout = args.get("timeout_s", 10)
        try:
            result = await client.run(
                code, int(timeout) if isinstance(timeout, int | float) else 10
            )
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc

        parts: list[str] = []
        if result.timed_out:
            parts.append("Abgebrochen: Zeitlimit überschritten.")
        elif result.error:
            parts.append(f"Fehler: {result.error}")
        elif not result.ok:
            parts.append(f"Das Programm endete mit Fehlercode {result.exit_code}.")
        if result.stdout.strip():
            parts.append(f"Ausgabe:\n{_clip(result.stdout.strip())}")
        if result.stderr.strip():
            parts.append(f"Fehlerausgabe:\n{_clip(result.stderr.strip())}")
        if result.images:
            item = ctx.stage.add(
                "html", "Python-Ergebnis", content=image_html(result.images, "Python-Ergebnis")
            )
            await ctx.emit(StageShow(item=item))
            parts.append(f"{len(result.images)} Bild(er) werden auf der Stage angezeigt.")
        if not parts:
            parts.append(f"Fertig in {result.duration_ms} ms, keine Ausgabe.")
        if not result.ok:
            raise ToolError("\n".join(parts))
        return "\n".join(parts)

    return [
        Tool(
            name="run_python",
            description=(
                "Führt Python 3.12 in einer abgeschotteten Sandbox aus (kein Netzwerk, keine "
                "Dateien des Hauses, wenig Speicher, Zeitlimit). Verfügbar: Standardbibliothek, "
                "numpy, matplotlib. Für Rechnungen, Auswertungen und Diagramme. Ausgabe über "
                "print(). Diagramme als PNG im aktuellen Ordner speichern "
                "(plt.savefig('bild.png')): sie erscheinen dann auf der Stage."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Vollständiges Python-Programm."},
                    "timeout_s": {
                        "type": "integer",
                        "description": "Zeitlimit, 1 bis 30 (Standard 10).",
                    },
                },
                "required": ["code"],
            },
            handler=run_python,
            risk="medium",
        )
    ]
