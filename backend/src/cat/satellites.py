"""Satelliten-Register: Anmeldung per Token, fester Raum je Satellit.

`data/config/satellites.yaml` enthält nur Hashes, nie Klartext-Tokens:

    satellites:
      - {id: kueche-pi, room: Küche, token_sha256: <hex>}

Neue Satelliten legt `scripts/satellite_token.py` an und zeigt das Token genau einmal.
"""

import hashlib
import hmac
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from cat.auth import LoginLimiter

log = logging.getLogger("cat.satellites")

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Satellite:
    id: str
    room: str


@dataclass
class SatelliteRegistry:
    satellites: dict[str, tuple[Satellite, str]] = field(default_factory=dict)  # id -> (sat, hash)
    error: str | None = None
    connected: dict[str, float] = field(default_factory=dict)  # id -> verbunden seit
    limiter: LoginLimiter = field(default_factory=lambda: LoginLimiter(10, 60.0))
    path: Path | None = None
    _stamp: tuple[int, int] | None = None  # (Änderungszeit, Größe) beim letzten Einlesen

    @classmethod
    def load(cls, path: Path) -> "SatelliteRegistry":
        registry = cls(path=path)
        registry._read()
        return registry

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat() if self.path else None
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size) if stat else None

    def _refresh(self) -> None:
        """Neue oder geänderte Satelliten gelten sofort, ohne Neustart von Cat."""
        if self._signature() != self._stamp:
            self._read()

    def _read(self) -> None:
        path = self.path
        self.satellites = {}
        self.error = None
        self._stamp = self._signature()
        if path is None or not path.is_file():
            return
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            entries = raw.get("satellites", []) if isinstance(raw, dict) else None
            if not isinstance(entries, list):
                raise ValueError("Erwartet wird eine Liste unter 'satellites:'")
            for entry in entries:
                sid, room = str(entry["id"]), str(entry["room"]).strip()
                digest = str(entry["token_sha256"]).lower()
                if not _ID.match(sid) or not room or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError(f"Ungültiger Eintrag für '{sid}'")
                if sid in self.satellites:
                    raise ValueError(f"Doppelte id '{sid}'")
                self.satellites[sid] = (Satellite(sid, room), digest)
        except (yaml.YAMLError, ValueError, KeyError, TypeError) as exc:
            # Fail closed: eine kaputte Datei lässt keinen Satelliten herein.
            self.satellites.clear()
            self.error = f"satellites.yaml: {exc}"
            log.warning("%s", self.error)

    def authenticate(self, token: str, source: str = "?") -> Satellite | None:
        """Gibt den Satelliten zu einem gültigen Token zurück. Nach vielen Fehlversuchen von
        derselben Quelle wird kurz gesperrt."""
        if self.limiter.retry_after(source) > 0:
            return None
        self._refresh()
        candidate = hash_token(token)
        match: Satellite | None = None
        for satellite, digest in self.satellites.values():  # immer alle prüfen: gleiche Laufzeit
            if hmac.compare_digest(candidate, digest):
                match = satellite
        if match is None:
            self.limiter.record_failure(source)
            return None
        self.limiter.reset(source)
        return match

    def mark_connected(self, satellite: Satellite, clock: Callable[[], float] = time.time) -> None:
        self.connected[satellite.id] = clock()

    def mark_disconnected(self, satellite: Satellite) -> None:
        self.connected.pop(satellite.id, None)

    def listing(self) -> list[dict[str, object]]:
        self._refresh()
        return [
            {
                "id": sat.id,
                "room": sat.room,
                "connected": sat.id in self.connected,
                "since": self.connected.get(sat.id),
            }
            for sat, _ in self.satellites.values()
        ]
