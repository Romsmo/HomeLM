import json
from typing import Any

from fastapi.testclient import TestClient

from cat.agent.responder import build_responder
from cat.config import Settings
from cat.llm.base import LLMError, TextDelta, ToolCall
from cat.main import create_app
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider


def client_with(provider: FakeProvider, settings: Settings) -> TestClient:
    app = create_app(settings)
    state = app.state.cat
    state.responder = build_responder(state, provider)
    c = TestClient(app)
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


def recv_until(ws: Any, type_: str) -> list[dict[str, Any]]:
    seen = []
    for _ in range(60):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if event["type"] == type_:
            return seen
    raise AssertionError(f"{type_} nicht empfangen")


def send(ws: Any, text: str) -> None:
    ws.send_text(json.dumps({"type": "chat.message", "text": text}))


def test_clock_request_renders_on_stage_and_answers(settings: Settings) -> None:
    html = "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='40'/></svg>"
    provider = FakeProvider(
        [ToolCall("c1", "show_html", {"title": "Analoguhr", "html": html})],
        [TextDelta("Hier ist deine Uhr.")],
    )
    with client_with(provider, settings) as c, c.websocket_connect("/ws") as ws:
        send(ws, "Zeig mir eine analoge Uhr als HTML-Grafik")
        events = recv_until(ws, "chat.done")
        types = [e["type"] for e in events]
        stage = next(e for e in events if e["type"] == "stage.show")
        assert stage["item"]["kind"] == "html" and stage["item"]["title"] == "Analoguhr"
        assert types.index("stage.show") < types.index("chat.delta")
        text = "".join(e["delta"] for e in events if e["type"] == "chat.delta")
        assert text == "Hier ist deine Uhr."
        assert "show_html" in provider.calls[0]["tool_names"]


def test_bar_chart_request_creates_chart(settings: Settings) -> None:
    spec = {
        "type": "bar",
        "labels": ["Jan", "Feb", "Mär"],
        "datasets": [{"label": "Umsatz", "data": [3, 5, 4]}],
    }
    provider = FakeProvider(
        [ToolCall("c1", "show_chart", {"title": "Umsatz", "spec": spec})],
        [TextDelta("Das Diagramm steht.")],
    )
    with client_with(provider, settings) as c, c.websocket_connect("/ws") as ws:
        send(ws, "Zeig mir ein Balkendiagramm: Jan 3, Feb 5, Mär 4")
        events = recv_until(ws, "chat.done")
        stage = next(e for e in events if e["type"] == "stage.show")
        assert stage["item"]["kind"] == "chart"
        assert stage["item"]["chart"]["datasets"][0]["data"] == [3.0, 5.0, 4.0]


def test_stage_history_replayed_on_reconnect_and_clearable(settings: Settings) -> None:
    provider = FakeProvider(
        [ToolCall("c1", "show_markdown", {"title": "Liste", "text": "- a"})],
        [TextDelta("ok")],
    )
    with client_with(provider, settings) as c:
        with c.websocket_connect("/ws") as ws:
            send(ws, "liste")
            recv_until(ws, "chat.done")
        with c.websocket_connect("/ws") as ws:
            replayed = [json.loads(ws.receive_text()) for _ in range(3)]
            assert [e["type"] for e in replayed] == ["chat.message", "chat.message", "stage.show"]
            ws.send_text(json.dumps({"type": "stage.clear"}))
            assert json.loads(ws.receive_text())["type"] == "stage.clear"
        with c.websocket_connect("/ws") as ws:
            types = [json.loads(ws.receive_text())["type"] for _ in range(2)]
            assert "stage.show" not in types


def test_model_error_becomes_chat_answer(settings: Settings) -> None:
    provider = FakeProvider(LLMError("Kein API-Schlüssel gesetzt."))
    with client_with(provider, settings) as c, c.websocket_connect("/ws") as ws:
        send(ws, "hallo")
        events = recv_until(ws, "chat.done")
        text = "".join(e["delta"] for e in events if e["type"] == "chat.delta")
        assert "Kein API-Schlüssel" in text
        assert not any(e["type"] == "error" for e in events)


def test_follow_up_sees_previous_turns(settings: Settings) -> None:
    provider = FakeProvider([TextDelta("Eins.")], [TextDelta("Zwei.")])
    with client_with(provider, settings) as c, c.websocket_connect("/ws") as ws:
        send(ws, "erste")
        recv_until(ws, "chat.done")
        recv_until(ws, "voice.state")
        send(ws, "zweite")
        recv_until(ws, "chat.done")
    second = provider.calls[1]["messages"]
    assert [m["content"] for m in second] == ["erste", "Eins.", "zweite"]
