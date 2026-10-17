import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cat.agent.responder import build_responder
from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import Allowlist, parse_allowlist
from cat.devices.confirm import ConfirmManager
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.intents.fastpath import FastPath
from cat.intents.text import number_word, parse_number, tokenize
from cat.intents.vocabulary import load_vocabulary
from cat.llm.base import TextDelta
from cat.main import create_app
from cat.ws.protocol import ServerEvent
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider
from tests.helpers import drain_replay

YAML = """
devices:
  - {id: wz_decke, backend: openhab, item: WzDecke, name: Deckenlicht, room: Wohnzimmer, type: light}
  - {id: wz_lese, backend: openhab, item: WzLese, name: Leselampe, room: Wohnzimmer, type: dimmer, synonyms: [Stehlampe]}
  - {id: wz_rollo, backend: openhab, item: WzRollo, name: Rollladen Wohnzimmer, room: Wohnzimmer, type: shutter}
  - {id: wz_heiz, backend: openhab, item: WzHeiz, name: Heizung Wohnzimmer, room: Wohnzimmer, type: thermostat}
  - {id: wz_temp, backend: openhab, item: WzTemp, name: Temperatur Wohnzimmer, room: Wohnzimmer, type: sensor}
  - {id: k_licht, backend: openhab, item: KLicht, name: Küchenlicht, room: Küche, type: light}
  - {id: k_temp, backend: openhab, item: KTemp, name: Küche Temperatur, room: Küche, type: sensor}
  - {id: sz_licht, backend: openhab, item: SzLicht, name: Schlafzimmerlicht, room: Schlafzimmer, type: light}
  - {id: sz_rollo, backend: openhab, item: SzRollo, name: Rollo Schlafzimmer, room: Schlafzimmer, type: shutter}
  - {id: t_lampen, backend: openhab, item: TLampen, name: Terrassenlampen, room: Terrasse, type: dimmer}
  - {id: t_temp, backend: openhab, item: TTemp, name: Außentemperatur, room: Terrasse, type: sensor}
  - {id: garage, backend: openhab, item: Garage, name: Garagentor, room: Garage, type: garage}
  - {id: haustuer, backend: openhab, item: Tuer, name: Haustür, room: Flur, type: lock, command_map: {lock: "ON", unlock: "OFF"}}
"""

STATES = {
    "KLicht": RawState("OFF"),
    "KTemp": RawState("21.5", "°C"),
    "WzTemp": RawState("22", "°C"),
    "TTemp": RawState("12.6", "°C"),
    "WzRollo": RawState("100"),
    "Garage": RawState("closed"),
    "Tuer": RawState("locked"),
    "TLampen": RawState("100", "%"),
}


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec: DeviceSpec) -> RawState:
        return STATES.get(spec.item, RawState("OFF"))

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.id, command))


def make_fastpath(
    allowlist: Allowlist | None = None, control: str = "full"
) -> tuple[FastPath, Backend, DeviceService]:
    events: list[ServerEvent] = []

    async def emit(event: ServerEvent) -> None:
        events.append(event)

    service = DeviceService(
        allowlist or parse_allowlist(YAML),
        control,  # type: ignore[arg-type]
        emit,
        AuditLog(None),
        ConfirmManager(emit, lambda: False),
    )
    service.settle_delay = 0
    backend = Backend()
    service.register_backend("openhab", backend)
    return FastPath(service, load_vocabulary()), backend, service


# --- Texthilfen ---


def test_tokenize_folds_umlauts_and_punctuation() -> None:
    assert tokenize("Mach das Licht in der Küche an!") == [
        "mach",
        "das",
        "licht",
        "in",
        "der",
        "kueche",
        "an",
    ]
    assert tokenize("21,5 Grad, 50%") == ["21,5", "grad", "50", "%"]


@pytest.mark.parametrize(
    ("word", "value"),
    [("null", 0), ("fuenf", 5), ("zwoelf", 12), ("zwanzig", 20), ("einundzwanzig", 21),
     ("neunundneunzig", 99), ("hundert", 100), ("haus", None), ("einundhaus", None)],
)  # fmt: skip
def test_number_words(word: str, value: int | None) -> None:
    assert number_word(word) == value


def test_parse_number_handles_digits_and_words() -> None:
    assert parse_number("21,5") == 21.5 and parse_number("fuenfzig") == 50.0
    assert parse_number("licht") is None


# --- Satzmuster (Parser + Zuordnung, ohne Netzwerk) ---

# (Satz, erwartetes Gerät, erwarteter Befehl bzw. Art)
SET_CASES = [
    ("Mach das Licht in der Küche an", "k_licht", "on"),
    ("Licht Küche aus", "k_licht", "off"),
    ("Schalte das Küchenlicht ein", "k_licht", "on"),
    ("Küchenlicht aus", "k_licht", "off"),
    ("ähm mach mal bitte das Licht im Schlafzimmer aus", "sz_licht", "off"),
    ("Schlafzimmerlicht aus", "sz_licht", "off"),
    ("Kannst du bitte die Lampe im Schlafzimmer anmachen", "sz_licht", "on"),
    ("Hey Cat, schalte doch mal das Licht im Schlafzimmer an", "sz_licht", "on"),
    ("also äh mach das Schlafzimmerlicht bitte mal kurz aus", "sz_licht", "off"),
    ("Mach die Leselampe auf 40 Prozent", "wz_lese", "40"),
    ("Dimme die Terrassenlampen auf fünfzig Prozent", "t_lampen", "50"),
    ("Terrassenlampen an", "t_lampen", "on"),
    ("Mach die Terrassenlampen auf 30 Prozent", "t_lampen", "30"),
    ("Rollladen im Wohnzimmer hoch", "wz_rollo", "up"),
    ("Fahre den Rollladen im Wohnzimmer runter", "wz_rollo", "down"),
    ("Rollo Schlafzimmer zu", "sz_rollo", "down"),
    ("Mach das Rollo im Schlafzimmer auf", "sz_rollo", "up"),
    ("Rollo im Schlafzimmer auf 30 Prozent", "sz_rollo", "30"),
    ("Stopp den Rollladen im Wohnzimmer", "wz_rollo", "stop"),
    ("Stelle die Heizung im Wohnzimmer auf einundzwanzig Grad", "wz_heiz", "21"),
    ("Heizung Wohnzimmer auf 22,5 Grad", "wz_heiz", "22.5"),
    ("Mach die Stehlampe an", "wz_lese", "on"),
    ("Mach das Deckenlicht im Wohnzimmer an", "wz_decke", "on"),
    ("Mach die Garage zu", "garage", "down"),
    ("Garagentor auf", "garage", "up"),
    ("Haustür verriegeln", "haustuer", "lock"),
    ("Haustür aufschließen", "haustuer", "unlock"),
]


@pytest.mark.parametrize(("text", "device", "command"), SET_CASES)
def test_set_sentences(text: str, device: str, command: str) -> None:
    fp, _, _ = make_fastpath()
    matched = fp.match(text)
    assert matched is not None, text
    parsed, spec = matched
    assert (spec.id, parsed.command, parsed.kind) == (device, command, "set"), text


QUERY_CASES = [
    ("Wie warm ist es im Wohnzimmer", "wz_temp"),
    ("Wie warm ist es draußen", "t_temp"),
    ("Temperatur in der Küche", "k_temp"),
    ("Wie kalt ist es auf der Terrasse", "t_temp"),
    ("Ist das Licht in der Küche an", "k_licht"),
    ("Ist das Küchenlicht aus", "k_licht"),
    ("Ist die Garage offen", "garage"),
    ("Ist die Haustür verriegelt", "haustuer"),
    ("Wie ist der Zustand der Haustür", "haustuer"),
    ("Ist der Rollladen im Wohnzimmer zu", "wz_rollo"),
]


@pytest.mark.parametrize(("text", "device"), QUERY_CASES)
def test_query_sentences(text: str, device: str) -> None:
    fp, _, _ = make_fastpath()
    matched = fp.match(text)
    assert matched is not None, text
    parsed, spec = matched
    assert spec.id == device and parsed.kind in ("query", "temperature"), text


# Nicht eindeutig oder kein Gerätebefehl: der Agent übernimmt (kein Raten).
FALLTHROUGH = [
    "Wie wird das Wetter morgen",
    "Erzähl mir einen Witz",
    "Mach das Licht an",  # mehrere Lichter, kein Raum
    "Mach das Licht im Wohnzimmer an",  # Deckenlicht oder Leselampe?
    "Mach das Licht im Keller an",  # Raum ist nicht freigegeben
    "Schalte den Fernseher ein",
    "ähm",
    "",
    "Licht an und Licht aus",
    "Was ist die Hauptstadt von Frankreich",
    "Mach es wärmer",
]


@pytest.mark.parametrize("text", FALLTHROUGH)
def test_fallthrough_sentences_return_none(text: str) -> None:
    fp, _, _ = make_fastpath()
    assert fp.match(text) is None, text


def test_default_room_resolves_unspecific_commands() -> None:
    fp, _, _ = make_fastpath()
    assert fp.match("Mach das Licht an") is None
    matched = fp.match("Mach das Licht an", default_room="Küche")
    assert matched is not None and matched[1].id == "k_licht"
    # Ein genannter Raum schlägt den Standardraum.
    matched = fp.match("Mach das Licht im Schlafzimmer an", default_room="Küche")
    assert matched is not None and matched[1].id == "sz_licht"


def test_no_devices_means_no_fastpath() -> None:
    fp, _, _ = make_fastpath(Allowlist())
    assert fp.match("Mach das Licht an") is None


def test_user_synonyms_extend_vocabulary(tmp_path: Path) -> None:
    user = tmp_path / "synonyms.yaml"
    user.write_text(
        "classes:\n  light: [funzel]\nrooms:\n  kueche: [kochnische]\n", encoding="utf-8"
    )
    fp, _, service = make_fastpath()
    fp = FastPath(service, load_vocabulary(user))
    matched = fp.match("Mach den Funzel in der Kochnische an")
    assert matched is not None and matched[1].id == "k_licht"


def test_broken_user_synonyms_are_ignored(tmp_path: Path) -> None:
    user = tmp_path / "synonyms.yaml"
    user.write_text("{kaputt: [", encoding="utf-8")
    assert load_vocabulary(user).classes["light"]


# --- Ausführung und Antworten ---


@pytest.mark.parametrize(
    ("text", "answer", "sent"),
    [
        ("Mach das Licht in der Küche an", "Okay, Küchenlicht ist an.", [("k_licht", "on")]),
        ("Küchenlicht aus", "Okay, Küchenlicht ist aus.", [("k_licht", "off")]),
        ("Dimme die Terrassenlampen auf fünfzig Prozent", "Okay, Terrassenlampen steht auf 50 Prozent.", [("t_lampen", "50")]),
        ("Rollladen im Wohnzimmer hoch", "Okay, Rollladen Wohnzimmer fährt hoch.", [("wz_rollo", "up")]),
        ("Heizung Wohnzimmer auf 22,5 Grad", "Okay, Heizung Wohnzimmer ist auf 22,5 Grad gestellt.", [("wz_heiz", "22.5")]),
        ("Rollo im Schlafzimmer auf 30 Prozent", "Okay, Rollo Schlafzimmer ist auf 30 Prozent zu.", [("sz_rollo", "30")]),
    ],
)  # fmt: skip
async def test_handle_executes_and_answers(
    text: str, answer: str, sent: list[tuple[str, str]]
) -> None:
    fp, backend, _ = make_fastpath()
    result = await fp.handle(text)
    assert result is not None and result.text == answer
    assert backend.sent == sent


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Wie warm ist es im Wohnzimmer", "Temperatur Wohnzimmer im Raum Wohnzimmer: 22 °C."),
        ("Temperatur in der Küche", "Küche Temperatur im Raum Küche: 21,5 °C."),
        ("Wie warm ist es draußen", "Außentemperatur im Raum Terrasse: 12,6 °C."),
        ("Ist das Licht in der Küche an", "Küchenlicht ist aus."),
        ("Ist der Rollladen im Wohnzimmer zu", "Rollladen Wohnzimmer ist zu."),
        ("Ist die Haustür verriegelt", "Haustür: verriegelt"),
    ],
)
async def test_handle_answers_queries(text: str, answer: str) -> None:
    fp, backend, _ = make_fastpath()
    result = await fp.handle(text)
    assert result is not None and result.text == answer
    assert backend.sent == []


async def test_handle_reports_readonly_and_high_risk_without_executing() -> None:
    fp, backend, _ = make_fastpath(control="readonly")
    result = await fp.handle("Mach das Licht in der Küche an")
    assert result is not None and "nur lesen" in result.text and backend.sent == []

    fp, backend, _ = make_fastpath(control="full")
    result = await fp.handle("Haustür aufschließen")  # high: ohne Oberfläche keine Bestätigung
    assert result is not None and "Bestätigung" in result.text and backend.sent == []


async def test_handle_returns_none_for_unmatched_text() -> None:
    fp, backend, _ = make_fastpath()
    assert await fp.handle("Erzähl mir einen Witz") is None and backend.sent == []


# --- Geschwindigkeit ---


def test_matching_is_fast_even_with_hundreds_of_devices() -> None:
    lines = ["devices:"]
    for i in range(300):
        room = ["Wohnzimmer", "Küche", "Bad", "Flur", "Keller"][i % 5]
        lines.append(
            f"  - {{id: d{i}, backend: openhab, item: I{i}, name: 'Gerät Nummer {i}', room: {room}, type: light}}"
        )
    lines.append(
        "  - {id: ziel, backend: openhab, item: Ziel, name: Schlafzimmerlicht, room: Schlafzimmer, type: light}"
    )
    fp, _, _ = make_fastpath(parse_allowlist("\n".join(lines)))
    sentences = [text for text, *_ in SET_CASES[:10]] + [t for t, _ in QUERY_CASES]
    fp.match("Schlafzimmerlicht an")  # Warmlauf
    start = time.perf_counter()
    runs = 0
    for _ in range(5):
        for text in sentences:
            fp.match(text)
            runs += 1
    average_ms = (time.perf_counter() - start) / runs * 1000
    assert average_ms < 25, f"Zuordnung zu langsam: {average_ms:.1f} ms im Mittel"
    one = time.perf_counter()
    assert fp.match("Mach das Licht im Schlafzimmer an") is not None
    assert (time.perf_counter() - one) * 1000 < 100


# --- Ende zu Ende: kein LLM-Aufruf ---


def test_light_command_runs_without_llm_over_websocket(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "devices.yaml").write_text(YAML, encoding="utf-8")
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        device_control="full",
    )
    app = create_app(settings)
    backend = Backend()
    app.state.cat.devices.register_backend("openhab", backend)
    app.state.cat.devices.settle_delay = 0
    provider = FakeProvider([TextDelta("LLM darf hier nicht antworten")])
    app.state.cat.responder = build_responder(app.state.cat, provider)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        with client.websocket_connect("/ws") as ws:
            drain_replay(ws)
            ws.send_text(
                json.dumps({"type": "chat.message", "text": "Mach das Licht in der Küche an"})
            )
            seen: list[dict] = []
            while not any(e["type"] == "chat.done" for e in seen):
                seen.append(json.loads(ws.receive_text()))
            answer = next(
                e for e in seen if e["type"] == "chat.message" and e["role"] == "assistant"
            )
            assert answer["text"] == "Okay, Küchenlicht ist an."
            # Unklarer Satz geht dagegen an den LLM.
            ws.send_text(
                json.dumps({"type": "chat.message", "text": "Erzähl mir etwas über Katzen"})
            )
            more: list[dict] = []
            while not any(e["type"] == "chat.done" for e in more):
                more.append(json.loads(ws.receive_text()))
    assert backend.sent == [("k_licht", "on")]
    assert len(provider.calls) == 1  # nur der zweite Satz
    audit = [
        json.loads(x) for x in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(x["source"] == "fastpath" and x["tool"] == "fastpath" for x in audit)
