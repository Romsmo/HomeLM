import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from cat.agent.tools import ToolContext, ToolError
from cat.audit import AuditLog, redact
from cat.devices.allowlist import EXAMPLE, load_allowlist, parse_allowlist
from cat.devices.commands import DeviceError, normalize_command
from cat.devices.confirm import ConfirmManager
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.devices.tools import build_device_tools
from cat.stage.store import StageStore
from cat.ws.protocol import ConfirmRequest, ServerEvent, StageShow

YAML = """
devices:
  - {id: licht, backend: openhab, item: Licht, name: Wohnzimmer Licht, room: Wohnzimmer, type: light, test: true, synonyms: [Stehlampe]}
  - {id: dimmer, backend: openhab, item: Dimmer, name: Leselampe, room: Wohnzimmer, type: dimmer}
  - {id: rollo, backend: openhab, item: Rollo, name: Rollladen, room: Wohnzimmer, type: shutter}
  - {id: heizung, backend: openhab, item: Heizung, name: Heizung, room: Wohnzimmer, type: thermostat}
  - {id: temp, backend: openhab, item: Temp, name: Temperatur, room: Wohnzimmer, type: sensor}
  - {id: tuer, backend: openhab, item: Tuer, name: Haustür, room: Flur, type: lock, risk: low}
  - {id: garage, backend: openhab, item: Garage, name: Garagentor, room: Garage, type: garage, test: true}
  - {id: kuechenlicht, backend: openhab, item: KL, name: Küche Licht, room: Küche, type: light}
  - {id: kuechenlicht2, backend: openhab, item: KL2, name: Küche Licht, room: Küche, type: light}
"""


class FakeBackend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.states: dict[str, RawState] = {}
        self.fail_read = False

    async def read(self, spec: DeviceSpec) -> RawState:
        if self.fail_read:
            raise DeviceError("weg")
        return self.states.get(spec.item, RawState("OFF"))

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.id, command))
        self.states[spec.item] = RawState(command.upper())


class Harness:
    def __init__(self, tmp_path: Path, control: str = "full", clients: bool = True) -> None:
        self.events: list[ServerEvent] = []
        self.audit_path = tmp_path / "audit.jsonl"
        self.audit = AuditLog(self.audit_path)
        self.has_clients = clients
        self.confirm = ConfirmManager(self.emit, lambda: self.has_clients, timeout_s=0.3)
        self.backend = FakeBackend()
        self.service = DeviceService(
            parse_allowlist(YAML),
            control,  # type: ignore[arg-type]
            self.emit,
            self.audit,
            self.confirm,
        )
        self.service.settle_delay = 0
        self.service.register_backend("openhab", self.backend)

    async def emit(self, event: ServerEvent) -> None:
        self.events.append(event)

    def audit_lines(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(x) for x in self.audit_path.read_text(encoding="utf-8").splitlines()]

    async def approve_when_asked(self, approved: bool) -> None:
        for _ in range(100):
            req = next((e for e in self.events if isinstance(e, ConfirmRequest)), None)
            if req:
                self.confirm.resolve(req.id, approved)
                return
            await asyncio.sleep(0.01)


# --- Allowlist ---


def test_allowlist_parses_and_applies_risk_floor() -> None:
    result = parse_allowlist(YAML)
    assert result.error is None and len(result.specs) == 9
    door = result.by_id("tuer")
    assert door is not None and door.risk == "low" and door.effective_risk == "high"
    assert result.by_id("rollo").effective_risk == "medium"  # type: ignore[union-attr]
    assert result.by_id("licht").effective_risk == "low"  # type: ignore[union-attr]


def test_allowlist_can_raise_but_not_lower_risk() -> None:
    text = "devices:\n  - {id: l, backend: openhab, item: L, name: L, room: R, type: light, risk: high}"
    assert parse_allowlist(text).specs[0].effective_risk == "high"


@pytest.mark.parametrize(
    "text",
    [
        "devices: 5",
        "devices:\n  - {id: 'Gross!', backend: openhab, item: x, name: x, room: r, type: light}",
        "devices:\n  - {id: a, backend: openhab, item: x, name: x, room: r, type: ufo}",
        "devices:\n  - {id: a, backend: openhab, item: x, name: x, room: r, type: light, extra: 1}",
        "devices:\n  - {id: a, backend: openhab, item: x, name: x, room: r, type: light}\n"
        "  - {id: a, backend: openhab, item: y, name: y, room: r, type: light}",
        "{kaputt: [",
    ],
)
def test_invalid_allowlist_fails_closed(text: str) -> None:
    result = parse_allowlist(text)
    assert result.specs == [] and result.error


def test_missing_file_means_no_devices_and_example_is_valid(tmp_path: Path) -> None:
    assert load_allowlist(tmp_path / "nope.yaml").specs == []
    assert parse_allowlist(EXAMPLE).error is None


# --- Befehle ---


def spec_of(device_id: str) -> DeviceSpec:
    result = parse_allowlist(YAML).by_id(device_id)
    assert result is not None
    return result


@pytest.mark.parametrize(
    ("device", "raw", "expected"),
    [
        ("licht", "an", "on"),
        ("licht", " AUS ", "off"),
        ("dimmer", "75", "75"),
        ("dimmer", "50%", "50"),
        ("rollo", "runter", "down"),
        ("rollo", "30", "30"),
        ("heizung", "21,5", "21.5"),
        ("tuer", "unlock", "unlock"),
        ("garage", "auf", "open"),
        ("rollo", "open", "up"),
    ],
)
def test_normalize_command_ok(device: str, raw: str, expected: str) -> None:
    assert normalize_command(spec_of(device), raw) == expected


@pytest.mark.parametrize(
    ("device", "raw"),
    [
        ("licht", "75"),
        ("dimmer", "150"),
        ("heizung", "99"),
        ("heizung", "heiß"),
        ("temp", "on"),
        ("tuer", "on"),
    ],
)
def test_normalize_command_rejects(device: str, raw: str) -> None:
    with pytest.raises(DeviceError):
        normalize_command(spec_of(device), raw)


# --- Modi ---


async def test_readonly_mode_blocks_all_control(tmp_path: Path) -> None:
    h = Harness(tmp_path, control="readonly")
    with pytest.raises(DeviceError, match="ausgeschaltet"):
        await h.service.command("licht", "on")
    assert h.backend.sent == []
    assert not any(i.controllable for i in h.service.snapshot())


async def test_test_mode_only_allows_test_devices(tmp_path: Path) -> None:
    h = Harness(tmp_path, control="test")
    assert "gesendet" in await h.service.command("licht", "on")
    with pytest.raises(DeviceError, match="kein Testgerät"):
        await h.service.command("rollo", "up")
    assert h.backend.sent == [("licht", "on")]
    controllable = {i.id for i in h.service.snapshot() if i.controllable}
    assert controllable == {"licht", "garage"}


async def test_full_mode_controls_low_and_medium_without_confirmation(tmp_path: Path) -> None:
    h = Harness(tmp_path, control="full")
    await h.service.command("licht", "on")
    await h.service.command("rollo", "down")
    assert h.backend.sent == [("licht", "on"), ("rollo", "down")]
    assert not any(isinstance(e, ConfirmRequest) for e in h.events)


# --- Bestätigung bei high (im Backend erzwungen) ---


async def test_high_risk_runs_only_after_approval(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    task = asyncio.create_task(h.service.command("tuer", "unlock", source="agent"))
    await h.approve_when_asked(True)
    assert "gesendet" in await task
    assert h.backend.sent == [("tuer", "unlock")]
    req = next(e for e in h.events if isinstance(e, ConfirmRequest))
    assert "Haustür" in req.summary and req.device == "tuer"
    assert any(x["tool"] == "confirm" and x["ok"] for x in h.audit_lines())


async def test_high_risk_denied_never_reaches_backend(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    task = asyncio.create_task(h.service.command("garage", "open"))
    await h.approve_when_asked(False)
    with pytest.raises(DeviceError, match="Bestätigung"):
        await task
    assert h.backend.sent == []
    assert any(x["tool"] == "confirm" and not x["ok"] for x in h.audit_lines())


async def test_high_risk_timeout_never_reaches_backend(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    with pytest.raises(DeviceError, match="Bestätigung"):
        await h.service.command("tuer", "unlock")
    assert h.backend.sent == []


async def test_high_risk_without_connected_ui_is_refused(tmp_path: Path) -> None:
    h = Harness(tmp_path, clients=False)
    with pytest.raises(DeviceError):
        await h.service.command("tuer", "unlock")
    assert h.backend.sent == [] and h.events == []


async def test_confirmation_ids_are_single_use_and_unforgeable(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    task = asyncio.create_task(h.service.command("tuer", "unlock"))
    for _ in range(100):
        if any(isinstance(e, ConfirmRequest) for e in h.events):
            break
        await asyncio.sleep(0.01)
    req = next(e for e in h.events if isinstance(e, ConfirmRequest))
    assert h.confirm.resolve("erfunden", True) is False
    assert h.backend.sent == []
    assert h.confirm.resolve(req.id, False) is True
    assert h.confirm.resolve(req.id, True) is False  # zweite Antwort zählt nicht
    with pytest.raises(DeviceError):
        await task
    assert h.backend.sent == []
    assert h.confirm.resolve(req.id, True) is False  # nach Abschluss ebenfalls nicht


async def test_confirmation_requested_for_every_command_on_high_devices(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    for command in ("close", "stop"):
        h.events.clear()
        task = asyncio.create_task(h.service.command("garage", command))
        await h.approve_when_asked(False)
        with pytest.raises(DeviceError):
            await task
        assert any(isinstance(e, ConfirmRequest) for e in h.events)
    assert h.backend.sent == []


# --- Auflösen, Lesen ---


async def test_resolve_by_id_name_synonym_and_ambiguity(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert h.service.resolve("licht").id == "licht"
    assert h.service.resolve("Wohnzimmer Licht").id == "licht"
    assert h.service.resolve("stehlampe").id == "licht"
    with pytest.raises(DeviceError, match="mehrdeutig"):
        h.service.resolve("Küche Licht")
    with pytest.raises(DeviceError, match="nicht freigegeben"):
        h.service.resolve("Keller Pumpe")


async def test_states_offline_and_change_events(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.backend.states["Temp"] = RawState("21.5", "°C")
    await h.service.refresh_all()
    temp = next(i for i in h.service.snapshot() if i.id == "temp")
    assert (temp.state, temp.unit, temp.online) == ("21.5", "°C", True)
    await h.service.on_state_change("openhab", "Temp", RawState("22", "°C"))
    assert next(i for i in h.service.snapshot() if i.id == "temp").state == "22"
    h.backend.fail_read = True
    info = await h.service.get_state("temp")
    assert info.online is False
    await h.service.set_offline("openhab")
    assert all(not i.online for i in h.service.snapshot())
    assert [i.id for i in h.service.snapshot("flur")] == ["tuer"]


# --- Werkzeuge ---


def tool_ctx(h: Harness) -> ToolContext:
    return ToolContext(emit=h.emit, stage=StageStore())


async def test_tools_list_get_set_and_show(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    tools = {t.name: t for t in build_device_tools(h.service)}
    ctx = tool_ctx(h)
    listing = await tools["list_devices"].handler({}, ctx)
    assert "Wohnzimmer Licht" in listing and "Risiko high" in listing
    assert "Keine" not in await tools["list_devices"].handler({"room": "Flur"}, ctx)
    assert "Haustür" in await tools["list_devices"].handler({"room": "flur"}, ctx)
    assert "Wohnzimmer Licht" in await tools["get_state"].handler({"device": "licht"}, ctx)
    assert "gesendet" in await tools["set_state"].handler({"device": "licht", "command": "on"}, ctx)
    with pytest.raises(ToolError, match="nicht freigegeben"):
        await tools["set_state"].handler({"device": "Keller Pumpe", "command": "on"}, ctx)
    with pytest.raises(ToolError, match="Parameter"):
        await tools["set_state"].handler({"device": "licht"}, ctx)
    await tools["show_devices"].handler({"room": "Wohnzimmer"}, ctx)
    shown = [e for e in h.events if isinstance(e, StageShow)]
    assert shown and shown[0].item.kind == "devices" and shown[0].item.content == "Wohnzimmer"


async def test_empty_allowlist_tells_model_there_are_no_devices(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.service._allowlist.specs.clear()
    h.service._rebuild()
    out = await {t.name: t for t in build_device_tools(h.service)}["list_devices"].handler(
        {}, tool_ctx(h)
    )
    assert "keine Geräte" in out


# --- Audit ---


def test_redact_masks_secrets_and_truncates() -> None:
    out = redact({"api_key": "sk-1", "html": "x" * 1000, "nested": {"Password": "p", "ok": 1}})
    assert out["api_key"] == "***" and out["nested"]["Password"] == "***"
    assert out["nested"]["ok"] == 1 and "1000 Zeichen" in out["html"]
    assert len(out["html"]) < 400


async def test_audit_log_writes_json_lines(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "sub" / "a.jsonl")
    await audit.record("show_html", {"html": "<p/>", "token": "geheim"}, "ok", source="agent")
    await audit.record("set_state", {"device": "x"}, "Fehler", ok=False, source="ui")
    lines = [json.loads(x) for x in (tmp_path / "sub" / "a.jsonl").read_text().splitlines()]
    assert [x["tool"] for x in lines] == ["show_html", "set_state"]
    assert lines[0]["params"]["token"] == "***" and lines[1]["ok"] is False
    assert {"ts", "source", "tool", "params", "ok", "result"} <= lines[0].keys()


async def test_audit_failure_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "datei"
    blocker.write_text("x")
    await AuditLog(blocker / "a.jsonl").record("t", {}, "r")  # Elternpfad ist eine Datei


def test_example_allowlist_in_docs_is_valid() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "devices.example.yaml"
    result = parse_allowlist(path.read_text(encoding="utf-8"))
    assert result.error is None and len(result.specs) >= 5
