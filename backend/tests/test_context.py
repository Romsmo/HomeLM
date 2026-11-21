"""Folgeanfragen aus dem Kontext der letzten Schaltung (Chat vom 21.11.2026, 11:12 bis 11:15)."""

import asyncio
from pathlib import Path

import pytest

from cat.agent.tools import ToolError
from cat.audit import AuditLog
from cat.devices.tools import personal_refs
from cat.intents.fillers import FillerBank
from cat.intents.lexicon import Lexicon
from cat.intents.teach import TeachService
from cat.memory.service import MemoryService
from tests.test_markisen import Setup, awning_items


def teach_for(s: Setup, tmp_path: Path) -> TeachService:
    lexicon = Lexicon(tmp_path / "lexicon.json")
    s.service.lexicon = lexicon
    return TeachService(
        s.service,
        lexicon,
        FillerBank(tmp_path / "fillers.json"),
        MemoryService(tmp_path / "memory", tmp_path / "sessions"),
        AuditLog(tmp_path / "teach.jsonl"),
    )


def sent_to(s: Setup, command: str) -> set[str]:
    return {i for i, c in s.backend.sent if c == command}


NICE = {f"Markise_{x}_Terrasse_Control" for x in ("Nord", "Ost", "West")}


async def test_the_chat_from_the_user_all_awnings_open_again(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markisen", "command": "down"}, s.ctx("Schließe die Markisen"))
    assert sent_to(s, "down") == NICE
    s.backend.sent.clear()

    # 11:13 "Mach sie doch wieder auf": früher fuhr nur Markise West hoch
    reply = await teach.intercept("Mach sie doch wieder auf")
    assert sent_to(s, "up") == NICE
    assert reply == "Okay, Markise Nord, Ost und West fahren hoch."

    # 11:13 "Ich meinte mach alle auf"
    s.backend.sent.clear()
    reply = await teach.intercept("Ich meinte mach alle auf")
    assert sent_to(s, "up") == NICE


async def test_x_and_y_too_uses_the_last_command(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markise West", "command": "up"}, s.ctx("Mach Markise West auf"))
    s.backend.sent.clear()

    # 11:14 "Ost und Nord auch!": früher "nicht als Schaltbefehl verstanden"
    reply = await teach.intercept("Ost und Nord auch!")
    assert sent_to(s, "up") == {"Markise_Ost_Terrasse_Control", "Markise_Nord_Terrasse_Control"}
    assert reply == "Okay, Markise Ost und Nord fahren hoch."


@pytest.mark.parametrize(
    "text", ["Markise Ost und Markise Nord auch", "Die Markise Ost auch bitte", "Ost genauso"]
)
async def test_ways_to_say_too(tmp_path: Path, text: str) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markise West", "command": "down"}, s.ctx("Markise West zu"))
    s.backend.sent.clear()
    assert await teach.intercept(text) is not None
    assert sent_to(s, "down") <= NICE and sent_to(s, "down")
    assert (
        "Markise_West_Terrasse_Control" not in {i for i, _ in s.backend.sent} or "Ost" not in text
    )


async def test_all_after_one_device_means_the_whole_kind(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markise Nord", "command": "down"}, s.ctx("Markise Nord zu"))
    s.backend.sent.clear()
    await teach.intercept("Mach alle auf")
    assert sent_to(s, "up") == NICE
    assert not any("Rollo" in i for i, _ in s.backend.sent)  # nur gleiche Sorte im Raum


async def test_again_without_a_direction_reverses_the_last_command(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markisen", "command": "down"}, s.ctx("Schließe die Markisen"))
    s.backend.sent.clear()
    await teach.intercept("Mach sie wieder")
    assert sent_to(s, "up") == NICE


async def test_the_context_expires(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    s.service.context_ttl_s = 0.05
    await s.set_state({"device": "Markisen", "command": "down"}, s.ctx("Schließe die Markisen"))
    await asyncio.sleep(0.1)
    s.backend.sent.clear()
    assert await teach.intercept("Mach sie wieder auf") is None  # kein Kontext mehr: Modell
    assert s.backend.sent == [] and s.service.last_device is None
    assert s.service.last_group() == [] and s.service.recent == []


async def test_follow_ups_do_not_hijack_normal_commands(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markisen", "command": "down"}, s.ctx("Schließe die Markisen"))
    s.backend.sent.clear()
    for text in (
        "Mach Romans Rollo auf",  # nennt ein Gerät: das Modell
        "Ist es warm?",
        "Wie spät ist es",
        "Auch das noch",  # "auch", aber kein Gerät dahinter
    ):
        assert await teach.intercept(text) is None, text
    assert s.backend.sent == []


async def test_an_unknown_name_with_too_is_not_guessed(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.set_state({"device": "Markise West", "command": "up"}, s.ctx("Markise West auf"))
    s.backend.sent.clear()
    assert await teach.intercept("Süd auch") is None
    assert s.backend.sent == []


# --- Der Nutzer: "mein Rollo" ---


def test_personal_refs() -> None:
    assert personal_refs("mein Rollo", "Roman") == ["Rollo Roman", "mein Rollo"]
    assert personal_refs("Meine Lampe", "Marius") == ["Lampe Marius", "Meine Lampe"]
    assert personal_refs("mein Rollo", "") == ["mein Rollo"]  # Sprecher unbekannt
    assert personal_refs("Romans Rollo", "Roman") == ["Romans Rollo"]


async def test_my_shutter_means_the_one_of_the_speaker(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    ctx = s.ctx("Mach mein Rollo auf")
    ctx.speaker = "Roman"
    await s.set_state({"device": "mein Rollo", "command": "up"}, ctx)
    assert s.backend.sent == [("Rollo_Roman_Control", "up")]

    s.backend.sent.clear()
    other = s.ctx("Mach mein Rollo auf")
    other.speaker = "Marius"
    await s.set_state({"device": "mein Rollo", "command": "up"}, other)
    assert s.backend.sent == [("Rollo_Marius_Control", "up")]


async def test_my_shutter_without_a_known_speaker_asks(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    with pytest.raises(ToolError):
        await s.set_state({"device": "mein Rollo", "command": "up"}, s.ctx("Mach mein Rollo auf"))
    assert s.backend.sent == []
