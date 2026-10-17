import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.llm.base import LLMError, TextDelta
from cat.llm.fallback import FallbackProvider
from cat.llm.litellm_provider import LiteLLMProvider, ThinkFilter, _describe
from cat.main import create_app
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider
from tests.helpers import drain_replay
from tests.test_litellm_provider import FakeLiteLLM, patch


async def collect(provider: Any) -> str:
    return "".join([e.text async for e in provider.stream("s", [], []) if isinstance(e, TextDelta)])


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(primary: FakeProvider, fallback: FakeProvider, clock: Clock | None = None):
    changes: list[tuple[str, bool]] = []

    async def on_change(name: str, offline: bool) -> None:
        changes.append((name, offline))

    provider = FallbackProvider(
        primary,
        fallback,
        "cloud",
        "lokal",
        cooldown_s=60,
        clock=clock or Clock(),
        on_change=on_change,
    )
    return provider, changes


async def test_uses_cloud_when_available() -> None:
    primary, local = FakeProvider([TextDelta("Cloud")]), FakeProvider()
    provider, changes = make(primary, local)
    assert await collect(provider) == "Cloud"
    assert local.calls == [] and changes == [] and provider.offline is False


async def test_switches_to_local_when_cloud_unreachable_and_reports_it() -> None:
    primary = FakeProvider(LLMError("kein Internet", unavailable=True))
    local = FakeProvider([TextDelta("Lokal")])
    provider, changes = make(primary, local)
    assert await collect(provider) == "Lokal"
    assert changes == [("lokal", True)] and provider.offline and provider.active == "lokal"


async def test_cooldown_skips_cloud_then_retries_and_switches_back() -> None:
    clock = Clock()
    primary = FakeProvider(LLMError("weg", unavailable=True), [TextDelta("Cloud wieder")])
    local = FakeProvider([TextDelta("Lokal 1")], [TextDelta("Lokal 2")])
    provider, changes = make(primary, local, clock)
    assert await collect(provider) == "Lokal 1"
    clock.now = 30  # Cloud ist noch "down": direkt lokal, kein Timeout-Warten
    assert await collect(provider) == "Lokal 2"
    assert len(primary.calls) == 1
    clock.now = 61  # Abkühlzeit vorbei: Cloud wird wieder versucht
    assert await collect(provider) == "Cloud wieder"
    assert changes == [("lokal", True), ("cloud", False)] and not provider.offline


async def test_config_errors_are_not_masked_by_fallback() -> None:
    primary = FakeProvider(LLMError("Schlüssel abgelehnt", unavailable=False))
    local = FakeProvider([TextDelta("Lokal")])
    provider, changes = make(primary, local)
    with pytest.raises(LLMError, match="Schlüssel"):
        await collect(provider)
    assert local.calls == [] and changes == []


async def test_no_switch_in_the_middle_of_an_answer() -> None:
    class Breaking:
        async def stream(self, system: str, messages: list, tools: list):  # type: ignore[no-untyped-def]
            yield TextDelta("Halb")
            raise LLMError("abgebrochen", unavailable=True)

    provider = FallbackProvider(Breaking(), FakeProvider([TextDelta("Lokal")]), "cloud", "lokal")
    seen: list[str] = []
    with pytest.raises(LLMError):
        async for event in provider.stream("s", [], []):
            seen.append(event.text)  # type: ignore[union-attr]
    assert seen == ["Halb"]


async def test_local_failure_is_reported_when_both_are_down() -> None:
    provider, _ = make(
        FakeProvider(LLMError("Cloud weg", unavailable=True)),
        FakeProvider(LLMError("Ollama läuft nicht", unavailable=True)),
    )
    with pytest.raises(LLMError, match="Ollama"):
        await collect(provider)


# --- Qwen3: Denkblöcke entfernen ---


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["Hallo Welt"], "Hallo Welt"),
        (["<think>überlege</think>Antwort"], "Antwort"),
        (["<think>\nviel\nText\n</think>\n\nJa, klar."], "Ja, klar."),
        (["<thi", "nk>geheim</th", "ink>Sicht", "bar"], "Sichtbar"),
        (["a < b und <think>x</think>c"], "a < b und c"),
        (["Vorher <think>nie zu Ende"], "Vorher "),
        (["x <th"], "x <th"),
    ],
)
def test_think_filter(chunks: list[str], expected: str) -> None:
    f = ThinkFilter()
    assert "".join(f.feed(c) for c in chunks) + f.flush() == expected


# --- Klassifizierung der Fehler ---


@pytest.mark.parametrize(
    ("exc_name", "unavailable"),
    [
        ("APIConnectionError", True),
        ("Timeout", True),
        ("RateLimitError", True),
        ("AuthenticationError", False),
        ("NotFoundError", False),
        ("BadRequestError", False),
    ],
)
def test_error_classification(exc_name: str, unavailable: bool) -> None:
    exc = getattr(FakeLiteLLM, exc_name)("x")
    assert _describe(FakeLiteLLM({}), exc)[1] is unavailable


async def test_litellm_provider_marks_connection_errors_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLiteLLM(FakeLiteLLM.APIConnectionError("dns"))
    patch(monkeypatch, fake)
    provider = LiteLLMProvider("ollama/qwen3:4b", api_base="http://ollama:11434", timeout_s=5)
    with pytest.raises(LLMError) as info:
        await collect(provider)
    assert info.value.unavailable
    assert fake.kwargs["api_base"] == "http://ollama:11434" and fake.kwargs["timeout"] == 5
    assert fake.kwargs["num_retries"] == 0


async def test_local_model_gets_no_think_and_thinking_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    def chunk(text: str) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))]
        )

    fake = FakeLiteLLM([chunk("<think>hmm</think>"), chunk("Ja.")])
    patch(monkeypatch, fake)
    provider = LiteLLMProvider("ollama/qwen3:4b", system_suffix=" /no_think", strip_think=True)
    assert await collect(provider) == "Ja."
    assert fake.kwargs["messages"][0]["content"].endswith("/no_think")


# --- Ende zu Ende: Anzeige des antwortenden Modells ---


def test_provider_state_is_announced_and_switches_visibly(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        learn=False,
        summarize_sessions=False,
        llm_model="anthropic/claude-haiku-5-5",
    )
    app = create_app(settings)
    state = app.state.cat
    provider = FallbackProvider(
        FakeProvider(LLMError("Internet weg", unavailable=True)),
        FakeProvider([TextDelta("Ich bin offline da.")]),
        "anthropic/claude-haiku-5-5",
        "ollama/qwen3:4b",
        on_change=state.set_provider,
    )
    state.responder = build_responder(state, provider)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        with client.websocket_connect("/ws") as ws:
            replay = drain_replay(ws)
            assert replay[-1] == {
                "type": "provider.state",
                "name": "anthropic/claude-haiku-5-5",
                "offline": False,
            }
            ws.send_text(json.dumps({"type": "chat.message", "text": "Hallo"}))
            seen: list[dict[str, Any]] = []
            while not any(e["type"] == "chat.done" for e in seen):
                seen.append(json.loads(ws.receive_text()))
            switch = next(e for e in seen if e["type"] == "provider.state")
            assert switch == {"type": "provider.state", "name": "ollama/qwen3:4b", "offline": True}
            assert "offline da" in "".join(e.get("delta", "") for e in seen)
        with client.websocket_connect("/ws") as ws:  # neue Verbindung sieht den aktuellen Stand
            assert drain_replay(ws)[-1]["offline"] is True


def test_fallback_is_only_built_when_configured(tmp_path: Path) -> None:
    from cat.agent.responder import _build_provider

    base = {"_env_file": None, "static_dir": None, "plugins": "", "data_dir": tmp_path}
    plain = create_app(Settings(**base, responder="echo"))  # type: ignore[arg-type]
    assert not isinstance(_build_provider(plain.state.cat), FallbackProvider)
    with_fallback = create_app(
        Settings(**base, responder="echo", fallback_model="ollama/qwen3:4b")  # type: ignore[arg-type]
    )
    assert isinstance(_build_provider(with_fallback.state.cat), FallbackProvider)
