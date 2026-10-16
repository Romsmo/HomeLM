from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from cat.llm import litellm_provider
from cat.llm.base import LLMError, TextDelta, ToolCall
from cat.llm.litellm_provider import LiteLLMProvider


def chunk(content: str | None = None, tool_calls: list[Any] | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def tc(index: int, id: str | None = None, name: str | None = None, args: str | None = None) -> Any:
    function = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=index, id=id, function=function)


class FakeLiteLLM:
    class AuthenticationError(Exception): ...

    class RateLimitError(Exception): ...

    class NotFoundError(Exception): ...

    class BadRequestError(Exception): ...

    class APIConnectionError(Exception): ...

    class Timeout(Exception): ...

    def __init__(self, chunks: list[Any] | Exception) -> None:
        self._chunks = chunks
        self.kwargs: dict[str, Any] = {}

    async def acompletion(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self._chunks, Exception):
            raise self._chunks

        async def gen() -> Any:
            for c in self._chunks:  # type: ignore[union-attr]
                yield c

        return gen()


def patch(monkeypatch: pytest.MonkeyPatch, fake: FakeLiteLLM) -> None:
    monkeypatch.setattr(litellm_provider, "_load_litellm", lambda: fake)


async def run(provider: LiteLLMProvider) -> list[Any]:
    return [e async for e in provider.stream("sys", [{"role": "user", "content": "hi"}], [])]


async def test_streams_text_and_assembles_tool_call_from_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLiteLLM(
        [
            chunk("Ich "),
            chunk("zeige"),
            chunk(tool_calls=[tc(0, id="call_1", name="show_html", args='{"title": "U')]),
            chunk(tool_calls=[tc(0, args='hr", "html": "<p/>"}')]),
            SimpleNamespace(choices=[]),
        ]
    )
    patch(monkeypatch, fake)
    events = await run(LiteLLMProvider("anthropic/x", api_key=SecretStr("k")))
    assert events[:2] == [TextDelta("Ich "), TextDelta("zeige")]
    call = events[2]
    assert isinstance(call, ToolCall)
    assert (call.id, call.name) == ("call_1", "show_html")
    assert call.arguments == {"title": "Uhr", "html": "<p/>"}
    assert fake.kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert fake.kwargs["stream"] is True


async def test_invalid_tool_arguments_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLiteLLM([chunk(tool_calls=[tc(0, id="c", name="t", args="{kaputt")])])
    patch(monkeypatch, fake)
    events = await run(LiteLLMProvider("openai/x"))
    assert isinstance(events[0], ToolCall) and events[0].arguments is None


async def test_missing_api_key_gives_clear_error_without_calling_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLiteLLM([])
    patch(monkeypatch, fake)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        await run(LiteLLMProvider("anthropic/claude-haiku-5-5"))
    assert fake.kwargs == {}


@pytest.mark.parametrize(
    ("exc_name", "fragment"),
    [
        ("AuthenticationError", "abgelehnt"),
        ("RateLimitError", "überlastet"),
        ("APIConnectionError", "Keine Verbindung"),
        ("NotFoundError", "CAT_LLM_MODEL"),
    ],
)
async def test_errors_are_translated_and_do_not_leak_details(
    monkeypatch: pytest.MonkeyPatch, exc_name: str, fragment: str
) -> None:
    fake = FakeLiteLLM(getattr(FakeLiteLLM, exc_name)("secret sk-ant-123 details"))
    patch(monkeypatch, fake)
    with pytest.raises(LLMError) as info:
        await run(LiteLLMProvider("anthropic/x", api_key=SecretStr("k")))
    assert fragment in str(info.value)
    assert "sk-ant" not in str(info.value)


async def test_api_key_is_passed_but_never_in_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLiteLLM([chunk("ok")])
    patch(monkeypatch, fake)
    await run(LiteLLMProvider("anthropic/x", api_key=SecretStr("sk-test")))
    assert fake.kwargs["api_key"] == "sk-test"
    assert "sk-test" not in str(fake.kwargs["messages"])
