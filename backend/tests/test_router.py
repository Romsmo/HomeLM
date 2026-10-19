import json
from pathlib import Path
from typing import Any

import pytest

from cat.agent.responder import build_responder
from cat.agent.router import RoutedResponder
from cat.claude.bridge import ClaudeResult
from cat.claude.budget import ClaudeBudget
from cat.claude.text import FOOTER_PREFIX
from cat.config import Settings
from cat.llm.base import LLMError, TextDelta, ToolCall
from cat.state import AppState
from cat.ws.protocol import ChatMessage, ProviderState, StageShow
from tests.fakes import FakeProvider


class FakeClaude:
    model = "sonnet"

    def __init__(self, *results: ClaudeResult) -> None:
        self._results = list(results)
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def ask(self, prompt: str, system: str) -> ClaudeResult:
        self.prompts.append(prompt)
        self.systems.append(system)
        return self._results.pop(0)


def ok(text: str) -> ClaudeResult:
    return ClaudeResult(True, text=text, duration_s=1.0)


def fail(kind: str, message: str = "kaputt") -> ClaudeResult:
    return ClaudeResult(False, kind=kind, message=message)


class Env:
    def __init__(
        self, tmp_path: Path, provider: FakeProvider, claude: FakeClaude | None, limit: int
    ):
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            data_dir=tmp_path,
            local_model="qwen-test",
            plugins="",
            sandbox=False,
        )
        self.state = AppState(settings)
        self.events: list[Any] = []

        async def collect(event: Any) -> None:
            self.events.append(event)

        self.state.emit = collect  # type: ignore[method-assign]
        self.claude = claude
        self.budget = ClaudeBudget(tmp_path / "usage.json", limit)
        pair = (claude, self.budget) if claude else None
        self.responder = build_responder(self.state, provider=provider, claude=pair)  # type: ignore[arg-type]
        assert isinstance(self.responder, RoutedResponder)
        self.provider = provider

    async def ask(self, text: str, spoken: bool = False) -> str:
        history = [ChatMessage(id="1", role="user", text=text, ts=0.0)]
        return "".join([d async for d in self.responder.reply(history, spoken=spoken)])

    def audit_lines(self) -> list[dict[str, Any]]:
        path = self.state.settings.audit_file
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def make(tmp_path: Path):  # type: ignore[no-untyped-def]
    def factory(*steps: Any, claude: FakeClaude | None = None, limit: int = 10) -> Env:
        return Env(tmp_path, FakeProvider(*steps), claude, limit)

    return factory


async def test_local_answer_never_asks_claude(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude()
    env = make([TextDelta("Es ist 12 Uhr.")], claude=claude)
    assert await env.ask("Wie spät ist es?") == "Es ist 12 Uhr."
    assert claude.prompts == [] and env.budget.used_today == 0


async def test_local_prompt_is_static_and_context_goes_to_user_message(make) -> None:  # type: ignore[no-untyped-def]
    env = make([TextDelta("ok")], claude=FakeClaude())
    await env.ask("Hallo")
    call = env.provider.calls[0]
    assert "Aktuelle Zeit" not in call["system"]  # bleibt gleich, Ollama behält den Anfang
    assert call["messages"][-1]["content"].startswith("[Aktuelle Zeit:")
    assert call["messages"][-1]["content"].endswith("Hallo")


async def test_local_gets_a_small_toolset_with_ask_claude(make) -> None:  # type: ignore[no-untyped-def]
    env = make([TextDelta("ok")], claude=FakeClaude())
    await env.ask("Hallo")
    names = env.provider.calls[0]["tool_names"]
    assert "ask_claude" in names and "memory_search" in names
    assert "set_state" not in names  # Geräte kommen als Kurzzeile (local_compact), nicht als Schema
    assert "show_html" not in names and "propose_plugin" not in names


async def test_without_claude_there_is_no_ask_claude_tool(make) -> None:  # type: ignore[no-untyped-def]
    env = make([TextDelta("ok")])
    await env.ask("Hallo")
    assert "ask_claude" not in env.provider.calls[0]["tool_names"]
    assert "Claude" not in env.provider.calls[0]["system"]


async def test_model_asks_claude_and_answer_is_streamed_with_footer(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Hier ist ein Gedicht."))
    env = make([ToolCall("c1", "ask_claude", {"question": "Gedicht über Rex"})], claude=claude)
    text = await env.ask("Schreib ein Gedicht über Rex")
    assert text == "Hier ist ein Gedicht." + FOOTER_PREFIX
    assert "Gedicht über Rex" in claude.prompts[0]  # Hinweis der lokalen KI
    assert "Schreib ein Gedicht über Rex" in claude.prompts[0]
    assert env.budget.used_today == 1
    (entry,) = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert entry["params"]["reason"] == "model" and entry["ok"] is True


async def test_provider_badge_switches_to_claude_and_back(make) -> None:  # type: ignore[no-untyped-def]
    env = make([ToolCall("c1", "ask_claude", {"question": "q"})], claude=FakeClaude(ok("A")))
    await env.ask("Schwere Frage")
    states = [e for e in env.events if isinstance(e, ProviderState)]
    assert [s.name for s in states] == ["claude/sonnet", "qwen-test"]


async def test_spoken_answer_has_no_footer_and_asks_for_short_text(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Kurz."))
    env = make([ToolCall("c1", "ask_claude", {"question": "q"})], claude=claude)
    assert await env.ask("Schwere Frage", spoken=True) == "Kurz."
    assert "laut vorgelesen" in claude.prompts[0]


async def test_explicit_request_skips_the_local_model(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Von Claude."))
    env = make(claude=claude)
    text = await env.ask("Frag mal Claude, warum der Himmel blau ist")
    assert text.startswith("Von Claude.")
    assert env.provider.calls == []
    (entry,) = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert entry["params"]["reason"] == "explicit"


async def test_local_failure_before_output_escalates(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Claude springt ein."))
    env = make(LLMError("Ollama aus", unavailable=True), claude=claude)
    assert (await env.ask("Hallo")).startswith("Claude springt ein.")
    (entry,) = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert entry["params"]["reason"] == "failed"


async def test_local_failure_without_claude_reports_error(make) -> None:  # type: ignore[no-untyped-def]
    env = make(LLMError("Ollama aus", unavailable=True))
    assert "Ollama aus" in await env.ask("Hallo")


async def test_too_many_steps_escalates_instead_of_giving_up(make) -> None:  # type: ignore[no-untyped-def]
    loop_call = [ToolCall("c", "list_devices", {})]
    claude = FakeClaude(ok("Gelöst."))
    env = make(*([loop_call] * 4), claude=claude)
    text = await env.ask("Mach etwas Kompliziertes")
    assert text.startswith("Gelöst.") and "zu viele" not in text


async def test_empty_local_answer_escalates(make) -> None:  # type: ignore[no-untyped-def]
    env = make([], claude=FakeClaude(ok("Antwort von Claude")))
    assert (await env.ask("Hm?")).startswith("Antwort von Claude")


async def test_empty_local_answer_without_claude_is_honest(make) -> None:  # type: ignore[no-untyped-def]
    env = make([])
    assert "keine verlässliche Antwort" in await env.ask("Hm?")


async def test_claude_error_is_explained_and_limit_blocks_followups(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(fail("limit", "Abo-Limit erreicht"))
    env = make(
        [ToolCall("c1", "ask_claude", {"question": "q"})],
        [ToolCall("c2", "ask_claude", {"question": "q"})],
        claude=claude,
    )
    first = await env.ask("Schwere Frage")
    assert "Claude" in first and "Abo-Limit erreicht" in first
    second = await env.ask("Noch eine schwere Frage")
    assert "Abo-Limit" in second and len(claude.prompts) == 1  # nicht noch einmal versucht
    entries = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert len(entries) == 1 and entries[0]["ok"] is False


async def test_daily_limit_stops_escalation(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Eins"))
    env = make(
        [ToolCall("c1", "ask_claude", {"question": "q"})],
        [ToolCall("c2", "ask_claude", {"question": "q"})],
        claude=claude,
        limit=1,
    )
    assert (await env.ask("Frage 1")).startswith("Eins")
    assert "Tageslimit" in await env.ask("Frage 2")
    assert len(claude.prompts) == 1


async def test_html_from_claude_goes_to_stage_not_chat(make) -> None:  # type: ignore[no-untyped-def]
    html = "Bitte:\n```html\n<!-- Titel: Uhr -->\n<svg viewBox='0 0 10 10'></svg>\n```"
    env = make([ToolCall("c1", "ask_claude", {"question": "Uhr"})], claude=FakeClaude(ok(html)))
    text = await env.ask("Zeig mir eine Uhr")
    assert "```" not in text and text.startswith("Bitte:")
    shows = [e for e in env.events if isinstance(e, StageShow)]
    assert len(shows) == 1 and shows[0].item.title == "Uhr"


async def test_claude_prompt_includes_memory_notes(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Gut."))
    env = make([ToolCall("c1", "ask_claude", {"question": "q"})], claude=claude)
    env.state.memory.remember("Hund", "Der Hund heißt Rex und mag Käse.", "haushalt")
    await env.ask("Was mag mein Hund?")
    assert "Rex" in claude.prompts[0]
    assert "Gedächtnis" in claude.systems[0]


async def test_refusal_from_local_model_is_replaced_by_claude(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Hier die Uhr."))
    env = make([TextDelta("Das kann ich leider nicht erstellen.")], claude=claude)
    text = await env.ask("Wie funktioniert ein Quantencomputer in Bildern?")
    assert text.startswith("Hier die Uhr.") and "kann ich leider nicht" not in text
    (entry,) = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert entry["params"]["reason"] == "refused"


async def test_long_refusal_is_caught_before_it_is_shown(make) -> None:  # type: ignore[no-untyped-def]
    refusal = "Das kann ich leider nicht. " + "Ich erkläre dir gern, warum das so ist. " * 8
    claude = FakeClaude(ok("Claude weiß es."))
    env = make([TextDelta(refusal[:100]), TextDelta(refusal[100:])], claude=claude)
    text = await env.ask("Eine Frage ohne Schlüsselwort")
    assert text.startswith("Claude weiß es.") and "leider nicht" not in text


async def test_normal_long_answer_streams_through_untouched(make) -> None:  # type: ignore[no-untyped-def]
    answer = "Ein Wort folgt dem anderen und alles ist in bester Ordnung. " * 6
    claude = FakeClaude()
    env = make([TextDelta(answer[:150]), TextDelta(answer[150:])], claude=claude)
    assert await env.ask("Erzähl mir etwas") == answer
    assert claude.prompts == []


async def test_refusal_stands_when_claude_is_blocked(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude()
    env = make([TextDelta("Das kann ich leider nicht.")], claude=claude, limit=0)
    assert await env.ask("Was ist los?") == "Das kann ich leider nicht."
    assert claude.prompts == []


async def test_tasks_the_local_model_cannot_do_skip_it_entirely(make) -> None:  # type: ignore[no-untyped-def]
    claude = FakeClaude(ok("Hier ist deine Uhr."))
    env = make(claude=claude)
    text = await env.ask("Zeig mir eine animierte Uhr")
    assert text.startswith("Hier ist deine Uhr.") and env.provider.calls == []
    (entry,) = [e for e in env.audit_lines() if e["tool"] == "claude_escalation"]
    assert entry["params"]["reason"] == "task"


class WarmProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.warmed: list[tuple[str, list[str]]] = []

    async def warm(self, system: str, tools: list[Any]) -> None:
        self.warmed.append((system, [t["function"]["name"] for t in tools]))


async def test_warm_up_runs_once_while_the_model_is_hot(tmp_path: Path) -> None:
    provider = WarmProvider()
    env = Env(tmp_path, provider, FakeClaude(), 10)
    await env.responder.warm()  # type: ignore[union-attr]
    await env.responder.warm()  # type: ignore[union-attr]
    assert len(provider.warmed) == 1
    system, names = provider.warmed[0]
    assert "Du bist Cat" in system and "ask_claude" in names
    await env.responder.warm(idle_s=0.0)  # type: ignore[union-attr]
    assert len(provider.warmed) == 2
