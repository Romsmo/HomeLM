import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.devices.models import DeviceSpec
from cat.devices.service import RawState
from cat.llm.base import TextDelta, ToolCall
from cat.main import create_app
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider
from tests.helpers import drain_replay

YAML = """
devices:
  - {id: licht, backend: openhab, item: Licht, name: Testlampe, room: Wohnzimmer, type: light, test: true}
  - {id: rollo, backend: openhab, item: Rollo, name: Rollladen, room: Wohnzimmer, type: shutter}
  - {id: tuer, backend: openhab, item: Tuer, name: Haustür, room: Flur, type: lock, test: true}
"""


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec: DeviceSpec) -> RawState:
        return RawState("OFF")

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.id, command))


def make(tmp_path: Path, control: str) -> tuple[TestClient, Backend]:
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
        device_control=control,  # type: ignore[arg-type]
    )
    app = create_app(settings)
    backend = Backend()
    app.state.cat.devices.register_backend("openhab", backend)
    app.state.cat.devices.settle_delay = 0
    client = TestClient(app)
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return client, backend


def recv_until(ws: Any, type_: str, limit: int = 60) -> list[dict[str, Any]]:
    seen = []
    for _ in range(limit):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if event["type"] == type_:
            return seen
    raise AssertionError(f"{type_} nicht empfangen: {[e['type'] for e in seen]}")


def command(ws: Any, device: str, cmd: str) -> None:
    ws.send_text(json.dumps({"type": "device.command", "id": device, "command": cmd}))


def audit_lines(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "audit.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_device_list_on_connect_with_control_mode(tmp_path: Path) -> None:
    client, _ = make(tmp_path, "test")
    with client, client.websocket_connect("/ws") as ws:
        listing = next(e for e in drain_replay(ws) if e["type"] == "device.list")
        assert listing["control"] == "test" and listing["error"] is None
        devices = {d["id"]: d for d in listing["devices"]}
        assert set(devices) == {"licht", "rollo", "tuer"}
        assert devices["licht"]["controllable"] and not devices["rollo"]["controllable"]
        assert devices["tuer"]["risk"] == "high"


def test_readonly_mode_rejects_ui_command_and_logs_it(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "readonly")
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        command(ws, "licht", "on")
        error = recv_until(ws, "error")[-1]
        assert "nur lesen" in error["message"]
    assert backend.sent == []
    entry = audit_lines(tmp_path)[-1]
    assert (entry["source"], entry["tool"], entry["ok"]) == ("ui", "set_state", False)


def test_ui_command_on_test_device_works_and_updates_state(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "test")
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        command(ws, "licht", "on")
        event = recv_until(ws, "device.state")[-1]
        assert event["id"] == "licht"
    assert backend.sent == [("licht", "on")]
    assert audit_lines(tmp_path)[-1]["ok"] is True


def test_non_test_device_rejected_in_test_mode(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "test")
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        command(ws, "rollo", "up")
        assert "kein Testgerät" in recv_until(ws, "error")[-1]["message"]
    assert backend.sent == []


def test_ui_high_risk_needs_confirmation_over_websocket(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "test")
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        command(ws, "tuer", "unlock")
        request = recv_until(ws, "confirm.request")[-1]
        assert request["device"] == "tuer" and "Haustür" in request["summary"]
        assert backend.sent == []  # noch nichts passiert
        ws.send_text(json.dumps({"type": "confirm.response", "id": "falsch", "approved": True}))
        ws.send_text(
            json.dumps({"type": "confirm.response", "id": request["id"], "approved": True})
        )
        recv_until(ws, "confirm.resolved")
        recv_until(ws, "device.state")
    assert backend.sent == [("tuer", "unlock")]


def test_ui_high_risk_denied_over_websocket(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "test")
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        command(ws, "tuer", "unlock")
        request = recv_until(ws, "confirm.request")[-1]
        ws.send_text(
            json.dumps({"type": "confirm.response", "id": request["id"], "approved": False})
        )
        assert "Bestätigung" in recv_until(ws, "error")[-1]["message"]
    assert backend.sent == []


def test_agent_tool_calls_are_audited_and_high_risk_still_asks(tmp_path: Path) -> None:
    client, backend = make(tmp_path, "test")
    app = client.app
    app.state.cat.learner.enabled = False  # type: ignore[attr-defined]  # hier soll der Agent antworten
    provider = FakeProvider(
        [ToolCall("c1", "set_state", {"device": "tuer", "command": "unlock"})],
        [TextDelta("Das habe ich nicht geschafft.")],
    )
    app.state.cat.responder = build_responder(app.state.cat, provider)  # type: ignore[attr-defined]
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text(json.dumps({"type": "chat.message", "text": "Mach die Haustür auf"}))
        request = recv_until(ws, "confirm.request")[-1]
        ws.send_text(
            json.dumps({"type": "confirm.response", "id": request["id"], "approved": False})
        )
        recv_until(ws, "chat.done")
    assert backend.sent == []
    tools = [(x["source"], x["tool"], x["ok"]) for x in audit_lines(tmp_path)]
    assert ("confirm", False) == (tools[0][1], tools[0][2]) and (
        "agent",
        "set_state",
        False,
    ) in tools
    tool_result = provider.calls[1]["messages"][-1]["content"]
    assert tool_result.startswith("Fehler:") and "Bestätigung" in tool_result


def test_every_agent_tool_call_is_audited_even_unknown_ones(tmp_path: Path) -> None:
    client, _ = make(tmp_path, "readonly")
    provider = FakeProvider(
        [ToolCall("c1", "gibts_nicht", {"api_key": "geheim"})],
        [TextDelta("ok")],
    )
    client.app.state.cat.responder = build_responder(client.app.state.cat, provider)  # type: ignore[attr-defined]
    with client, client.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text(json.dumps({"type": "chat.message", "text": "x"}))
        recv_until(ws, "chat.done")
    entry = audit_lines(tmp_path)[-1]
    assert entry["tool"] == "gibts_nicht" and entry["ok"] is False
    assert entry["params"]["api_key"] == "***"
