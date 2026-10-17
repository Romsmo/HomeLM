import json
from pathlib import Path
from typing import Any

import pytest

from cat.agent.loop import Agent
from cat.agent.prompt import LOCAL_BRIEFS, LOCAL_TOOLS, build_local_prompt
from cat.agent.responder import build_responder
from cat.agent.tools import Tool, ToolContext, ToolRegistry
from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import parse_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.devices.tools import build_device_tools
from cat.intents.learned import Learner
from cat.llm.base import TextDelta, ToolCall
from cat.stage.store import StageStore
from cat.state import AppState
from cat.ws.protocol import ServerEvent
from tests.fakes import FakeProvider

YAML = """
devices:
  - {id: roman, backend: openhab, item: R, name: Deckenlicht Roman, room: Romans Zimmer, type: light}
  - {id: rollo, backend: openhab, item: RO, name: Romans Rollo, room: Romans Zimmer, type: shutter}
  - {id: rollo2, backend: openhab, item: RO2, name: Rollo Roman Control, room: Romans Zimmer, type: shutter}
"""


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False

    async def read(self, spec: DeviceSpec) -> RawState:
        return RawState({"RO": None, "RO2": "0"}.get(spec.item, "OFF"))

    async def send(self, spec: DeviceSpec, command: str) -> None:
        if self.fail:
            from cat.devices.commands import DeviceError

            raise DeviceError("openHAB ist nicht erreichbar, nichts gesendet.")
        self.sent.append((spec.id, command))


def make(tmp_path: Path) -> tuple[DeviceService, Backend]:
    async def emit(_: ServerEvent) -> None: ...

    service = DeviceService(
        parse_allowlist(YAML),
        "full",
        emit,
        AuditLog(tmp_path / "a.jsonl"),
        ConfirmManager(emit, lambda: True, timeout_s=0.2),
    )
    service.settle_delay = 0
    backend = Backend()
    service.register_backend("openhab", backend)
    return service, backend


def agent_for(service: DeviceService, provider: FakeProvider) -> Agent:
    registry = ToolRegistry()
    for tool in build_device_tools(service):
        registry.register(tool)
    return Agent(provider, registry, lambda: "SYSTEM")


async def run(
    agent: Agent, text: str = "x", device_related: bool = False
) -> tuple[str, ToolContext]:
    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    ctx.device_related = device_related
    out = "".join([d async for d in agent.run([{"role": "user", "content": text}], ctx)])
    return out, ctx


# --- Fertige Antworten sparen den zweiten Modellaufruf ---


async def test_a_successful_command_is_answered_without_asking_the_model_again(
    tmp_path: Path,
) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Deckenlicht Roman", "command": "off"})]
    )
    out, ctx = await run(agent_for(service, provider))
    assert out == "Okay, Deckenlicht Roman ist aus."
    assert backend.sent == [("roman", "off")]
    assert len(provider.calls) == 1  # nur der Schritt, der das Werkzeug wählt
    assert ctx.trace[0].ok


async def test_a_state_question_is_answered_from_the_tool_result(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    provider = FakeProvider([ToolCall("c1", "get_state", {"device": "Deckenlicht Roman"})])
    out, _ = await run(agent_for(service, provider), "Ist das Deckenlicht an?")
    assert out == "Deckenlicht Roman ist aus." and len(provider.calls) == 1


async def test_unknown_state_names_the_similar_device_in_the_instant_answer(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("0")})  # das Zwillings-Item hat einen Wert
    provider = FakeProvider([ToolCall("c1", "get_state", {"device": "Romans Rollo"})])
    out, _ = await run(agent_for(service, provider), "Ist Romans Rollo offen?")
    assert out.startswith("Den Zustand von Romans Rollo kenne ich nicht.")
    assert "Ähnliches Gerät: Rollo Roman Control ist offen." in out
    assert len(provider.calls) == 1


async def test_several_commands_in_one_step_are_answered_together(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [
            ToolCall("c1", "set_state", {"device": "Deckenlicht Roman", "command": "on"}),
            ToolCall("c2", "set_state", {"device": "Romans Rollo", "command": "down"}),
        ]
    )
    out, _ = await run(agent_for(service, provider))
    assert out == "Okay, Deckenlicht Roman ist an.\nOkay, Romans Rollo fährt runter."
    assert len(backend.sent) == 2 and len(provider.calls) == 1


async def test_a_failed_command_still_goes_back_to_the_model(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    backend.fail = True
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Deckenlicht Roman", "command": "off"})],
        [TextDelta("Das hat leider nicht geklappt, openHAB antwortet nicht.")],
    )
    out, _ = await run(agent_for(service, provider))
    assert "nicht geklappt" in out and len(provider.calls) == 2  # Fehler: das Modell erklärt


async def test_collective_question_with_state_filter_is_answered_without_the_model(
    tmp_path: Path,
) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"R": RawState("OFF"), "RO2": RawState("0")})
    provider = FakeProvider([ToolCall("c1", "list_devices", {"query": "Rollo", "state": "offen"})])
    out, _ = await run(agent_for(service, provider), "Welche Rollos sind offen?")
    assert out == "Offen sind: Rollo Roman Control (Romans Zimmer)." and len(provider.calls) == 1


async def test_state_filter_names_what_matches_and_says_when_nothing_does(
    tmp_path: Path,
) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"R": RawState("OFF"), "RO2": RawState("0")})
    provider = FakeProvider(
        [ToolCall("c1", "list_devices", {"state": "aus"})],
        [ToolCall("c1", "list_devices", {"state": "an"})],
    )
    agent = agent_for(service, provider)
    out, _ = await run(agent, "Was ist alles aus?")
    assert out == "Aus sind: Deckenlicht Roman (Romans Zimmer)."
    out, _ = await run(agent, "Welche Geräte sind an?")
    assert out == "Kein passendes Gerät ist an."


async def test_lookups_that_need_judgement_still_use_the_model(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "list_devices", {"query": "Rollo"})],
        [TextDelta("Es gibt zwei Rollos: Romans Rollo und Rollo Roman Control.")],
    )
    out, _ = await run(agent_for(service, provider))
    assert "zwei Rollos" in out and len(provider.calls) == 2


async def test_a_command_misrouted_to_get_state_still_gets_executed(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "get_state", {"device": "Deckenlicht Roman"})],
        [ToolCall("c2", "set_state", {"device": "Deckenlicht Roman", "command": "on"})],
    )
    out, _ = await run(agent_for(service, provider), "Mach das Deckenlicht von Roman an")
    assert out == "Okay, Deckenlicht Roman ist an." and backend.sent == [("roman", "on")]
    assert len(provider.calls) == 2


async def test_a_command_that_is_only_announced_after_reading_the_state_is_executed(
    tmp_path: Path,
) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "get_state", {"device": "Deckenlicht Roman"})],
        [TextDelta("Das Licht ist an. Ich schalte es aus.")],
        [ToolCall("c2", "set_state", {"device": "Deckenlicht Roman", "command": "off"})],
    )
    out, _ = await run(agent_for(service, provider), "Mach das Deckenlicht aus", True)
    assert out == "Okay, Deckenlicht Roman ist aus." and backend.sent == [("roman", "off")]


async def test_device_talk_without_a_tool_is_not_shown_unverified(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    provider = FakeProvider(
        [TextDelta("Das Deckenlicht ist bestimmt aus.")],
        [ToolCall("c1", "get_state", {"device": "Deckenlicht Roman"})],
        [TextDelta("Das Deckenlicht ist aus.")],
    )
    out, _ = await run(agent_for(service, provider), "Wie steht das Deckenlicht", True)
    assert "bestimmt" not in out and "ist aus" in out


async def test_a_vague_device_word_does_not_block_a_plain_answer(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    provider = FakeProvider([TextDelta("Roman ist ein Buch.")], [TextDelta("Roman ist ein Buch.")])
    out, _ = await run(agent_for(service, provider), "Was ist ein Roman", True)
    assert out == "Roman ist ein Buch."


def test_mentions_device_uses_words_from_the_house(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    assert service.mentions_device("Welche Lichter sind an?")
    assert service.mentions_device("Sind die Rollos offen?")
    assert service.mentions_device("Mach das Deckenlicht an")
    assert not service.mentions_device("Wie wird das Wetter morgen?")


async def test_a_call_written_as_text_is_executed(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    provider = FakeProvider([TextDelta('get_state(device="Deckenlicht Roman")')])
    out, ctx = await run(agent_for(service, provider), "Ist das Deckenlicht an?", True)
    assert out == "Deckenlicht Roman ist aus." and ctx.trace[0].tool == "get_state"


async def test_a_command_answered_with_get_state_is_not_learned_as_a_question(
    tmp_path: Path,
) -> None:
    service, _ = make(tmp_path)
    learner = Learner(tmp_path / "learned.json", service, learn_after=1)
    from cat.agent.tools import ToolTrace

    wrong = [ToolTrace("get_state", {"device": "Deckenlicht Roman"}, True, "")]
    assert learner.observe("Mach das Deckenlicht von Roman an", wrong) is None
    assert learner.listing() == []
    assert learner.observe("Ist das Deckenlicht Roman an", wrong) is not None


# --- Kleiner Prompt für das lokale Modell ---


def local_payload(tmp_path: Path) -> tuple[str, str, list[str]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        local_model="qwen-test",
        claude_url="http://claude-bridge:8099",
        plugins="system,weather",
        sandbox=True,
    )
    state = AppState(settings)
    responder = build_responder(state, provider=FakeProvider())  # type: ignore[arg-type]
    agent: Agent = responder._agent  # type: ignore[attr-defined]
    schemas = agent._registry.schemas()
    return (
        agent._system_prompt(),
        json.dumps(schemas, ensure_ascii=False),
        [s["function"]["name"] for s in schemas],
    )


def test_local_model_gets_few_compact_tools(tmp_path: Path) -> None:
    system, tools, names = local_payload(tmp_path)
    assert set(names) <= set(LOCAL_TOOLS) | {"ask_claude"} and "ask_claude" in names
    assert "set_state" in names and "show_chart" not in names and "show_markdown" not in names
    assert len(tools) < 2600  # vorher ca. 9000 Zeichen für 16 Werkzeuge
    assert tools.count('"description"') == len(names)  # nur je Werkzeug eine, keine je Parameter


def test_parameter_descriptions_are_stripped_but_names_and_enums_stay(tmp_path: Path) -> None:
    registry = ToolRegistry()

    async def noop(_: dict[str, Any], __: ToolContext) -> str:
        return ""

    registry.register(
        Tool(
            "demo",
            "Ein langer Satz. Noch einer.",
            {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["a", "b"], "description": "lang"}
                },
                "required": ["mode"],
            },
            noop,
        )
    )
    schema = registry.compact({}).schemas()[0]["function"]
    assert schema["description"] == "Ein langer Satz"  # erster Satz, wenn keine Kurzfassung da ist
    assert schema["parameters"]["properties"]["mode"] == {"type": "string", "enum": ["a", "b"]}
    assert schema["parameters"]["required"] == ["mode"]
    assert (
        registry.schemas()[0]["function"]["parameters"]["properties"]["mode"]["description"]
        == "lang"
    )


def test_local_system_prompt_is_short_and_keeps_the_rules() -> None:
    prompt = build_local_prompt(claude=True)
    assert len(prompt) < 1400  # vorher 1800 Zeichen
    for needle in (
        "Zustände nie raten",
        "Erfolg meldest du erst nach",
        "ask_claude",
        "nie Passwörter",
    ):
        assert needle in prompt
    assert "ask_claude" not in build_local_prompt(claude=False)


# --- Abfragen werden sofort gelernt ---


async def test_questions_are_learned_after_one_time_but_commands_need_two(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    learner = Learner(tmp_path / "learned.json", service, learn_after=2)
    from cat.agent.tools import ToolTrace

    ask = [ToolTrace("get_state", {"device": "Deckenlicht Roman"}, True, "")]
    first = learner.observe("Ist das Deckenlicht Roman an?", ask)
    assert first is not None and first.active
    result = await learner.handle("ist das deckenlicht roman an")
    assert result is not None and result.text == "Deckenlicht Roman ist aus."
    cmd = [ToolTrace("set_state", {"device": "Deckenlicht Roman", "command": "off"}, True, "")]
    assert learner.observe("Schalte Deckenlicht Roman aus", cmd) is None  # erst einmal gesehen
    assert learner.observe("Schalte Deckenlicht Roman aus", cmd) is not None
    rows = {r["phrase"]: r for r in learner.listing()}
    assert rows["ist das {dev} an"]["needed"] == 1 and rows["schalte {dev} aus"]["needed"] == 2


async def test_tool_turns_are_marked_so_the_local_model_does_not_copy_them(
    tmp_path: Path,
) -> None:
    from cat.dialog import handle_user_text

    state = AppState(Settings(_env_file=None, data_dir=tmp_path))  # type: ignore[call-arg]

    class Tooled:
        async def reply(self, history, spoken=False, room=None):  # type: ignore[no-untyped-def]
            await state.learn_from("Licht an", [ToolTrace("set_state", {}, True, "")])
            yield "Okay."

    from cat.agent.tools import ToolTrace

    state.responder = Tooled()
    await handle_user_text(state, "Licht an")
    assert [m.tooled for m in state.chat] == [True, True]
    state.responder = None  # Echo-Antwort ohne Werkzeuge
    await handle_user_text(state, "Hallo")
    assert [m.tooled for m in state.chat][2:] == [False, False]


def test_defaults_favour_speed() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.local_threads >= 4 and s.local_keep_alive == "60m" and s.vad_silence_s <= 1.2


@pytest.mark.parametrize("name", LOCAL_TOOLS)
def test_every_local_tool_has_a_brief(name: str) -> None:
    assert name in LOCAL_BRIEFS and len(LOCAL_BRIEFS[name]) < 130
