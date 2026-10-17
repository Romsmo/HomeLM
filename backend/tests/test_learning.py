import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cat.agent.loop import CORRECTION, UNVERIFIED, Agent
from cat.agent.tools import Tool, ToolContext, ToolRegistry, ToolTrace
from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import parse_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.intents import learned as learned_module
from cat.intents.claims import claims_action
from cat.intents.learned import Learner, phrase_of
from cat.llm.base import TextDelta, ToolCall
from cat.main import create_app
from cat.stage.store import StageStore
from cat.ws.protocol import ChatMessage, ServerEvent
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider

YAML = """
devices:
  - {id: roman, backend: openhab, item: R, name: Deckenlicht Roman, room: Romans Zimmer, type: light}
  - {id: marius, backend: openhab, item: M, name: Deckenlicht Marius, room: Marius Zimmer, type: light}
  - {id: kueche, backend: openhab, item: K, name: Küchenlicht, room: Küche, type: light, synonyms: [Licht Küche]}
  - {id: rollo, backend: openhab, item: RO, name: Romans Rollo, room: Romans Zimmer, type: shutter}
  - {id: temp, backend: openhab, item: T, name: Außentemperatur, room: Terrasse, type: sensor}
"""


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec: DeviceSpec) -> RawState:
        return RawState(
            {"RO": "0", "T": "12.5"}.get(spec.item, "OFF"), "°C" if spec.item == "T" else None
        )

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.id, command))


class Harness:
    def __init__(self, tmp_path: Path, control: str = "full", learn_after: int = 2) -> None:
        self.events: list[ServerEvent] = []

        async def emit(event: ServerEvent) -> None:
            self.events.append(event)

        self.path = tmp_path / "learned.json"
        self.service = DeviceService(
            parse_allowlist(YAML),
            control,  # type: ignore[arg-type]
            emit,
            AuditLog(tmp_path / "a.jsonl"),
            ConfirmManager(emit, lambda: True, timeout_s=0.2),
        )
        self.service.settle_delay = 0
        self.backend = Backend()
        self.service.register_backend("openhab", self.backend)
        self.learner = Learner(self.path, self.service, learn_after)

    def run(self, text: str, *calls: tuple[str, dict[str, Any]], ok: bool = True, **kw: Any):  # type: ignore[no-untyped-def]
        trace = [ToolTrace(tool, args, ok, "") for tool, args in calls]
        return self.learner.observe(text, trace, **kw)


def set_(device: str, command: str) -> tuple[str, dict[str, Any]]:
    return "set_state", {"device": device, "command": command}


def get(device: str) -> tuple[str, dict[str, Any]]:
    return "get_state", {"device": device}


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_phrase_is_normalized() -> None:
    assert phrase_of("Mach das Küchenlicht AN!") == "mach das kuechenlicht an"
    assert phrase_of("  Fahre Romans Rollo auf 21,5 %. ") == "fahre romans rollo auf 21,5 %"


async def test_learns_after_the_same_request_twice_then_answers_without_the_model(
    h: Harness,
) -> None:
    assert h.run("Schalte Deckenlicht Roman an", set_("Deckenlicht Roman", "on")) is None
    assert await h.learner.handle("Schalte Deckenlicht Roman an") is None  # erst einmal gesehen
    learned = h.run("Schalte Deckenlicht Roman an.", set_("Deckenlicht Roman", "ON"))
    assert learned is not None and learned.active  # beim zweiten Mal neu aktiv
    assert (
        h.run("Schalte Deckenlicht Roman an", set_("Deckenlicht Roman", "on")) is None
    )  # nicht erneut melden
    result = await h.learner.handle("schalte deckenlicht roman an")
    assert result is not None and "Deckenlicht Roman ist an" in result.text
    assert h.backend.sent == [("roman", "on")]
    assert result.total_ms < 500  # Millisekunden statt Sekunden


async def test_the_device_name_becomes_a_building_block(h: Harness) -> None:
    h.run("schalte deckenlicht roman an", set_("roman", "on"))
    h.run("schalte deckenlicht roman an", set_("roman", "on"))
    result = await h.learner.handle(
        "Schalte Deckenlicht Marius an"
    )  # nie gelernt, nur der Baustein
    assert result is not None and h.backend.sent == [("marius", "on")]
    assert await h.learner.handle("schalte das radio an") is None  # unbekanntes Gerät: Modell
    assert h.backend.sent == [("marius", "on")]


async def test_numbers_are_building_blocks_too_and_are_checked(h: Harness) -> None:
    for _ in range(2):
        h.run("fahre romans rollo auf 50 prozent", set_("rollo", "50"))
    assert (await h.learner.handle("fahre romans rollo auf 30 prozent")) is not None
    assert h.backend.sent == [("rollo", "30")]
    assert await h.learner.handle("fahre romans rollo auf 500 prozent") is None  # nicht raten
    assert h.backend.sent == [("rollo", "30")]


async def test_sentences_that_depend_on_the_conversation_are_not_learned(h: Harness) -> None:
    for _ in range(3):  # "es" meint das Gerät, das gerade eben dran war
        h.run("mach es wieder aus", set_("roman", "off"), previous_device="roman")
    assert await h.learner.handle("mach es wieder aus") is None
    assert h.learner.listing() == []


async def test_a_phrase_without_a_device_name_is_learned_as_an_alias(h: Harness) -> None:
    for _ in range(2):
        h.run("wie warm ist es draußen", get("temp"), previous_device="roman")
    result = await h.learner.handle("Wie warm ist es draußen?")
    assert result is not None and result.text == "Außentemperatur: 12,5 °C."
    assert await h.learner.handle("wie kalt ist es draußen") is None  # andere Worte: Modell


async def test_a_room_makes_a_vague_sentence_learnable_for_that_room(h: Harness) -> None:
    for _ in range(2):
        h.run("Mach das Licht an", set_("kueche", "on"), room="Küche", previous_device=None)
    assert await h.learner.handle("mach das licht an", "Flur") is None
    result = await h.learner.handle("mach das licht an", "Küche")
    assert result is not None and h.backend.sent == [("kueche", "on")]


async def test_a_vague_sentence_right_after_the_same_device_is_still_context(h: Harness) -> None:
    for _ in range(3):
        h.run("mach es an", set_("kueche", "on"), room="Küche", previous_device="kueche")
    assert h.learner.listing() == []


async def test_only_successful_pure_device_requests_are_learned(h: Harness) -> None:
    for _ in range(3):
        h.run("schalte deckenlicht roman an", set_("roman", "on"), ok=False)
        h.run("schalte deckenlicht roman an", ("memory_write", {"title": "x"}), set_("roman", "on"))
        h.run("schalte deckenlicht roman an", set_("unbekanntes geraet", "on"))
        h.run("schalte deckenlicht roman an", set_("roman", "kaputt"))
        h.run("schalte deckenlicht roman an")
    assert h.learner.listing() == []
    h.run("schalte deckenlicht roman an", ("list_devices", {}), set_("roman", "on"))
    h.run("schalte deckenlicht roman an", ("list_devices", {"query": "x"}), set_("roman", "on"))
    assert len(h.learner.listing()) == 1 and h.learner.listing()[0]["active"]


async def test_a_routine_with_several_devices_is_learned_as_a_whole(h: Harness) -> None:
    routine = (set_("roman", "off"), set_("marius", "off"), set_("rollo", "down"))
    for _ in range(2):
        h.run("gute nacht", *routine)
    result = await h.learner.handle("Gute Nacht!")
    assert result is not None
    assert h.backend.sent == [("roman", "off"), ("marius", "off"), ("rollo", "down")]
    assert result.text.count("Okay") == 3


async def test_a_different_outcome_for_the_same_words_starts_counting_again(h: Harness) -> None:
    h.run("licht aus im kinderzimmer", set_("roman", "off"), previous_device="marius")
    h.run(
        "licht aus im kinderzimmer", set_("marius", "off"), previous_device="roman"
    )  # andere Aktion
    assert h.learner.listing()[0]["seen"] == 1 and not h.learner.listing()[0]["active"]


async def test_questions_are_learned_too(h: Harness) -> None:
    for _ in range(2):
        h.run("ist romans rollo offen", get("rollo"))
    result = await h.learner.handle("Ist Romans Rollo offen?")
    assert result is not None and result.text == "Romans Rollo ist offen."
    for _ in range(2):
        h.run("wie warm ist es draußen", get("temp"))
    warm = await h.learner.handle("Wie warm ist es draußen?")
    assert warm is not None and warm.text == "Außentemperatur: 12,5 °C."


async def test_everything_learned_survives_a_restart_and_can_be_forgotten(h: Harness) -> None:
    for _ in range(2):
        h.run("schalte deckenlicht roman an", set_("roman", "on"))
    again = Learner(h.path, h.service, 2)
    assert await again.handle("schalte deckenlicht roman an") is not None
    row = again.listing()[0]
    assert row["active"] and row["phrase"] == "schalte {dev} an" and "Gerät" in row["does"]
    assert again.forget(row["id"]) and not again.forget(row["id"])
    assert await again.handle("schalte deckenlicht roman an") is None
    assert json.loads(h.path.read_text(encoding="utf-8"))["shortcuts"] == []
    h.run("schalte deckenlicht roman an", set_("roman", "on"))
    again.clear()
    assert again.listing() == []


async def test_a_vanished_device_makes_the_shortcut_forget_itself(h: Harness) -> None:
    for _ in range(2):
        h.run("wie warm ist es draußen", get("temp"))
    h.service._allowlist.specs[:] = [s for s in h.service._allowlist.specs if s.id != "temp"]
    h.service._rebuild()
    assert await h.learner.handle("wie warm ist es draußen") is None
    assert h.learner.listing() == []


async def test_safety_rules_still_apply_to_shortcuts(tmp_path: Path) -> None:
    h = Harness(tmp_path, control="readonly")
    for _ in range(2):
        h.run("schalte deckenlicht roman an", set_("roman", "on"))
    result = await h.learner.handle("schalte deckenlicht roman an")
    assert result is not None and "Steuern ist ausgeschaltet" in result.text
    assert h.backend.sent == []


async def test_disabled_learning_does_nothing(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.learner.enabled = False
    for _ in range(3):
        h.run("schalte deckenlicht roman an", set_("roman", "on"))
    assert h.learner.listing() == [] and await h.learner.handle("x") is None


async def test_the_list_is_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(learned_module, "MAX_ENTRIES", 3)
    h = Harness(tmp_path, learn_after=1)
    for i in range(6):
        h.run(f"deckenlicht roman variante {i}", set_("roman", "on"))
    assert len(h.learner.listing()) == 3


def test_broken_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "learned.json").write_text("{kaputt", encoding="utf-8")
    assert Harness(tmp_path).learner.listing() == []


async def test_announces_what_it_learned_in_the_chat(tmp_path: Path) -> None:
    from cat.state import AppState

    settings = Settings(_env_file=None, data_dir=tmp_path, plugins="")  # type: ignore[call-arg]
    state = AppState(settings)
    state.devices.register_backend("openhab", Backend())
    state.devices._allowlist.specs.append(parse_allowlist(YAML).specs[0])
    state.devices._rebuild()
    sent: list[ServerEvent] = []

    async def emit(event: ServerEvent) -> None:
        sent.append(event)

    state.emit = emit  # type: ignore[method-assign]
    trace = [ToolTrace("set_state", {"device": "roman", "command": "on"}, True, "")]
    await state.learn_from("schalte deckenlicht roman an", trace)
    assert sent == []
    await state.learn_from("schalte deckenlicht roman an", trace)
    note = next(e for e in sent if isinstance(e, ChatMessage))
    assert (
        note.role == "system" and "künftig sofort" in note.text and "schalte {dev} an" in note.text
    )


# --- Absicherung gegen erfundene Erfolgsmeldungen ---


@pytest.mark.parametrize(
    "text",
    [
        "Okay, Deckenlicht Roman ist aus.",
        "Das Licht ist jetzt an.",
        "Der Rollladen ist wieder offen",
        "Ich habe das Licht ausgeschaltet.",
        "Erledigt!",
        "Romans Rollo fährt jetzt hoch.",
    ],
)
def test_unbacked_claims_are_recognized(text: str) -> None:
    assert claims_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "Ich bin Cat, der Heimassistent.",
        "Das Licht ist an der Decke montiert.",
        "Wie warm soll es sein?",
        "Die Hauptstadt von Australien ist Canberra.",
        "Welches Gerät meinst du?",
    ],
)
def test_normal_sentences_are_not_claims(text: str) -> None:
    assert not claims_action(text)


async def ok_tool(args: dict[str, Any], _: ToolContext) -> str:
    return "Befehl gesendet."


def guarded_agent(provider: FakeProvider) -> Agent:
    registry = ToolRegistry()
    for name in ("set_state", "get_state", "list_devices"):
        registry.register(Tool(name, name, {"type": "object", "properties": {}}, ok_tool))
    return Agent(provider, registry, lambda: "SYSTEM")


async def run_agent(agent: Agent, text: str = "mach es aus") -> tuple[str, ToolContext]:
    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    out = "".join([d async for d in agent.run([{"role": "user", "content": text}], ctx)])
    return out, ctx


async def test_a_claim_without_a_tool_call_is_not_shown_and_the_model_is_corrected() -> None:
    provider = FakeProvider(
        [TextDelta("Okay, Deckenlicht Roman ist aus.")],
        [ToolCall("c1", "set_state", {"device": "roman", "command": "off"})],
        [TextDelta("Fertig, Deckenlicht Roman ist aus.")],
    )
    out, ctx = await run_agent(guarded_agent(provider))
    assert out == "Fertig, Deckenlicht Roman ist aus."  # erst nach dem echten Werkzeug
    assert [t.tool for t in ctx.trace] == ["set_state"]
    assert provider.calls[1]["messages"][-1]["content"] == CORRECTION
    assert provider.calls[1]["messages"][-2] == {
        "role": "assistant",
        "content": "Okay, Deckenlicht Roman ist aus.",
    }


async def test_a_second_unbacked_claim_ends_with_an_honest_message() -> None:
    provider = FakeProvider(
        [TextDelta("Okay, das Licht ist aus.")], [TextDelta("Ja, ist erledigt.")]
    )
    out, ctx = await run_agent(guarded_agent(provider))
    assert out == UNVERIFIED and ctx.trace == []


async def test_a_claim_in_the_same_step_as_a_tool_call_is_fine() -> None:
    provider = FakeProvider(
        [
            TextDelta("Okay, ist erledigt."),
            ToolCall("c1", "set_state", {"device": "x", "command": "on"}),
        ],
        [TextDelta("Das Licht ist jetzt an.")],
    )
    out, _ = await run_agent(guarded_agent(provider))
    assert "Das Licht ist jetzt an." in out and UNVERIFIED not in out


async def test_claims_after_a_real_lookup_are_not_questioned() -> None:
    provider = FakeProvider(
        [ToolCall("c1", "get_state", {"device": "x"})], [TextDelta("Das Licht ist an.")]
    )
    out, _ = await run_agent(guarded_agent(provider))
    assert out == "Das Licht ist an."


async def test_normal_answers_stream_normally_and_agents_without_devices_skip_the_guard() -> None:
    provider = FakeProvider([TextDelta("Ich bin Cat. "), TextDelta("Wie kann ich helfen?")])
    out, _ = await run_agent(guarded_agent(provider), "wer bist du")
    assert out == "Ich bin Cat. Wie kann ich helfen?"
    plain = Agent(FakeProvider([TextDelta("Erledigt!")]), ToolRegistry(), lambda: "S")
    assert (await run_agent(plain))[0] == "Erledigt!"


# --- API ---


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def test_api_lists_and_forgets_what_was_learned(client: TestClient) -> None:
    state = client.app.state.cat  # type: ignore[attr-defined]
    state.devices._allowlist.specs.append(parse_allowlist(YAML).specs[0])
    state.devices._rebuild()
    trace = [ToolTrace("set_state", {"device": "roman", "command": "on"}, True, "")]
    for _ in range(2):
        state.learner.observe("schalte deckenlicht roman an", trace)
    rows = client.get("/api/learned").json()
    assert len(rows) == 1 and rows[0]["phrase"] == "schalte {dev} an" and rows[0]["active"]
    other = TestClient(client.app)
    assert other.get("/api/learned").status_code == 401
    assert client.delete("/api/learned/gibtsnicht").status_code == 404
    bad = client.delete(f"/api/learned/{rows[0]['id']}", headers={"origin": "https://x.example"})
    assert bad.status_code == 403
    assert client.delete(f"/api/learned/{rows[0]['id']}").json() == {"ok": True}
    assert client.get("/api/learned").json() == []
    audit = state.settings.audit_file.read_text(encoding="utf-8")
    assert "learned_forget" in audit
