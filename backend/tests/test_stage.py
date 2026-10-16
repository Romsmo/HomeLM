from typing import Any

import pytest

from cat.agent.tools import ToolContext, ToolError, ToolRegistry
from cat.stage.models import ChartSpec
from cat.stage.sanitize import (
    MAX_HTML_CHARS,
    ContentError,
    clean_title,
    sanitize_html,
    sanitize_markdown,
)
from cat.stage.store import MAX_HISTORY, StageStore
from cat.stage.tools import register_stage_tools
from cat.ws.protocol import ServerEvent, StageClear, StageShow


class Sink:
    def __init__(self) -> None:
        self.events: list[ServerEvent] = []

    async def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


def setup() -> tuple[ToolRegistry, ToolContext, Sink]:
    registry = ToolRegistry()
    register_stage_tools(registry)
    sink = Sink()
    return registry, ToolContext(emit=sink, stage=StageStore()), sink


async def call(registry: ToolRegistry, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
    tool = registry.get(name)
    assert tool is not None
    return await tool.handler(args, ctx)


# --- Sanitizing ---


def test_html_removes_dangerous_elements() -> None:
    html = (
        '<div>ok</div><iframe src="http://x"></iframe><object data="x"></object>'
        '<embed src="x"><base href="http://evil/"><link rel="stylesheet" href="http://x/a.css">'
        '<meta http-equiv="refresh" content="0;url=http://evil"><meta charset="utf-8">'
        '<script src="http://evil/x.js"></script><script>let action = 1;</script>'
    )
    cleaned = sanitize_html(html)
    for bad in ("iframe", "object", "embed", "<base", "<link", "http-equiv", "evil"):
        assert bad not in cleaned.lower()
    assert "<div>ok</div>" in cleaned
    assert '<meta charset="utf-8">' in cleaned
    assert "let action = 1;" in cleaned  # Inline-Skripte bleiben unverändert


def test_html_is_case_insensitive() -> None:
    assert "iframe" not in sanitize_html("<IFRAME SRC=x></IFRAME><p>a</p>").lower()


def test_html_limits() -> None:
    with pytest.raises(ContentError):
        sanitize_html("   ")
    with pytest.raises(ContentError, match="zu groß"):
        sanitize_html("x" * (MAX_HTML_CHARS + 1))


def test_markdown_and_title_limits() -> None:
    with pytest.raises(ContentError):
        sanitize_markdown("")
    assert len(clean_title("a " * 100)) <= 80
    with pytest.raises(ContentError):
        clean_title("   ")


# --- Chart-Modell ---


def test_chart_spec_requires_matching_lengths() -> None:
    ok = {"type": "bar", "labels": ["a", "b"], "datasets": [{"label": "x", "data": [1, 2]}]}
    assert ChartSpec.model_validate(ok).type == "bar"
    bad = {"type": "bar", "labels": ["a", "b"], "datasets": [{"label": "x", "data": [1]}]}
    with pytest.raises(ValueError, match="erwartet 2"):
        ChartSpec.model_validate(bad)
    with pytest.raises(ValueError):
        ChartSpec.model_validate({**ok, "type": "radar"})


# --- Werkzeuge ---


async def test_show_html_emits_stage_event_and_keeps_history() -> None:
    registry, ctx, sink = setup()
    result = await call(registry, "show_html", {"title": "Uhr", "html": "<svg></svg>"}, ctx)
    assert "Uhr" in result
    event = sink.events[0]
    assert isinstance(event, StageShow)
    assert (event.item.kind, event.item.title, event.item.content) == ("html", "Uhr", "<svg></svg>")
    assert len(ctx.stage.items) == 1


async def test_show_chart_validates_and_emits() -> None:
    registry, ctx, sink = setup()
    spec = {"type": "line", "labels": ["Mo", "Di"], "datasets": [{"label": "T", "data": [1.5, 2]}]}
    await call(registry, "show_chart", {"title": "Temperatur", "spec": spec}, ctx)
    event = sink.events[0]
    assert isinstance(event, StageShow) and event.item.chart is not None
    assert event.item.chart.datasets[0].data == [1.5, 2.0]

    with pytest.raises(ToolError, match="Ungültige Diagrammdaten"):
        await call(registry, "show_chart", {"title": "x", "spec": {"type": "bar"}}, ctx)
    assert len(sink.events) == 1  # Fehlerhafte Aufrufe zeigen nichts


async def test_show_markdown_and_clear() -> None:
    registry, ctx, sink = setup()
    await call(registry, "show_markdown", {"title": "Liste", "text": "- a\n- b"}, ctx)
    await call(registry, "clear_stage", {}, ctx)
    assert isinstance(sink.events[0], StageShow)
    assert isinstance(sink.events[1], StageClear)
    assert ctx.stage.items == []


async def test_tools_reject_bad_arguments() -> None:
    registry, ctx, sink = setup()
    with pytest.raises(ToolError, match="html"):
        await call(registry, "show_html", {"title": "x"}, ctx)
    with pytest.raises(ToolError, match="leer"):
        await call(registry, "show_html", {"title": "x", "html": "  "}, ctx)
    assert sink.events == []


def test_stage_history_is_capped() -> None:
    store = StageStore()
    for i in range(MAX_HISTORY + 5):
        store.add("markdown", f"t{i}", content="x")
    assert len(store.items) == MAX_HISTORY
    assert store.items[-1].title == f"t{MAX_HISTORY + 4}"
