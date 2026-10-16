"""Stage-Werkzeuge für das Modell: show_html, show_chart, show_markdown, clear_stage."""

from typing import Any

from pydantic import ValidationError

from cat.agent.tools import Tool, ToolContext, ToolError, ToolRegistry
from cat.stage.models import ChartSpec
from cat.stage.sanitize import ContentError, clean_title, sanitize_html, sanitize_markdown
from cat.ws.protocol import StageClear, StageShow


def _text_arg(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"Parameter '{key}' fehlt oder ist kein Text.")
    return value


async def show_html(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        title = clean_title(_text_arg(args, "title"))
        html = sanitize_html(_text_arg(args, "html"))
    except ContentError as exc:
        raise ToolError(str(exc)) from exc
    item = ctx.stage.add("html", title, content=html)
    await ctx.emit(StageShow(item=item))
    return f"HTML-Grafik '{title}' wird auf der Stage angezeigt."


async def show_markdown(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        title = clean_title(_text_arg(args, "title"))
        text = sanitize_markdown(_text_arg(args, "text"))
    except ContentError as exc:
        raise ToolError(str(exc)) from exc
    item = ctx.stage.add("markdown", title, content=text)
    await ctx.emit(StageShow(item=item))
    return f"Text '{title}' wird auf der Stage angezeigt."


async def show_chart(args: dict[str, Any], ctx: ToolContext) -> str:
    try:
        title = clean_title(_text_arg(args, "title"))
        spec = ChartSpec.model_validate(args.get("spec"))
    except ContentError as exc:
        raise ToolError(str(exc)) from exc
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise ToolError(f"Ungültige Diagrammdaten ({details}).") from exc
    item = ctx.stage.add("chart", title, chart=spec)
    await ctx.emit(StageShow(item=item))
    return f"Diagramm '{title}' wird auf der Stage angezeigt."


async def clear_stage(args: dict[str, Any], ctx: ToolContext) -> str:
    ctx.stage.clear()
    await ctx.emit(StageClear())
    return "Die Stage ist leer."


_TITLE = {"type": "string", "description": "Kurzer Titel (max. 80 Zeichen)."}


def register_stage_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="show_html",
            description=(
                "Zeigt eine HTML-Grafik auf der Stage (z. B. Uhr, Animation, Skizze, kleine "
                "Oberfläche). Das HTML muss in sich geschlossen sein: inline CSS, inline "
                "JavaScript, SVG oder Canvas. Es läuft in einer Sandbox ohne Netzwerk: keine "
                "externen Skripte, Bilder, Schriften oder API-Aufrufe (Bilder nur als data:-URL)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": _TITLE,
                    "html": {
                        "type": "string",
                        "description": "HTML-Fragment oder Dokument. Dunkler Hintergrund passt "
                        "zur Oberfläche; die Fläche füllt das ganze Stage-Fenster.",
                    },
                },
                "required": ["title", "html"],
            },
            handler=show_html,
        )
    )
    registry.register(
        Tool(
            name="show_chart",
            description=(
                "Zeigt ein Diagramm (Balken, Linie, Torte, Ring) aus strukturierten Daten. "
                "Bevorzugt dieses Werkzeug für Zahlen statt selbstgebautem HTML."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": _TITLE,
                    "spec": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["bar", "line", "pie", "doughnut"]},
                            "labels": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Beschriftungen (x-Achse oder Segmente).",
                            },
                            "datasets": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "data": {"type": "array", "items": {"type": "number"}},
                                    },
                                    "required": ["label", "data"],
                                },
                                "description": "Je Datensatz so viele Werte wie labels.",
                            },
                            "x_label": {"type": "string"},
                            "y_label": {"type": "string"},
                        },
                        "required": ["type", "labels", "datasets"],
                    },
                },
                "required": ["title", "spec"],
            },
            handler=show_chart,
        )
    )
    registry.register(
        Tool(
            name="show_markdown",
            description="Zeigt formatierten Text (Markdown, Tabellen, Listen) auf der Stage.",
            parameters={
                "type": "object",
                "properties": {
                    "title": _TITLE,
                    "text": {"type": "string", "description": "Markdown-Text."},
                },
                "required": ["title", "text"],
            },
            handler=show_markdown,
        )
    )
    registry.register(
        Tool(
            name="clear_stage",
            description="Leert die Stage und ihre Historie.",
            parameters={"type": "object", "properties": {}},
            handler=clear_stage,
        )
    )
