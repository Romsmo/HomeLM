"""HTTP-Schnittstelle für abgelegte Dateien: hochladen, auflisten, ansehen, löschen, zeigen."""

import asyncio
import logging
import mimetypes
import os
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from cat.auth import require_auth
from cat.files import (
    MARKDOWN_EXT,
    MAX_FILE_BYTES,
    MAX_INBOX_BYTES,
    FileError,
    Inbox,
    StoredFile,
    clean_name,
)
from cat.stage.sanitize import MAX_MARKDOWN_CHARS
from cat.state import AppState
from cat.ws.protocol import ChatMessage, StageShow

log = logging.getLogger("cat.files")
router = APIRouter(dependencies=[Depends(require_auth)])

FILE_CSP = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"

# Darstellung auf der Stage: Text bis zu dieser Länge (Rest wird abgeschnitten).
STAGE_TEXT_CHARS = min(MAX_MARKDOWN_CHARS, 60_000)


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.cat
    return state


def _same_origin(request: Request) -> None:
    """Schutz vor fremden Webseiten: Der Origin (falls gesendet) muss zum Host passen."""
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Fremder Ursprung")


def _human(size: int) -> str:
    if size >= 1024**2:
        return f"{size / 1024**2:.1f} MB".replace(".", ",")
    return f"{max(1, round(size / 1024))} KB"


def _json(file: StoredFile) -> dict[str, Any]:
    return {"name": file.name, "size": file.size, "kind": file.kind, "modified": file.modified}


async def show_on_stage(state: AppState, inbox: Inbox, name: str) -> bool:
    """Zeigt eine Datei auf der Stage (Bild oder Text). False, wenn die Art das nicht zulässt."""
    path = inbox.path_of(name)
    kind = inbox.describe(path).kind
    if kind == "image":
        item = state.stage.add("image", name, content=name)
    elif kind == "text":
        text, cut = await asyncio.to_thread(inbox.read_text, name, STAGE_TEXT_CHARS)
        if not text.strip():
            return False
        body = text if path.suffix.lower() in MARKDOWN_EXT else f"```\n{text}\n```"
        if cut:
            body += "\n\n*(gekürzt)*"
        item = state.stage.add("markdown", name, content=body)
    else:
        return False
    await state.emit(StageShow(item=item))
    return True


@router.get("/api/files")
async def list_files(request: Request) -> list[dict[str, Any]]:
    return [_json(f) for f in _state(request).inbox.list()]


@router.put("/api/files/{name}")
async def upload(name: str, request: Request) -> dict[str, Any]:
    _same_origin(request)
    state, inbox = _state(request), _state(request).inbox
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise HTTPException(413, f"Datei zu groß (höchstens {_human(MAX_FILE_BYTES)}).")
    if await asyncio.to_thread(inbox.used_bytes) >= MAX_INBOX_BYTES:
        raise HTTPException(413, "Der Dateieingang ist voll. Bitte erst Dateien löschen.")
    target = inbox.new_path(name)
    partial = target.with_name(f".upload-{uuid.uuid4().hex}")
    size = 0
    try:
        with partial.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, f"Datei zu groß (höchstens {_human(MAX_FILE_BYTES)}).")
                await asyncio.to_thread(fh.write, chunk)
        if size == 0:
            raise HTTPException(400, "Die Datei ist leer.")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    stored = inbox.describe(target)
    note = ChatMessage(
        id=uuid.uuid4().hex,
        role="system",
        text=f"Datei erhalten: {stored.name} ({_human(stored.size)})",
        ts=time.time(),
    )
    state.chat.append(note)
    await state.emit(note)
    await state.audit.record(
        "file_upload", {"name": stored.name, "size": stored.size}, "ok", source="ui"
    )
    try:
        await show_on_stage(state, inbox, stored.name)
    except (FileError, OSError):
        log.exception("Datei konnte nicht auf der Stage gezeigt werden")
    return _json(stored)


@router.get("/api/files/{name}")
async def download(name: str, request: Request) -> FileResponse:
    try:
        path = _state(request).inbox.path_of(name)
    except FileError as exc:
        raise HTTPException(404, str(exc)) from exc
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    inline = media.startswith("image/")
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            # Auch ein direkt geöffnetes SVG oder HTML darf nichts ausführen.
            "Content-Security-Policy": FILE_CSP,
            "Cache-Control": "private, max-age=300",
        },
    )


@router.delete("/api/files/{name}")
async def delete(name: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    try:
        state.inbox.delete(name)
    except FileError as exc:
        raise HTTPException(404, str(exc)) from exc
    await state.audit.record("file_delete", {"name": clean_name(name)}, "ok", source="ui")
    return {"ok": True}


@router.post("/api/files/{name}/show")
async def show(name: str, request: Request) -> dict[str, bool]:
    _same_origin(request)
    state = _state(request)
    try:
        shown = await show_on_stage(state, state.inbox, name)
    except FileError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not shown:
        raise HTTPException(415, "Diese Dateiart kann Cat nicht anzeigen (nur Bilder und Text).")
    return {"ok": True}
