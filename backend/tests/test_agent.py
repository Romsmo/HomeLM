import json
from typing import Any

import pytest

from cat.agent.loop import LIMIT_NOTICE, Agent, to_llm_messages
from cat.agent.tools import Tool, ToolContext, ToolError, ToolRegistry
from cat.llm.base import TextDelta, ToolCall
from cat.stage.store import StageStore
from cat.ws.protocol import ServerEvent
from tests.fakes import FakeProvider


class Collector:
    def __init__(self) -> None:
        self.events: list[ServerEvent] = []

    async def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


def make_agent(provider: FakeProvider, *tools: Tool, max_steps: int = 6) -> Agent:
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    return Agent(provider, registry, lambda: "SYSTEM", max_steps=max_steps)


def ctx() -> ToolContext:
    return ToolContext(emit=Collector(), stage=StageStore())


async def collect(agent: Agent, history: list[dict[str, Any]] | None = None) -> str:
    history = history or [{"role": "user", "content": "hi"}]
    return "".join([d async for d in agent.run(history, ctx())])


def echo_tool(calls: list[dict[str, Any]]) -> Tool:
    async def handler(args: dict[str, Any], _: ToolContext) -> str:
        calls.append(args)
        return f"ok {args.get('x')}"

    return Tool("echo", "Echo", {"type": "object", "properties": {}}, handler)


async def test_plain_answer_streams_text() -> None:
    provider = FakeProvider([TextDelta("Hallo "), TextDelta("Welt")])
    assert await collect(make_agent(provider)) == "Hallo Welt"
    assert provider.calls[0]["system"] == "SYSTEM"


async def test_tool_loop_runs_tool_then_answers() -> None:
    seen: list[dict[str, Any]] = []
    provider = FakeProvider(
        [ToolCall("c1", "echo", {"x": 1})],
        [TextDelta("Fertig.")],
    )
    text = await collect(make_agent(provider, echo_tool(seen)))
    assert text == "Fertig."
    assert seen == [{"x": 1}]
    second = provider.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "echo"
    assert json.loads(second[-2]["tool_calls"][0]["function"]["arguments"]) == {"x": 1}
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "ok 1"}


async def test_text_before_and_after_tool_is_separated() -> None:
    provider = FakeProvider(
        [TextDelta("Moment."), ToolCall("c1", "echo", {})],
        [TextDelta("Da.")],
    )
    assert await collect(make_agent(provider, echo_tool([]))) == "Moment.\n\nDa."


async def test_unknown_tool_and_bad_arguments_go_back_to_model() -> None:
    provider = FakeProvider(
        [ToolCall("c1", "gibts_nicht", {}), ToolCall("c2", "echo", None, "{kaputt")],
        [TextDelta("ok")],
    )
    await collect(make_agent(provider, echo_tool([])))
    tool_msgs = [m for m in provider.calls[1]["messages"] if m["role"] == "tool"]
    assert "gibt es nicht" in tool_msgs[0]["content"]
    assert "kein gültiges JSON" in tool_msgs[1]["content"]


async def test_tool_errors_are_reported_not_raised() -> None:
    async def failing(_: dict[str, Any], __: ToolContext) -> str:
        raise ToolError("Parameter fehlt")

    async def crashing(_: dict[str, Any], __: ToolContext) -> str:
        raise RuntimeError("geheim: sk-123")

    provider = FakeProvider(
        [ToolCall("a", "fail", {}), ToolCall("b", "crash", {})],
        [TextDelta("ok")],
    )
    agent = make_agent(
        provider,
        Tool("fail", "", {"type": "object"}, failing),
        Tool("crash", "", {"type": "object"}, crashing),
    )
    await collect(agent)
    results = [m["content"] for m in provider.calls[1]["messages"] if m["role"] == "tool"]
    assert results[0] == "Fehler: Parameter fehlt"
    assert "geheim" not in results[1] and results[1].startswith("Fehler:")


async def test_step_limit_stops_endless_tool_loops() -> None:
    steps = [[ToolCall(f"c{i}", "echo", {})] for i in range(3)]
    provider = FakeProvider(*steps)
    text = await collect(make_agent(provider, echo_tool([]), max_steps=3))
    assert text == LIMIT_NOTICE
    assert len(provider.calls) == 3


async def test_history_is_not_mutated() -> None:
    history: list[dict[str, Any]] = [{"role": "user", "content": "hi"}]
    provider = FakeProvider([ToolCall("c1", "echo", {})], [TextDelta("x")])
    await collect(make_agent(provider, echo_tool([])), history)
    assert history == [{"role": "user", "content": "hi"}]


def test_tool_schemas_use_function_format() -> None:
    registry = ToolRegistry()
    registry.register(echo_tool([]))
    schema = registry.schemas()[0]
    assert schema["type"] == "function" and schema["function"]["name"] == "echo"
    with pytest.raises(ValueError):
        registry.register(echo_tool([]))


def test_to_llm_messages_normalizes_history() -> None:
    items = [
        ("assistant", "verwaist"),
        ("user", "a"),
        ("user", "b"),  # Antwort darauf ist ausgefallen
        ("assistant", "c"),
        ("system", "ignoriert"),
        ("user", "  "),
    ]
    assert to_llm_messages(items) == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]
    many = [("user" if i % 2 == 0 else "assistant", str(i)) for i in range(100)]
    assert len(to_llm_messages(many, limit=10)) == 10
