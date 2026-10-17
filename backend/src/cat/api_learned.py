"""HTTP-Schnittstelle für das Gelernte: ansehen und einzeln vergessen."""

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


@router.get("/api/learned")
async def list_learned(request: Request) -> list[dict[str, Any]]:
    return _state(request).learner.listing()


@router.delete("/api/learned/{shortcut_id}")
async def forget(shortcut_id: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    if not state.learner.forget(shortcut_id):
        raise HTTPException(404, "Das gibt es nicht (mehr).")
    await state.audit.record("learned_forget", {"id": shortcut_id}, "vergessen", source="ui")
    return {"ok": True}


@router.delete("/api/learned")
async def forget_all(request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    state.learner.clear()
    await state.audit.record("learned_forget", {"id": "alle"}, "vergessen", source="ui")
    return {"ok": True}
