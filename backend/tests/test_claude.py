import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from cat.claude.bridge import ClaudeBridge
from cat.claude.budget import ClaudeBudget
from cat.claude.text import (
    FOOTER_PREFIX,
    build_prompt,
    chunk,
    is_explicit_request,
    looks_like_refusal,
    needs_claude,
    split_html,
    strip_footer,
)
from cat.ws.protocol import ChatMessage


def msg(role: str, text: str) -> ChatMessage:
    return ChatMessage(id=text[:4], role=role, text=text, ts=0.0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "text",
    [
        "Frag mal Claude, wie das geht",
        "frage bitte Claude danach",
        "Lass Claude das beantworten",
        "Claude soll das erklären",
        "kannst du das mit Claude klären?",
    ],
)
def test_explicit_requests(text: str) -> None:
    assert is_explicit_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Schalte das Licht an",
        "Merk dir, dass ich Claude Code nutze",
        "Wie warm ist es draußen?",
        "Wer ist Claude Monet?",
    ],
)
def test_normal_requests_stay_local(text: str) -> None:
    assert not is_explicit_request(text)


def test_split_html_extracts_blocks_and_title() -> None:
    text = "Hier die Uhr:\n```html\n<!-- Titel: Uhr -->\n<svg></svg>\n```\nViel Spaß."
    clean, blocks = split_html(text)
    assert clean == "Hier die Uhr:\n\nViel Spaß."
    assert blocks == [("Uhr", "<!-- Titel: Uhr -->\n<svg></svg>")]


def test_split_html_without_title_and_unclosed_block() -> None:
    _, blocks = split_html("```html\n<p>x</p>\n```")
    assert blocks[0][0] == "Grafik von Claude"
    clean, blocks = split_html("Text\n```html\n<p>abgeschnitten")
    assert blocks == [] and "unvollständig" in clean and "abgeschnitten" not in clean


def test_chunk_roundtrips() -> None:
    text = "Das ist ein längerer Satz mit vielen Wörtern, der zerlegt werden soll. " * 5
    parts = chunk(text, 40)
    assert "".join(parts) == text and len(parts) > 3


def test_build_prompt_has_history_memory_note_and_strips_footer() -> None:
    history = [
        msg("user", "Wer bin ich?"),
        msg("assistant", "Du bist Robin." + FOOTER_PREFIX),
        msg("user", "Schreibe ein Gedicht über unseren Hund"),
    ]
    prompt = build_prompt(
        history,
        "Gedicht über den Hund",
        "Erinnerungen: Hund heißt Rex",
        spoken=True,
        now=datetime(2026, 10, 17, 12, 0).astimezone(),
    )
    assert "Nutzer: Wer bin ich?" in prompt and "Cat: Du bist Robin." in prompt
    assert "Claude" not in prompt.split("Bisheriges Gespräch")[1].split("Aktuelle Nachricht")[0]
    assert "Aktuelle Nachricht des Nutzers:\nSchreibe ein Gedicht" in prompt
    assert "Hund heißt Rex" in prompt and "Gedicht über den Hund" in prompt
    assert "laut vorgelesen" in prompt


def test_strip_footer() -> None:
    assert strip_footer("Antwort" + FOOTER_PREFIX) == "Antwort"


# --- Budget ---


def test_budget_counts_per_day_and_blocks(tmp_path: Path) -> None:
    day = ["2026-10-17"]
    now = [0.0]
    budget = ClaudeBudget(tmp_path / "u.json", 2, today=lambda: day[0], clock=lambda: now[0])
    assert budget.blocked() is None
    budget.record()
    budget.record()
    assert budget.used_today == 2 and "Tageslimit" in (budget.blocked() or "")
    day[0] = "2026-10-18"
    assert budget.blocked() is None and budget.used_today == 0
    budget.block(60, "Abo-Limit")
    assert budget.blocked() == "Abo-Limit"
    now[0] = 61.0
    assert budget.blocked() is None


def test_budget_survives_restart_and_zero_disables(tmp_path: Path) -> None:
    ClaudeBudget(tmp_path / "u.json", 5, today=lambda: "d").record()
    assert ClaudeBudget(tmp_path / "u.json", 5, today=lambda: "d").used_today == 1
    assert ClaudeBudget(tmp_path / "x.json", 0).blocked()


def test_budget_ignores_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "u.json").write_text("{kaputt", encoding="utf-8")
    assert ClaudeBudget(tmp_path / "u.json", 3).used_today == 0


# --- Brücke ---


def bridge(handler: Any) -> ClaudeBridge:
    return ClaudeBridge(
        "http://claude-bridge:8099", "sonnet", 5, transport=httpx.MockTransport(handler)
    )


async def test_bridge_success_sends_prompt_and_model() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content), path=request.url.path)
        return httpx.Response(
            200, json={"ok": True, "text": " Antwort ", "cost_usd": 0.01, "turns": 2}
        )

    result = await bridge(handler).ask("Frage", "System")
    assert result.ok and result.text == "Antwort" and result.turns == 2
    assert seen["path"] == "/ask" and seen["prompt"] == "Frage" and seen["model"] == "sonnet"
    assert seen["system"] == "System" and seen["memory"] is True


async def test_bridge_reports_error_kinds() -> None:
    def limit(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "kind": "limit", "message": "Limit"})

    result = await bridge(limit).ask("q", "s")
    assert not result.ok and result.kind == "limit" and result.message == "Limit"

    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    assert (await bridge(down).ask("q", "s")).kind == "unreachable"

    def slow(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    assert (await bridge(slow).ask("q", "s")).kind == "timeout"

    def garbage(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    assert (await bridge(garbage).ask("q", "s")).kind == "error"


async def test_bridge_empty_text_is_an_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "text": "  "})

    assert not (await bridge(handler).ask("q", "s")).ok


@pytest.mark.parametrize(
    "text",
    [
        "Zeig mir eine animierte Uhr",
        "Erstell eine HTML Seite für das Wetter",
        "Zeichne einen Hund",
        "Schreib mir ein Python Skript für Backups",
        "Programmiere einen Wecker",
    ],
)
def test_tasks_the_local_model_cannot_do_go_straight_to_claude(text: str) -> None:
    assert needs_claude(text)


@pytest.mark.parametrize(
    "text",
    ["Mach das Licht an", "Wie wird das Wetter", "Schreib mir ein Gedicht", "Spiel Musik"],
)
def test_ordinary_requests_do_not_trigger_the_shortcut(text: str) -> None:
    assert not needs_claude(text)


@pytest.mark.parametrize(
    "answer",
    [
        "Ihr habt keine Animationen auf der Stage. Eine animierte Uhr kann ich nicht erstellen.",
        "Das kann ich leider nicht.",
        "Ich weiß es leider nicht genau.",
        "Ich kann dir leider keine Auskunft geben.",
        "Ich bin mir nicht sicher, ob das stimmt.",
    ],
)
def test_refusals_are_recognized(answer: str) -> None:
    assert looks_like_refusal(answer)


@pytest.mark.parametrize(
    "answer",
    [
        "Es gibt heute keine Termine.",
        "Morgens trinkst du Kaffee mit Hafermilch.",
        "Das Licht ist an.",
        "Eine Stunde hat 60 Minuten.",
    ],
)
def test_normal_answers_are_not_refusals(answer: str) -> None:
    assert not looks_like_refusal(answer)
