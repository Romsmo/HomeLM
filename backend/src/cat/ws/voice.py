"""Audio-WebSocket /ws/voice für Browser und Satelliten (Protokoll: docs/voice-protocol.md)."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect

from cat.auth import require_auth
from cat.dialog import handle_user_text
from cat.satellites import Satellite
from cat.state import AppState
from cat.voice.pipeline import Reply, VoiceSession
from cat.voice.wake import WakeDetector
from cat.ws.endpoint import _origin_ok
from cat.ws.protocol import VoiceState

log = logging.getLogger("cat.voice")
router = APIRouter()

MAX_FRAME = 64 * 1024  # größere Audio-Frames sind ein Fehler (Schutz vor Speicherfluten)


@dataclass(frozen=True)
class Principal:
    """Wer verbindet: der Browser (Cookie) oder ein registrierter Satellit (Token)."""

    kind: str
    satellite: Satellite | None = None


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
        "wake": wake_info(request.app.state.cat.settings),
    }


@router.get("/api/satellites", dependencies=[Depends(require_auth)])
async def satellite_list(request: Request) -> dict[str, Any]:
    registry = request.app.state.cat.satellites
    return {"satellites": registry.listing(), "error": registry.error}


def wake_phrases(settings: Any) -> list[str]:
    return [p.strip() for p in str(settings.wake_phrases).split(",") if p.strip()]


def wake_info(settings: Any) -> dict[str, Any]:
    return {
        "required": bool(settings.wake_required),
        "phrases": wake_phrases(settings),
        "followup_s": settings.wake_followup_s,
    }


def _state(ws: WebSocket) -> AppState:
    state: AppState = ws.app.state.cat
    return state


def _authenticate(ws: WebSocket, state: AppState) -> Principal | None:
    """Browser: Sitzungs-Cookie plus passender Origin. Satellit: `Authorization: Bearer <Token>`
    (Browser können diesen Header bei WebSockets nicht setzen, fremde Webseiten also nicht)."""
    header = ws.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        source = ws.client.host if ws.client else "?"
        satellite = state.satellites.authenticate(header[7:].strip(), source)
        return Principal("satellite", satellite) if satellite else None
    if state.auth.is_authenticated(ws.cookies) and _origin_ok(ws):
        return Principal("browser")
    return None


@router.websocket("/ws/voice")
async def voice_endpoint(ws: WebSocket) -> None:
    state = _state(ws)
    principal = _authenticate(ws, state)
    if principal is None:
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
            state,
            text,
            room,
            spoken=True,
            on_delta=on_delta,
            on_filler=lambda text: session.say_filler(text),
            manage_voice_state=False,
            wait=True,  # mehrere Satelliten: nacheinander statt "bitte warten"
        )

    async def on_state(name: str) -> None:
        if name in ("idle", "listening", "thinking", "speaking"):
            await state.emit(VoiceState(state=name))  # type: ignore[arg-type]

    satellite = principal.satellite
    session = VoiceSession(
        engine,
        handle_text,
        send_json,
        send_audio,
        # Der Raum eines Satelliten steht in der Registrierung, der Client kann ihn nicht ändern.
        room=satellite.room if satellite else None,
        on_state=on_state,
        # Der Browser hört immer zu und braucht die Phrase; Satelliten wecken per Wake-Word.
        wake=(
            WakeDetector(wake_phrases(state.settings), state.settings.wake_followup_s)
            if satellite is None and state.settings.wake_required
            else None
        ),
    )
    if satellite:
        state.satellites.mark_connected(satellite)
        log.info("Satellit %s (Raum %s) verbunden", satellite.id, satellite.room)
    await send_json({"type": "voice.ready", "stt": state.settings.stt_model})
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                log.info("Sprach-WebSocket geschlossen (Code %s)", message.get("code"))
                break
            if (data := message.get("bytes")) is not None:
                if len(data) > MAX_FRAME:
                    await send_json({"type": "error", "message": "Audio-Frame zu groß"})
                    continue
                await session.feed(data)
            elif (text := message.get("text")) is not None:
                _control(session, text, fixed_room=satellite is not None)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()
        if satellite:
            state.satellites.mark_disconnected(satellite)
            log.info("Satellit %s getrennt", satellite.id)
        await state.emit(VoiceState(state="idle"))


def _control(session: VoiceSession, text: str, fixed_room: bool) -> None:
    """Steuernachrichten (JSON): {"type": "hello", "room": "Küche"} (nur für den Browser)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    if isinstance(data, dict) and data.get("type") == "hello" and not fixed_room:
        room = data.get("room")
        session.room = room.strip()[:60] if isinstance(room, str) and room.strip() else None
