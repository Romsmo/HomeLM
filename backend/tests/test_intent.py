"""Tun oder nur lesen? (intents/text.py: intent_kind, erzwungen in agent/loop.py)"""

from pathlib import Path

import pytest

from cat.devices.service import RawState
from cat.intents.text import intent_kind
from cat.llm.base import TextDelta, ToolCall
from tests.fakes import FakeProvider
from tests.test_speed import agent_for, make, run


@pytest.mark.parametrize(
    "text",
    [
        "Schließe die Markisen",
        "Mach das Licht an",
        "Licht an",
        "Rollo runter",
        "Fahr das Rollo auf 30 Prozent",
        "Kannst du die Markisen schließen?",
        "Könntest du bitte das Licht ausmachen",
        "Mach das Licht an?",  # die Spracherkennung hängt gern ein Fragezeichen an
        "Mach das Licht an und sag mir Bescheid",
        "Stell Romans Rollo auf 50",
    ],
)
def test_these_are_orders(text: str) -> None:
    assert intent_kind(text) == "act"


@pytest.mark.parametrize(
    "text",
    [
        "Ist das Rollo zu?",
        "Sind die Markisen offen",
        "Welche Rollos sind zu?",
        "Ist das Licht an?",
        "Sag mir, ob das Licht an ist",
        "Kannst du mir sagen, wie das Rollo steht?",
        "Zeig mir die offenen Rollos",
        "Zähle mir bitte auf, welche Rollos offen sind",
        "Ob die Markisen zu sind?",
        "Wie spät ist es",  # eine Frage ohne Gerät: lesen, nicht schalten
    ],
)
def test_these_only_want_to_read(text: str) -> None:
    assert intent_kind(text) == "read"


@pytest.mark.parametrize(
    "text",
    [
        "Das Rollo ist zu",
        "Die Markisen sind noch auf",
        "Ich hab nie gesagt, dass du das Licht anmachen sollst",
        "Warum hast du das Rollo geöffnet",
        "Roman",
        "",
    ],
)
def test_these_are_neither(text: str) -> None:
    assert intent_kind(text) == "none"


async def test_a_question_never_switches_anything_it_reads_instead(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("100")})
    # Das Modell greift fälschlich zu set_state, obwohl nur gefragt wurde.
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "up"})]
    )
    out, ctx = await run(agent_for(service, provider), "Ist das Rollo zu?", True)
    assert backend.sent == []  # nichts geschaltet
    assert "Romans Rollo" in out  # und trotzdem geantwortet: mit dem Zustand
    assert ctx.trace[-1].tool == "set_state" and ctx.trace[-1].ok
    assert ctx.trace[-1].result.startswith("Nur gelesen, nichts geschaltet")


async def test_a_statement_never_switches_and_ends_honestly(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    call = ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "down"})
    provider = FakeProvider([call], [call])  # das Modell bleibt beim Schalten
    out, _ = await run(agent_for(service, provider), "Das Rollo ist zu", True)
    assert backend.sent == [] and "nichts geschaltet" in out and "Nachgesehen" in out


async def test_other_messages_get_a_look_and_then_an_answer(tmp_path: Path) -> None:
    """Sonstiges: nicht schalten, sondern nachsehen und mit dem Gefundenen antworten."""
    service, backend = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("100")})
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "down"})],
        [ToolCall("c2", "get_state", {"device": "Romans Rollo"})],
    )
    out, ctx = await run(agent_for(service, provider), "Das Rollo ist zu", True)
    assert backend.sent == [] and "Romans Rollo" in out and "nicht als Schaltbefehl" not in out
    hint = provider.calls[1]["messages"][-1]["content"]
    assert "get_state" in hint and "ehrlich" in hint  # das Modell wurde zum Nachsehen geschickt
    assert [t.tool for t in ctx.trace] == ["set_state", "get_state"]


async def test_other_messages_the_model_cannot_solve_get_an_honest_answer(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "down"})],
        [TextDelta("Das kann ich nicht klären, dazu habe ich nichts gefunden.")],
        [TextDelta("Das kann ich nicht klären, dazu habe ich nichts gefunden.")],
    )
    out, _ = await run(agent_for(service, provider), "Das Rollo ist zu", True)
    assert backend.sent == [] and "nicht klären" in out


async def test_an_unchecked_claim_after_a_blocked_switch_is_not_shown(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "down"})],
        [TextDelta("Okay, das Rollo ist jetzt zu.")],  # ohne nachgesehen zu haben
        [TextDelta("Okay, das Rollo ist jetzt zu.")],
    )
    out, _ = await run(agent_for(service, provider), "Das Rollo ist zu", True)
    assert backend.sent == [] and "jetzt zu" not in out


async def test_a_polite_request_is_carried_out(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "down"})]
    )
    out, _ = await run(agent_for(service, provider), "Kannst du das Rollo bitte schließen?", True)
    assert backend.sent and backend.sent[0][1] == "down"
    assert "Romans Rollo" in out


async def test_an_order_is_carried_out(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Deckenlicht Roman", "command": "on"})]
    )
    await run(agent_for(service, provider), "Mach das Licht an", True)
    assert backend.sent == [("roman", "on")]
