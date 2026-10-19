import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cat.config import Settings
from cat.dialog import handle_user_text
from cat.intents.fillers import (
    BUILTIN,
    CATEGORIES,
    FillerBank,
    FillerWorkshop,
    category_for,
    valid_phrase,
    workshop_prompt,
)
from cat.state import AppState
from cat.ws.protocol import ChatFiller, ServerEvent
from tests.test_speed import make

# --- Art der Anfrage ---


@pytest.mark.parametrize(
    ("text", "device", "claude", "expected"),
    [
        ("Welche Markisen sind gerade an?", True, False, "lookup"),
        ("Ist das Deckenlicht von Roman an?", True, False, "lookup"),
        ("Mach das Licht aus", True, False, "control"),
        ("Fahr das Rollo auf 30 Prozent", True, False, "control"),
        ("Merk dir, dass ich Hafermilch mag", False, False, "memory"),
        ("Vergiss das wieder", False, False, "memory"),
        ("Wie viele Minuten hat eine Stunde?", False, False, "think"),
        ("Erklär mir die Relativitätstheorie", False, True, "claude"),
    ],
)
def test_category_comes_from_the_words_of_the_request(
    text: str, device: bool, claude: bool, expected: str
) -> None:
    assert category_for(text, device_related=device, claude=claude) == expected


# --- Prüfung neuer Sätze ---


@pytest.mark.parametrize(
    "text",
    [
        "Moment, ich schaue kurz nach.",
        "Einen Augenblick bitte!",
        "Gleich, ich sehe bei {topic} nach.",
        "- Ich überlege kurz.",
        "1. Lass mich kurz nachdenken.",
        '"Warte, ich schaue mal."',
    ],
)
def test_good_sentences_are_accepted(text: str) -> None:
    assert valid_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Moment",  # zu kurz, kein Satzende
        "Okay, das Licht ist aus.",  # behauptet ein Ergebnis
        "Ich habe 3 Geräte geprüft.",  # Zahl
        "Das ist **fertig** gleich.",  # Markdown
        "Ich schaue bei {topic} und {topic} nach.",
        "Ich schaue bei {thema} nach.",
        "Das ist ein sehr langer Satz, der mit viel zu vielen Worten nichts Kurzes mehr sagt.",
        "Siehe https://example.com bitte.",
        "Ergebnis folgt gleich.",
        "Hm, gleich nachgedacht.",  # Vergangenheitsform klingt schief
        "Das Wetter ist schön heute abend.",  # sagt nichts über Warten
    ],
)
def test_bad_sentences_are_rejected(text: str) -> None:
    assert valid_phrase(text) is None


# --- Liste ---


def test_builtin_sentences_exist_for_every_kind_and_pass_their_own_check() -> None:
    assert set(BUILTIN) == set(CATEGORIES)
    for texts in BUILTIN.values():
        assert all(valid_phrase(t) for t in texts)


def test_pick_rotates_and_uses_topic_sentences_only_with_a_topic(tmp_path: Path) -> None:
    bank = FillerBank(tmp_path / "f.json")
    seen = {bank.pick("lookup") for _ in range(12)}
    assert len(seen) >= 4 and all("{topic}" not in s and s for s in seen if s)
    with_topic = {bank.pick("lookup", "Markisen") for _ in range(40)}
    assert any("Markisen" in (s or "") for s in with_topic)
    assert all("{" not in (s or "") for s in with_topic)
    first = bank.pick("think")
    assert bank.pick("think") != first  # nie zweimal derselbe hintereinander


def test_disabled_bank_says_nothing(tmp_path: Path) -> None:
    assert FillerBank(tmp_path / "f.json", enabled=False).pick("think") is None


def test_use_is_counted_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    bank = FillerBank(path)
    for _ in range(3):
        bank.pick("memory")
    again = FillerBank(path)
    assert sum(r["uses"] for r in again.listing() if r["category"] == "memory") == 3


def test_removed_sentences_stay_gone_even_builtin_ones(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    bank = FillerBank(path)
    assert bank.remove("Hm, einen Moment.")
    assert not bank.remove("Hm, einen Moment.")
    reloaded = FillerBank(path)
    assert "Hm, einen Moment." not in [r["text"] for r in reloaded.listing()]
    assert reloaded.add_generated("think", ["Hm, einen Moment."]) == []  # kommt nicht wieder


def test_generated_sentences_are_checked_and_deduplicated(tmp_path: Path) -> None:
    bank = FillerBank(tmp_path / "f.json")
    added = bank.add_generated(
        "think",
        [
            "Lass mich das kurz durchdenken.",
            "Lass mich das kurz durchdenken.",  # doppelt
            "Moment, ich überlege kurz.",  # gibt es schon (Vorgabe: ähnlich, aber nicht gleich)
            "Das Licht ist an.",  # Ergebnis
            "Zu kurz",
        ],
    )
    assert "Lass mich das kurz durchdenken." in added and len(added) <= 2
    rows = {r["text"]: r for r in bank.listing()}
    assert rows["Lass mich das kurz durchdenken."]["source"] == "generated"


def test_needs_more_points_at_the_busiest_short_category(tmp_path: Path) -> None:
    bank = FillerBank(tmp_path / "f.json")
    for _ in range(30):
        bank.pick("claude")
    assert bank.needs_more() == "claude"


# --- Werkstatt ---


async def test_workshop_adds_sentences_only_when_idle_and_within_the_daily_limit(
    tmp_path: Path,
) -> None:
    bank = FillerBank(tmp_path / "f.json")
    prompts: list[str] = []

    async def generate(prompt: str) -> str:
        prompts.append(prompt)
        return "Ich sehe kurz nach, bleib dran.\n2. Gleich weiß ich mehr!\nKaputt"

    busy = {"v": True}
    shop = FillerWorkshop(bank, generate, lambda: not busy["v"], per_day=2)
    assert await shop.run_once() == [] and prompts == []  # Cat ist beschäftigt
    busy["v"] = False
    assert await shop.run_once()
    await shop.run_once()
    assert await shop.run_once() == [] and len(prompts) == 2  # Tageslimit
    assert "Ich sehe kurz nach, bleib dran." in [r["text"] for r in bank.listing()]


async def test_workshop_survives_a_failing_model(tmp_path: Path) -> None:
    async def generate(_: str) -> str:
        raise RuntimeError("Ollama aus")

    shop = FillerWorkshop(FillerBank(tmp_path / "f.json"), generate, lambda: True)
    assert await shop.run_once() == []


def test_workshop_prompt_asks_for_short_non_committal_sentences() -> None:
    prompt = workshop_prompt("lookup", ["Moment, ich schaue kurz nach."])
    assert "Höchstens 8 Wörter" in prompt and "kein Ergebnis" in prompt


# --- im Dialog ---


class SlowResponder:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    async def reply(self, history, spoken=False, room=None) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        await asyncio.sleep(self.seconds)
        yield "Fertig."


async def run_dialog(
    tmp_path: Path, seconds: float, text: str = "Welche Rollos sind offen?"
) -> tuple[list[ServerEvent], list[str]]:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        data_dir=tmp_path,
        plugins="",
        learn=False,
        filler_delay_s=0.05,
        filler_repeat_s=0.2,
    )
    state = AppState(settings)
    service, _ = make(tmp_path)
    state.devices = service
    state.responder = SlowResponder(seconds)
    events: list[ServerEvent] = []

    async def emit(event: ServerEvent) -> None:
        events.append(event)

    state.emit = emit  # type: ignore[method-assign]
    spoken: list[str] = []

    async def on_filler(text: str) -> None:
        spoken.append(text)

    await handle_user_text(state, text, spoken=True, on_filler=on_filler)
    return events, spoken


async def test_a_slow_answer_gets_a_matching_filler_in_chat_and_voice(tmp_path: Path) -> None:
    events, spoken = await run_dialog(tmp_path, 0.12)
    shown = [e.text for e in events if isinstance(e, ChatFiller)]
    assert shown and shown == spoken
    assert any(w in shown[0] for w in ("nach", "prüfe", "Rollo"))  # nachsehen, nicht schalten


async def test_a_fast_answer_gets_no_filler(tmp_path: Path) -> None:
    events, spoken = await run_dialog(tmp_path, 0.0)
    assert not [e for e in events if isinstance(e, ChatFiller)] and spoken == []


async def test_a_very_slow_answer_gets_a_few_different_fillers(tmp_path: Path) -> None:
    _, spoken = await run_dialog(tmp_path, 0.7)
    assert 2 <= len(spoken) <= 3 and len(set(spoken)) == len(spoken)
