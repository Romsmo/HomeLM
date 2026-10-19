"""HTTP-Schnittstelle für Personen: ansehen, Stimme oder Person vergessen."""

import asyncio
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request

from cat.auth import require_auth
from cat.state import AppState

router = APIRouter(dependencies=[Depends(require_auth)])


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.cat
    return state


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Fremder Ursprung")


@router.get("/api/people")
async def list_people(request: Request) -> dict[str, Any]:
    state = _state(request)
    return {
        "enabled": state.people.enabled,
        "voice_available": state.people.encoder is not None,
        "people": [p.public() for p in state.people.store.all()],
    }


@router.delete("/api/people/{person_id}/voice")
async def forget_voice(person_id: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    if not state.people.store.forget_voice(person_id):
        raise HTTPException(404, "Diese Person gibt es nicht (mehr).")
    await state.audit.record("people_forget_voice", {"id": person_id}, "gelöscht", source="ui")
    return {"ok": True}


@router.delete("/api/people/{person_id}")
async def forget_person(person_id: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    person = state.people.store.get(person_id)
    if person is None:
        raise HTTPException(404, "Diese Person gibt es nicht (mehr).")
    state.people.store.remove(person_id)
    await state._person_forgotten(person)
    await asyncio.to_thread(state.people.drop_channel, "chat")
    await state.audit.record("people_forget", {"id": person_id}, "gelöscht", source="ui")
    return {"ok": True}
