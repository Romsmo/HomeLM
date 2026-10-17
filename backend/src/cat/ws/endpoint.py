import logging
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from cat.devices.ui import handle_ui_command
from cat.dialog import handle_user_text
from cat.state import AppState
from cat.ws.hub import Connection
from cat.ws.protocol import (
    ChatClear,
    ClientChatClear,
    ClientChatMessage,
    ClientConfirmResponse,
    ClientDeviceCommand,
    ClientStageClear,
    ClientWidgetRefresh,
    ErrorEvent,
    StageClear,
    StageShow,
    client_event_adapter,
)

log = logging.getLogger("cat.ws")
router = APIRouter()


def _origin_ok(ws: WebSocket) -> bool:
    """Schutz vor fremden Webseiten: Origin muss zum Host passen (falls gesendet)."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    return urlparse(origin).netloc == ws.headers.get("host")


async def _replay(state: AppState, conn: Connection) -> None:
    for message in state.chat:
        await conn.send(message)
    for item in state.stage.items:
        await conn.send(StageShow(item=item))
    for widget in state.widgets.values():
        await conn.send(widget)
    await conn.send(state.devices.list_event())


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    state: AppState = ws.app.state.cat
    if not state.auth.is_authenticated(ws.cookies) or not _origin_ok(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    conn = state.hub.add(ws)
    try:
        await _replay(state, conn)
        while True:
            raw = await ws.receive_text()
            try:
                event = client_event_adapter.validate_json(raw)
            except ValidationError:
                await conn.send(ErrorEvent(message="Ungültige Nachricht"))
                continue
            await _dispatch(state, conn, event)
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.remove(conn)


async def _dispatch(
    state: AppState,
    conn: Connection,
    event: ClientChatMessage
    | ClientChatClear
    | ClientStageClear
    | ClientWidgetRefresh
    | ClientConfirmResponse
    | ClientDeviceCommand,
) -> None:
    match event:
        case ClientChatMessage(text=text):
            # Als Task, damit der Empfangs-Loop (z. B. Clear, Refresh) frei bleibt.
            state.spawn(handle_user_text(state, text))
        case ClientChatClear():
            if state.run_lock.locked():
                await conn.send(ErrorEvent(message="Cat antwortet noch, bitte kurz warten."))
                return
            state.chat.clear()
            state.memory.sessions.new_session()
            await state.emit(ChatClear())
        case ClientStageClear():
            state.stage.clear()
            await state.emit(StageClear())
        case ClientWidgetRefresh(id=widget_id):
            refresh = state.widget_refresher
            if refresh is None or not await refresh(widget_id):
                message = f"Widget '{widget_id}' ist nicht aktualisierbar"
                await conn.send(ErrorEvent(message=message))
        case ClientConfirmResponse(id=confirm_id, approved=approved):
            # Unbekannte oder schon beantwortete IDs werden stillschweigend ignoriert.
            state.confirm.resolve(confirm_id, approved)
        case ClientDeviceCommand(id=device_id, command=command):
            # Als Task: bei "high" wartet der Befehl auf Bestätigung, der Loop muss frei bleiben.
            state.spawn(handle_ui_command(state, device_id, command))
