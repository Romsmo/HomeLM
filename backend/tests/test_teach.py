from pathlib import Path

import pytest

from cat.agent.loop import Agent
from cat.agent.prompt import COMPACT_HIDDEN
from cat.agent.tools import ToolContext, ToolRegistry
from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import parse_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.service import DeviceService, RawState
from cat.devices.tools import build_device_tools
from cat.dialog import handle_user_text
from cat.intents.fillers import FillerBank, user_phrase
from cat.intents.lexicon import Lexicon, normalize
from cat.intents.teach import TeachService
from cat.llm.base import TextDelta, ToolCall
from cat.memory.service import MemoryService
from cat.stage.store import StageStore
from cat.state import AppState
from tests.fakes import FakeProvider

YAML = """
devices:
  - {id: roman, backend: openhab, item: R, name: Romans Rollo, room: Romans Zimmer, type: shutter}
  - {id: marius, backend: openhab, item: M, name: Marius Rollo, room: Marius Zimmer, type: shutter}
  - {id: licht, backend: openhab, item: L, name: Deckenlicht Roman, room: Romans Zimmer, type: light}
  - {id: tuer, backend: openhab, item: T, name: Haustür, room: Flur, type: door, risk: high}
  - {id: terrasse, backend: openhab, item: TL, name: Terrassenlicht, room: Terrasse, type: light}
"""


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec):  # type: ignore[no-untyped-def]
        return RawState("0")

    async def send(self, spec, command: str) -> None:  # type: ignore[no-untyped-def]
        self.sent.append((spec.id, command))


def make(tmp_path: Path) -> tuple[DeviceService, Backend, TeachService]:
    async def emit(_: object) -> None: ...

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
    lexicon = Lexicon(tmp_path / "lexicon.json")
    service.lexicon = lexicon
    teach = TeachService(
        service,
        lexicon,
        FillerBank(tmp_path / "fillers.json"),
        MemoryService(tmp_path / "memory", tmp_path / "sessions"),
        AuditLog(tmp_path / "teach.jsonl"),
    )
    return service, backend, teach


# --- Wortschatz ---


def test_terms_are_normalised_so_plural_and_hyphen_do_not_matter() -> None:
    assert normalize("Dach-Rollo") == normalize("Dachrollos") == normalize("dach rollos")
    assert normalize("Dachrollen") == normalize("Dachrollo")


def test_lexicon_persists_and_finds_terms_in_text(tmp_path: Path) -> None:
    lex = Lexicon(tmp_path / "l.json")
    lex.add("Dach-Rollo", ["roman", "marius"])
    again = Lexicon(tmp_path / "l.json")
    assert again.lookup("die Dachrollos").ids == ["roman", "marius"]  # type: ignore[union-attr]
    assert again.mentions("Mach bitte alle Dach Rollos zu") and not again.mentions("Hallo")
    again.forget_device("marius")
    assert again.lookup("Dachrollo").ids == ["roman"]  # type: ignore[union-attr]
    assert again.remove("dachrollos") and again.listing() == []


# --- Begriffe erklären (Szene aus dem Chat) ---


async def test_explaining_a_term_never_moves_a_shutter_and_the_term_works_afterwards(
    tmp_path: Path,
) -> None:
    service, backend, teach = make(tmp_path)
    reply = await teach.intercept("Mit Dach-Rollo meine ich Rollo Roman und Rollo Marius.")
    assert reply == "Okay, ab jetzt verstehe ich „Dach-Rollo“ als Romans Rollo und Marius Rollo."
    assert backend.sent == []

    registry = ToolRegistry()
    for tool in build_device_tools(service):
        registry.register(tool)
    provider = FakeProvider([TextDelta("S|Dachrollos|down")])
    agent = Agent(provider, registry, lambda: "SYSTEM", hidden_tools=COMPACT_HIDDEN)

    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    ctx.device_related = True
    out = "".join(
        [
            d
            async for d in agent.run(
                [{"role": "user", "content": "Bitte die Dachrollos schließen"}], ctx
            )
        ]
    )
    assert backend.sent == [("roman", "down"), ("marius", "down")]
    assert out == "Okay, Romans Rollo fährt runter.\nOkay, Marius Rollo fährt runter."


@pytest.mark.parametrize(
    "text",
    [
        "Das Wetter ist schön",  # Ziel ist kein Gerät
        "Roman ist ein Name",
        "Wie viele Rollos sind offen",
        "Mit Dachrollos meine ich das Haus",
        "Rollo Roman ist Romans Rollo",  # der Begriff ist selbst ein Gerät
    ],
)
async def test_only_real_devices_make_an_explanation(tmp_path: Path, text: str) -> None:
    _, _, teach = make(tmp_path)
    assert await teach.intercept(text) is None


async def test_a_term_can_be_asked_for_and_listed(tmp_path: Path) -> None:
    _, _, teach = make(tmp_path)
    assert "noch keine Begriffe" in (await teach.intercept("Welche Begriffe kennst du?") or "")
    await teach.intercept("Wenn ich Kinderrollos sage, meine ich Romans Rollo und Marius Rollo")
    assert (await teach.intercept("Was ist ein Kinderrollo?")) == (
        "„Kinderrollos“ habe ich von dir als Romans Rollo und Marius Rollo gelernt."
    )
    assert "Kinderrollos" in (await teach.intercept("Welche Begriffe kennst du?") or "")


# --- Korrekturen ---


async def test_a_correction_applies_the_new_word_to_the_last_devices(tmp_path: Path) -> None:
    service, backend, teach = make(tmp_path)
    await service.command("Romans Rollo", "up")
    await service.command("Marius Rollo", "up")
    backend.sent.clear()
    reply = await teach.intercept("Ähm, bitte schließen, meinte ich.")
    assert backend.sent == [("roman", "down"), ("marius", "down")]
    assert reply == "Okay, Romans Rollo fährt runter.\nOkay, Marius Rollo fährt runter."


async def test_a_correction_without_a_recent_command_does_nothing(tmp_path: Path) -> None:
    _, backend, teach = make(tmp_path)
    reply = await teach.intercept("Bitte schließen, meinte ich")
    assert backend.sent == [] and "nicht, welches Gerät" in (reply or "")


async def test_a_correction_never_touches_doors(tmp_path: Path) -> None:
    service, backend, teach = make(tmp_path)
    service.recent = [("tuer", "unlock", __import__("time").monotonic(), None)]
    reply = await teach.intercept("Bitte schließen, meinte ich")
    assert backend.sent == [] and "vollständigen Befehl" in (reply or "")


async def test_a_correction_with_a_number_sets_the_percentage(tmp_path: Path) -> None:
    service, backend, teach = make(tmp_path)
    await service.command("Romans Rollo", "up")
    backend.sent.clear()
    await teach.intercept("Nein, auf 30 Prozent meinte ich")
    assert backend.sent == [("roman", "30")]


# --- Merken und Füllsätze ---


async def test_remember_stores_a_note_without_the_model(tmp_path: Path) -> None:
    _, _, teach = make(tmp_path)
    reply = await teach.intercept(
        "rollo schließen entspricht 100 prozent und rollo öffnen 0 prozent, merk dir das"
    )
    assert reply is not None and reply.startswith("Okay, ich habe mir gemerkt:")
    assert "0 Prozent ist offen" in reply
    reply = await teach.intercept("Merk dir, dass die Terrassenlampen abends an sein sollen")
    assert reply == "Okay, ich habe mir gemerkt: die Terrassenlampen abends an sein sollen."
    notes = teach._memory.store.all()
    assert {n.topic for n in notes} == {"wortschatz", "allgemein"}
    # Persönliche Fakten überlässt es dem Modell (dritte Person, siehe memory_write).
    assert await teach.intercept("Merk dir, dass ich abends gern Tee trinke") is None


async def test_secrets_are_not_remembered(tmp_path: Path) -> None:
    _, _, teach = make(tmp_path)
    reply = await teach.intercept("Merk dir, das WLAN Passwort ist hunter2geheim")
    assert reply is not None and "Passwort" in reply and teach._memory.store.all() == []


async def test_a_user_filler_is_added_to_the_right_kind(tmp_path: Path) -> None:
    _, _, teach = make(tmp_path)
    reply = await teach.intercept(
        "nehme folgenden Füllsatz mit auf: Einen Moment, ist gleich erledigt (bei Schalten)"
    )
    assert reply == "Okay, neuer Füllsatz (Schalten): „Einen Moment, ist gleich erledigt.“"
    rows = {r["text"]: r for r in teach._fillers.listing()}
    row = rows["Einen Moment, ist gleich erledigt."]
    assert row["category"] == "control" and row["source"] == "user"
    again = await teach.intercept("Nimm folgenden Füllsatz auf: Einen Moment, ist gleich erledigt")
    assert again == "Diesen Füllsatz kenne ich schon."
    assert "Welchen Füllsatz" in (await teach.intercept("Nimm einen Füllsatz auf") or "")


def test_user_filler_checks() -> None:
    assert user_phrase("Ich bin gleich da") == "Ich bin gleich da."
    assert user_phrase("") is None and user_phrase("Zu 5 Zahlen") is None
    assert (
        user_phrase("Ein sehr langer Satz mit viel zu vielen Wörtern darin wirklich viele") is None
    )


# --- im Dialog ---


async def test_explanations_never_reach_the_model_and_cost_no_time(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, data_dir=tmp_path, plugins="", learn=False, people=False, filler=False
    )
    state = AppState(settings)
    service, backend, _ = make(tmp_path)
    state.devices = service
    state.devices.lexicon = state.lexicon
    state.teach._devices = service

    class NoModel:
        async def reply(self, history, spoken=False, room=None):  # type: ignore[no-untyped-def]
            raise AssertionError("darf nicht aufgerufen werden")
            yield ""

    state.responder = NoModel()

    async def emit(_: object) -> None: ...

    state.emit = emit  # type: ignore[method-assign]
    reply = await handle_user_text(state, "Mit Dach-Rollo meine ich Rollo Roman und Rollo Marius.")
    assert reply.text.startswith("Okay, ab jetzt verstehe ich") and reply.fastpath
    assert backend.sent == [] and [m.tooled for m in state.chat] == [True, True]


async def test_an_unknown_device_word_offers_to_learn_it(tmp_path: Path) -> None:
    service, backend, _ = make(tmp_path)
    registry = ToolRegistry()
    for tool in build_device_tools(service):
        registry.register(tool)
    provider = FakeProvider([TextDelta("S|Deckenrollos|down")])
    agent = Agent(provider, registry, lambda: "SYSTEM", hidden_tools=COMPACT_HIDDEN)

    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    ctx.device_related = True
    out = "".join(
        [
            d
            async for d in agent.run(
                [{"role": "user", "content": "Mach bitte alle Deckenrollos zu"}], ctx
            )
        ]
    )
    assert "„Deckenrollos“ kenne ich nicht" in out and "Mit Deckenrollos meine ich" in out
    assert backend.sent == [] and len(provider.calls) == 1  # kein zweiter Modellschritt
    assert ToolCall  # Import für Lesbarkeit


# --- Rückgängig, Entschuldigung, Gruppenfrage ---


async def test_undo_restores_the_state_before_the_last_command(tmp_path: Path) -> None:
    service, backend, teach = make(tmp_path)
    service.seed_states("openhab", {"R": RawState("0"), "M": RawState("0")})
    await service.command("Romans Rollo", "down")
    await service.command("Marius Rollo", "down")
    backend.sent.clear()
    reply = await teach.intercept("Mach das bitte rückgängig")
    assert backend.sent == [("roman", "0"), ("marius", "0")]
    assert reply == "Okay, Romans Rollo ist offen.\nOkay, Marius Rollo ist offen."


async def test_a_complaint_offers_to_undo_and_waits_for_the_answer(tmp_path: Path) -> None:
    service, backend, teach = make(tmp_path)
    service.seed_states("openhab", {"R": RawState("0")})
    await service.command("Romans Rollo", "down")
    backend.sent.clear()
    reply = await teach.intercept("Aber ich hab doch nie gesagt, dass du das Rollo öffnen sollst.")
    assert reply is not None and "Missverständnis" in reply and "Soll ich das rückgängig" in reply
    assert backend.sent == []  # erst fragen
    assert await teach.intercept("Ja") == "Okay, Romans Rollo ist offen."
    assert backend.sent == [("roman", "0")]
    # Nein: nichts passiert
    await service.command("Romans Rollo", "down")
    backend.sent.clear()
    await teach.intercept("Das wollte ich nicht")
    assert await teach.intercept("Nein") == "Okay, ich lasse es so." and backend.sent == []


async def test_a_complaint_without_a_recent_command_just_apologises(tmp_path: Path) -> None:
    _, backend, teach = make(tmp_path)
    reply = await teach.intercept("Das war falsch")
    assert reply == "Entschuldige, das war ein Missverständnis. Ich habe zuletzt nichts geschaltet."
    assert await teach.intercept("Mach das rückgängig") == (
        "Ich weiß gerade nicht, was ich rückgängig machen soll."
    )
    assert backend.sent == []


async def test_a_group_word_after_g_lists_the_matching_devices(tmp_path: Path) -> None:
    from tests.test_speed import compact_agent, run

    service, _, _ = make(tmp_path)
    service.seed_states("openhab", {"L": RawState("OFF"), "TL": RawState("ON")})
    lights = [i for i in service.snapshot() if i.type == "light"]
    service.search = lambda query, limit=20: lights  # type: ignore[method-assign]
    provider = FakeProvider([TextDelta("G|Beleuchtungen")])  # kein einzelnes Gerät
    out, _ = await run(compact_agent(service, provider), "Welche Lichter sind an?", True)
    assert out == "Zu „Beleuchtungen“ gibt es: Deckenlicht Roman (aus), Terrassenlicht (an)."
