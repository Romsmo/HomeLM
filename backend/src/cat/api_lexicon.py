"""HTTP-Schnittstelle für den Wortschatz: vom Nutzer erklärte Begriffe ansehen und löschen."""

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


@router.get("/api/lexicon")
async def list_terms(request: Request) -> list[dict[str, Any]]:
    state = _state(request)
    names = {s.id: s.name for s in state.devices.specs}
    return [
        {
            "term": r["term"],
            "devices": [names[i] for i in r["ids"] if i in names],
            "uses": r["uses"],
        }
        for r in state.lexicon.listing()
    ]


@router.delete("/api/lexicon")
async def delete_term(term: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    if not state.lexicon.remove(term):
        raise HTTPException(404, "Diesen Begriff gibt es nicht (mehr).")
    await state.audit.record("lexicon_delete", {"term": term}, "gelöscht", source="ui")
    return {"ok": True}
