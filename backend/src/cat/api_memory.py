"""HTTP-Schnittstelle für das Gedächtnis (Second Brain): Notizen ansehen und einzeln löschen."""

import asyncio
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request

from cat.auth import require_auth
from cat.memory.notes import NoteError
from cat.state import AppState

router = APIRouter(dependencies=[Depends(require_auth)])


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.cat
    return state


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Fremder Ursprung")


@router.get("/api/memory")
async def list_notes(request: Request) -> list[dict[str, Any]]:
    notes = await asyncio.to_thread(_state(request).memory.list_notes)
    return [
        {
            "path": n.path,
            "topic": n.topic,
            "title": n.title,
            "date": n.date,
            "tags": n.tags,
            "text": " ".join(n.body.split())[:240],
        }
        for n in notes
    ]


@router.delete("/api/memory")
async def delete_note(path: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    try:
        deleted = await asyncio.to_thread(state.memory.store.delete, path)
    except NoteError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Diese Notiz gibt es nicht (mehr).")
    await asyncio.to_thread(state.memory.index.sync)
    await state.audit.record("memory_delete", {"path": path}, "gelöscht", source="ui")
    return {"ok": True}
