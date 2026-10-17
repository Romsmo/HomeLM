import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cat.ws.protocol import CLIENT_EVENT_TYPES, SERVER_EVENT_TYPES
from tests.helpers import drain_replay


def _recv_until(ws: Any, type_: str, limit: int = 50) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if event["type"] == type_:
            return seen
    raise AssertionError(f"{type_} nicht empfangen: {seen}")


def test_ws_rejects_unauthenticated(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
        pass


def test_ws_rejects_foreign_origin(authed: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        authed.websocket_connect("/ws", headers={"origin": "http://evil.example"}),
    ):
        pass


def test_echo_streams_live(authed: TestClient) -> None:
    with authed.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text(json.dumps({"type": "chat.message", "text": "Hallo Cat"}))
        first = json.loads(ws.receive_text())
        assert first["type"] == "chat.message" and first["role"] == "user"
        events = _recv_until(ws, "chat.done")
        deltas = "".join(e["delta"] for e in events if e["type"] == "chat.delta")
        assert deltas == "Echo: Hallo Cat"
        assert _recv_until(ws, "voice.state")[-1]["state"] == "idle"


def test_history_replayed_and_clear(authed: TestClient) -> None:
    with authed.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text(json.dumps({"type": "chat.message", "text": "eins"}))
        _recv_until(ws, "chat.done")
        _recv_until(ws, "voice.state")
    with authed.websocket_connect("/ws") as ws:
        replay = drain_replay(ws)
        first, second = replay[0], replay[1]
        assert (first["role"], first["text"]) == ("user", "eins")
        assert (second["role"], second["text"]) == ("assistant", "Echo: eins")
        assert [e["type"] for e in replay[-2:]] == ["device.list", "provider.state"]
        ws.send_text(json.dumps({"type": "chat.clear"}))
        assert json.loads(ws.receive_text())["type"] == "chat.clear"
    with authed.websocket_connect("/ws") as ws:
        replay = drain_replay(ws)
        assert [e["type"] for e in replay] == ["device.list", "provider.state"]


def test_invalid_message_gives_error(authed: TestClient) -> None:
    with authed.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text("kein json")
        assert json.loads(ws.receive_text())["type"] == "error"
        ws.send_text(json.dumps({"type": "chat.message", "text": ""}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_unknown_widget_refresh_gives_error(authed: TestClient) -> None:
    with authed.websocket_connect("/ws") as ws:
        drain_replay(ws)
        ws.send_text(json.dumps({"type": "widget.refresh", "id": "nope"}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_protocol_doc_and_frontend_types_list_all_events() -> None:
    root = Path(__file__).resolve().parents[2]
    doc = (root / "docs" / "protocol.md").read_text(encoding="utf-8")
    ts = (root / "frontend" / "src" / "protocol.ts").read_text(encoding="utf-8")
    for name in {*SERVER_EVENT_TYPES, *CLIENT_EVENT_TYPES}:
        assert f"`{name}`" in doc, f"{name} fehlt in docs/protocol.md"
        assert f'"{name}"' in ts, f"{name} fehlt in frontend/src/protocol.ts"
