"""Tageslimit und Sperre für Fragen an Claude.

Schützt das Abo-Limit des Nutzers und die Privatsphäre: Es gehen nie mehr als `daily_limit`
Fragen pro Tag an Claude. Nach einem Limit- oder Anmeldefehler ruht Claude eine Weile, damit
nicht jede Nachricht erst wieder scheitert.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cat.claude")


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


class ClaudeBudget:
    def __init__(
        self,
        path: Path,
        daily_limit: int,
        today: Callable[[], str] = _today,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = path
        self._limit = daily_limit
        self._today = today
        self._clock = clock
        self._blocked_until = 0.0
        self._blocked_reason = ""

    def _count(self) -> int:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return int(data["count"]) if data.get("date") == self._today() else 0
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    @property
    def used_today(self) -> int:
        return self._count()

    def blocked(self) -> str | None:
        """Grund, warum jetzt nicht an Claude gefragt werden darf, sonst None."""
        if self._clock() < self._blocked_until:
            return self._blocked_reason
        if self._limit <= 0:
            return "Claude ist abgeschaltet (Tageslimit 0)."
        if self._count() >= self._limit:
            return f"Das Tageslimit für Claude ist erreicht ({self._limit} Fragen)."
        return None

    def record(self) -> None:
        """Zählt eine Frage (vor dem Aufruf, damit auch abgebrochene Aufrufe zählen)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"date": self._today(), "count": self._count() + 1}), encoding="utf-8"
            )
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Claude-Zähler konnte nicht gespeichert werden")

    def block(self, seconds: float, reason: str) -> None:
        self._blocked_until = self._clock() + seconds
        self._blocked_reason = reason
