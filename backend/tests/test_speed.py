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
    agent: Agent, text: str = "Mach 1", device_related: bool = False
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
    out, _ = await run(agent_for(service, provider), "Mach das Deckenlicht von Roman an", True)
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


async def test_a_command_that_contradicts_the_users_words_is_not_sent(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Deckenlicht Roman", "command": "on"})],
        [ToolCall("c2", "set_state", {"device": "Deckenlicht Roman", "command": "off"})],
    )
    out, _ = await run(agent_for(service, provider), "Mach das Deckenlicht von Roman aus", True)
    assert backend.sent == [("roman", "off")] and out == "Okay, Deckenlicht Roman ist aus."


def test_power_conflict_only_fires_for_a_clear_direction() -> None:
    from cat.intents.text import power_conflict

    assert power_conflict("Mach das Licht aus", "on") == "aus"
    assert power_conflict("Schalte das Licht ein", "off") == "an"
    assert power_conflict("Mach das Licht aus", "off") is None
    assert power_conflict("Mach das eine an und das andere aus", "on") is None
    assert power_conflict("Stell den Rollo auf 50", "50") is None


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


def test_same_words_in_another_order_find_the_device(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    spec = service.resolve("Rollos Roman")
    assert spec is not None and spec.id == "rollo"


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
    assert len(tools) < 3100  # vorher ca. 9000 Zeichen für 16 Werkzeuge
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
    assert s.local_threads >= 4 and s.local_keep_alive == "24h" and s.vad_silence_s <= 1.2


@pytest.mark.parametrize("name", LOCAL_TOOLS)
def test_every_local_tool_has_a_brief(name: str) -> None:
    assert name in LOCAL_BRIEFS and len(LOCAL_BRIEFS[name]) < 130


async def test_shutter_words_cover_rollos_and_markises_together(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("0")})
    provider = FakeProvider(
        [ToolCall("c1", "list_devices", {"query": "Rollos oder Markisen", "state": "offen"})]
    )
    out, _ = await run(agent_for(service, provider), "Welche Rollos und Markisen sind offen?")
    assert out == "Offen sind: Rollo Roman Control (Romans Zimmer)."


async def test_an_imperative_that_asks_for_information_is_not_treated_as_a_command(
    tmp_path: Path,
) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("0")})
    provider = FakeProvider(
        [ToolCall("c1", "list_devices", {"query": "Rollos", "state": "offen"})],
    )
    text = "zähle mir bitte auf, welche ganzen Rollos einschließlich Markisen offen sind"
    out, _ = await run(agent_for(service, provider), text, True)
    assert out == "Offen sind: Rollo Roman Control (Romans Zimmer)." and len(provider.calls) == 1


def test_control_cues() -> None:
    from cat.intents.text import has_control_cue, is_question

    assert has_control_cue("Mach das Licht aus") and has_control_cue("Rollo auf 30 Prozent")
    assert has_control_cue("Fahr das Rollo runter")
    assert not has_control_cue("Zeig mir die Rollos im Haus")
    assert is_question("zähle mir bitte auf, welche Rollos offen sind")


async def test_markises_and_rollos_can_be_asked_separately(tmp_path: Path) -> None:
    from cat.devices.allowlist import parse_allowlist

    yaml = (
        "devices:\n"
        "  - {id: rollo, backend: openhab, item: RO, name: Romans Rollo, room: Romans Zimmer, "
        "type: shutter}\n"
        "  - {id: mark, backend: openhab, item: MA, name: Markise Nord, room: Terrassenmarkisen, "
        "type: shutter}\n"
    )
    service, _ = make(tmp_path)
    service._allowlist = parse_allowlist(yaml)
    service._rebuild()
    service.seed_states("openhab", {"RO": RawState("0"), "MA": RawState("0")})

    async def ask(query: str) -> str:
        provider = FakeProvider([ToolCall("c", "list_devices", {"query": query, "state": "offen"})])
        out, _ = await run(agent_for(service, provider), "Welche sind offen?", True)
        return out

    assert await ask("Markisen") == "Offen sind: Markise Nord (Terrassenmarkisen)."
    assert await ask("Rollos") == "Offen sind: Romans Rollo (Romans Zimmer)."
    both = await ask("Rollos oder Markisen")
    assert "Markise Nord" in both and "Romans Rollo" in both


# --- Kurzzeilen statt Werkzeugaufruf (local_compact) ---


def compact_agent(service: DeviceService, provider: FakeProvider) -> Agent:
    from cat.agent.prompt import COMPACT_HIDDEN

    registry = ToolRegistry()
    for tool in build_device_tools(service):
        registry.register(tool)
    return Agent(provider, registry, lambda: "SYSTEM", hidden_tools=COMPACT_HIDDEN)


async def test_a_short_line_is_executed_and_never_shown(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider([TextDelta("S|Deckenlicht Roman|off")])
    out, ctx = await run(compact_agent(service, provider), "Mach das Deckenlicht aus", True)
    assert out == "Okay, Deckenlicht Roman ist aus." and backend.sent == [("roman", "off")]
    assert len(provider.calls) == 1 and ctx.trace[0].tool == "set_state"
    assert "set_state" not in provider.calls[0]["tool_names"]  # das Modell sieht kein Schema


async def test_a_short_line_arriving_in_small_pieces_is_not_leaked(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [TextDelta("S"), TextDelta("|Deckenlicht"), TextDelta(" Roman|"), TextDelta("on")]
    )
    out, _ = await run(compact_agent(service, provider), "Schalte das Deckenlicht ein", False)
    assert out == "Okay, Deckenlicht Roman ist an." and backend.sent == [("roman", "on")]


async def test_several_short_lines_are_several_calls(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider([TextDelta("S|Deckenlicht Roman|on\nS|Romans Rollo|down")])
    out, _ = await run(compact_agent(service, provider), "Licht an und Rollo runter", True)
    assert out == "Okay, Deckenlicht Roman ist an.\nOkay, Romans Rollo fährt runter."
    assert len(backend.sent) == 2


async def test_state_questions_and_lists_work_as_short_lines(tmp_path: Path) -> None:
    service, _ = make(tmp_path)
    service.seed_states("openhab", {"RO2": RawState("0")})
    out, _ = await run(
        compact_agent(service, FakeProvider([TextDelta("G|Deckenlicht Roman")])),
        "Ist das Deckenlicht an?",
        True,
    )
    assert out == "Deckenlicht Roman ist aus."
    out, _ = await run(
        compact_agent(service, FakeProvider([TextDelta("L|Rollos oder Markisen|offen")])),
        "Welche Rollos sind offen?",
        True,
    )
    assert out == "Offen sind: Rollo Roman Control (Romans Zimmer)."


async def test_normal_answers_starting_with_a_command_letter_are_shown_unchanged(
    tmp_path: Path,
) -> None:
    service, _ = make(tmp_path)
    for text in ("Sehr gern!", "Gern geschehen.", "S", "Alles klar, das ist ein Test."):
        provider = FakeProvider([TextDelta(text)])
        out, _ = await run(compact_agent(service, provider), "Danke", False)
        assert out == text


async def test_a_line_with_extra_text_is_not_treated_as_a_command(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider([TextDelta("S|Deckenlicht Roman|off\nDas habe ich gemacht.")])
    out, _ = await run(compact_agent(service, provider), "Danke", False)
    assert backend.sent == [] and "Das habe ich gemacht." in out


def test_compact_mode_is_the_default_and_the_prompt_teaches_the_format() -> None:
    from cat.agent.prompt import build_local_prompt

    assert Settings(_env_file=None).local_compact is True  # type: ignore[call-arg]
    prompt = build_local_prompt(claude=True, compact=True)
    assert "S|Gerät|Befehl" in prompt and "L|Stichwort|Zustand" in prompt and "ask_claude" in prompt
    assert "set_state(device" not in prompt


def test_old_assistant_messages_are_shortened_for_the_small_model() -> None:
    from cat.agent.loop import to_llm_messages

    long = "Antwort " * 100
    items = [("user", "Frage 1"), ("assistant", long), ("user", "Frage 2"), ("assistant", long)]
    out = to_llm_messages(items, limit=8, max_chars=100)
    assert len(out[1]["content"]) <= 100 and out[1]["content"].endswith("…")
    assert out[-1]["content"] == long  # die letzte Nachricht bleibt vollständig
    assert to_llm_messages(items)[1]["content"] == long  # ohne Grenze unverändert


async def test_device_requests_get_no_time_or_memory_in_the_prompt(tmp_path: Path) -> None:
    from cat.agent.responder import build_responder
    from cat.ws.protocol import ChatMessage

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, data_dir=tmp_path, local_model="q", plugins="", sandbox=False, people=False
    )
    state = AppState(settings)
    service, _ = make(tmp_path)
    state.devices = service
    state.memory.remember("Kurzbefehle", "Deckenlicht Roman Rollo schalten", "gelerntes", ["auto"])
    provider = FakeProvider([TextDelta("ok")], [TextDelta("ok")])  # 2. Schritt: Korrektur
    responder = build_responder(state, provider=provider)  # type: ignore[arg-type]
    history = [ChatMessage(id="1", role="user", text="Mach das Deckenlicht von Roman an", ts=0)]
    _ = [d async for d in responder.reply(history)]
    sent = provider.calls[0]["messages"][-1]["content"]
    assert sent == "Mach das Deckenlicht von Roman an"
    assert state.memory.context_for("Deckenlicht Roman Rollo") == ""  # Kurzbefehle nie fürs Modell


async def test_a_name_or_an_explanation_never_switches_anything(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    for text in (
        "Roman.",
        "Mit Dach-Rollo meine ich Rollo Roman",
        "Ich hab doch nie gesagt, dass du das Rollo öffnen sollst",
        "Warum hast du Romans Rollo geöffnet?",
    ):
        provider = FakeProvider(
            [ToolCall("c", "set_state", {"device": "Romans Rollo", "command": "up"})]
        )
        out, ctx = await run(compact_agent(service, provider), text, True)
        assert "nicht als Schaltbefehl" in out and ctx.trace[0].ok is False
    assert backend.sent == []


async def test_closing_words_with_an_opening_command_are_refused(tmp_path: Path) -> None:
    service, backend = make(tmp_path)
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "Romans Rollo", "command": "0"})],
        [ToolCall("c2", "set_state", {"device": "Romans Rollo", "command": "down"})],
    )
    out, _ = await run(agent_for(service, provider), "Bitte schließe Romans Rollo", True)
    assert backend.sent == [("rollo", "down")] and out == "Okay, Romans Rollo fährt runter."


def test_shutter_conflict_and_wording() -> None:
    from cat.intents.replies import confirm_text
    from cat.intents.text import shutter_conflict

    assert shutter_conflict("Bitte die Dachrollos schließen", "0") == "schließen"
    assert shutter_conflict("Mach das Rollo auf", "down") == "öffnen"
    assert shutter_conflict("Mach das Rollo auf", "up") is None
    assert shutter_conflict("Rollo auf 30 Prozent", "0") is None  # Zahl im Text: keine Prüfung
    assert shutter_conflict("Schließe und öffne", "0") is None  # unklar
    spec = DeviceSpec(id="r", backend="openhab", item="R", name="Rollo", room="Z", type="shutter")
    assert confirm_text(spec, "0") == "Okay, Rollo ist offen."
    assert confirm_text(spec, "100") == "Okay, Rollo ist zu."
    assert confirm_text(spec, "30") == "Okay, Rollo ist zu 30 Prozent geschlossen."
