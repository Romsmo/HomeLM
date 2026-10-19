"""HTTP-Schnittstelle für die Füllsätze: ansehen und einzeln löschen."""

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


@router.get("/api/fillers")
async def list_fillers(request: Request) -> list[dict[str, Any]]:
    return _state(request).fillers.listing()


@router.delete("/api/fillers")
async def delete_filler(text: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    if not state.fillers.remove(text):
        raise HTTPException(404, "Diesen Füllsatz gibt es nicht (mehr).")
    await state.audit.record("filler_delete", {"text": text}, "gelöscht", source="ui")
    return {"ok": True}
