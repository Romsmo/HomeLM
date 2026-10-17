import json
from typing import Any

import httpx
import pytest

from cat.llm.base import LLMError, TextDelta, ToolCall
from cat.llm.ollama import OllamaProvider, _to_ollama


def lines(*chunks: dict[str, Any]) -> bytes:
    return ("\n".join(json.dumps(c) for c in chunks) + "\n").encode()


def provider(handler: Any, **kwargs: Any) -> OllamaProvider:
    return OllamaProvider(
        "qwen3:test", "http://ollama:11434/", transport=httpx.MockTransport(handler), **kwargs
    )


async def run(p: OllamaProvider, tools: list[Any] | None = None) -> list[Any]:
    return [e async for e in p.stream("SYS", [{"role": "user", "content": "hi"}], tools or [])]


async def test_streams_text_and_sends_options() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content), url=str(request.url))
        return httpx.Response(
            200,
            content=lines(
                {"message": {"role": "assistant", "content": "Hal"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ),
        )

    events = await run(provider(handler, num_ctx=2048, num_thread=3, keep_alive="5m"))
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hal", "lo"]
    assert seen["url"] == "http://ollama:11434/api/chat"
    assert seen["think"] is False and seen["stream"] is True and seen["keep_alive"] == "5m"
    assert seen["options"]["num_ctx"] == 2048 and seen["options"]["num_thread"] == 3
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    assert "tools" not in seen


async def test_tool_call_arguments_object_and_missing_id() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        call = {"function": {"name": "set_state", "arguments": {"device": "licht", "on": True}}}
        return httpx.Response(
            200, content=lines({"message": {"role": "assistant", "tool_calls": [call]}})
        )

    events = await run(provider(handler), tools=[{"type": "function"}])
    (call,) = [e for e in events if isinstance(e, ToolCall)]
    assert call.name == "set_state" and call.arguments == {"device": "licht", "on": True}
    assert call.id.startswith("call_")


async def test_think_blocks_are_filtered() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=lines(
                {"message": {"content": "<think>grübel"}},
                {"message": {"content": "</think>Antwort"}},
            ),
        )

    events = await run(provider(handler))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Antwort"


async def test_model_missing_is_reported_with_pull_hint() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(LLMError) as exc:
        await run(provider(handler))
    assert "ollama pull qwen3:test" in str(exc.value) and exc.value.unavailable


async def test_server_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model requires more system memory"})

    with pytest.raises(LLMError) as exc:
        await run(provider(handler))
    assert exc.value.unavailable and "more system memory" in str(exc.value)


async def test_connection_refused_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError) as exc:
        await run(provider(handler))
    assert exc.value.unavailable and "nicht erreichbar" in str(exc.value)


async def test_timeout_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMError) as exc:
        await run(provider(handler))
    assert exc.value.unavailable and "zu lange" in str(exc.value)


def test_messages_are_converted_to_ollama_format() -> None:
    converted = _to_ollama(
        [
            {"role": "user", "content": "Licht an"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "set_state", "arguments": '{"device": "licht"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]
    )
    assert converted[1]["tool_calls"] == [
        {"function": {"name": "set_state", "arguments": {"device": "licht"}}}
    ]
    assert converted[2] == {"role": "tool", "tool_name": "set_state", "content": "ok"}
