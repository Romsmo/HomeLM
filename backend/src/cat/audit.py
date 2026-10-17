"""Audit-Log: eine JSON-Zeile je Tool-Aufruf (Zeit, Werkzeug, Parameter, Ergebnis)."""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("cat.audit")

_SENSITIVE = ("token", "password", "passwort", "secret", "key", "authorization")
MAX_TEXT = 300
MAX_DEPTH = 4


def redact(value: Any, depth: int = 0) -> Any:
    """Kürzt lange Texte und maskiert Felder, die wie Geheimnisse heißen."""
    if depth > MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        return {
            str(k): "***" if any(s in str(k).lower() for s in _SENSITIVE) else redact(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, depth + 1) for v in value[:20]]
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else f"{value[:MAX_TEXT]}… ({len(value)} Zeichen)"
    return value


class AuditLog:
    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _write(self, line: str) -> None:
        assert self._path is not None
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    async def record(
        self,
        tool: str,
        params: dict[str, Any] | None,
        result: str,
        ok: bool = True,
        source: str = "agent",
    ) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": source,
            "tool": tool,
            "params": redact(params or {}),
            "ok": ok,
            "result": redact(result),
        }
        log.info("audit %s %s ok=%s", source, tool, ok)
        if self._path is None:
            return
        try:
            await asyncio.to_thread(self._write, json.dumps(entry, ensure_ascii=False))
        except OSError:
            # Das Log darf den Betrieb nicht stoppen, der Fehler steht aber im Server-Log.
            log.exception("Audit-Log nicht schreibbar: %s", self._path)
