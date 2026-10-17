"""Audio-WebSocket /ws/voice für Browser und Satelliten (Protokoll: docs/voice-protocol.md)."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect

from cat.auth import require_auth
from cat.dialog import handle_user_text
from cat.state import AppState
from cat.voice.pipeline import Reply, VoiceSession
from cat.ws.endpoint import _origin_ok
from cat.ws.protocol import VoiceState

log = logging.getLogger("cat.voice")
router = APIRouter()

MAX_FRAME = 64 * 1024  # größere Audio-Frames sind ein Fehler (Schutz vor Speicherfluten)


@router.get("/api/voice", dependencies=[Depends(require_auth)])
async def voice_info(request: Request) -> dict[str, Any]:
    """Für das Frontend: Ist Sprache an und bereit, und ist das Mikrofon hier nutzbar?"""
    engine = request.app.state.cat.voice
    return {
        "enabled": engine is not None,
        "ready": bool(engine and engine.ready),
        "error": engine.error if engine else None,
        "stt": getattr(engine.stt, "model_name", "") if engine else None,
        "voice": getattr(engine.tts, "voice_name", "") if engine else None,
    }


def _state(ws: WebSocket) -> AppState:
    state: AppState = ws.app.state.cat
    return state


@router.websocket("/ws/voice")
async def voice_endpoint(ws: WebSocket) -> None:
    state = _state(ws)
    if not state.auth.is_authenticated(ws.cookies) or not _origin_ok(ws):
        await ws.close(code=1008)
        return
    engine = state.voice
    if engine is None:
        await ws.close(code=1008, reason="Sprachfunktion ist ausgeschaltet")
        return
    await ws.accept()
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, Any]) -> None:
        async with send_lock:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def send_audio(chunk: bytes) -> None:
        async with send_lock:
            await ws.send_bytes(chunk)

    if not engine.ready:
        message = engine.error or "Die Sprachmodelle laden noch, bitte kurz warten."
        await send_json({"type": "error", "message": message})
        await ws.close(code=1013)
        return

    async def handle_text(text: str, room: str | None, on_delta: Any) -> Reply:
        return await handle_user_text(
            state, text, room, spoken=True, on_delta=on_delta, manage_voice_state=False
        )

    async def on_state(name: str) -> None:
        if name in ("idle", "listening", "thinking", "speaking"):
            await state.emit(VoiceState(state=name))  # type: ignore[arg-type]

    session = VoiceSession(engine, handle_text, send_json, send_audio, on_state=on_state)
    await send_json({"type": "voice.ready", "stt": state.settings.stt_model})
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if (data := message.get("bytes")) is not None:
                if len(data) > MAX_FRAME:
                    await send_json({"type": "error", "message": "Audio-Frame zu groß"})
                    continue
                await session.feed(data)
            elif (text := message.get("text")) is not None:
                _control(session, text)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        await state.emit(VoiceState(state="idle"))


def _control(session: VoiceSession, text: str) -> None:
    """Steuernachrichten (JSON): {"type": "hello", "room": "Küche"}."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    if isinstance(data, dict) and data.get("type") == "hello":
        room = data.get("room")
        session.room = room.strip()[:60] if isinstance(room, str) and room.strip() else None
