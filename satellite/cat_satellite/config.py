"""Konfiguration des Satelliten (config.yaml, Token auch über CAT_SATELLITE_TOKEN)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Ungültige Konfiguration; die Meldung nennt das Problem."""


_DEVICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclass(frozen=True)
class Config:
    server_url: str  # ws://192.168.0.10:8090/ws/voice
    token: str
    device_id: str
    room: str  # nur für Logs; maßgeblich ist der Raum, den der Server für das Token kennt
    wakeword_model: str = "hey_jarvis"  # eingebautes Modell oder Pfad zu .onnx/.tflite
    wakeword_threshold: float = 0.5
    input_device: str | int | None = None
    output_device: str | int | None = None
    beep: bool = True
    cooldown_s: float = 1.5  # nach einer Antwort so lange keine neue Auslösung
    server_timeout_s: float = 20.0  # so lange auf eine Antwort des Servers warten

    @property
    def safe_url(self) -> str:
        """URL für Logs (ohne mögliche Zugangsdaten in der URL)."""
        return re.sub(r"//[^/@]*@", "//", self.server_url)


def _device(value: Any, name: str) -> str | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ConfigError(f"{name} muss ein Gerätename oder eine Nummer sein")
    return value


def parse_config(raw: dict[str, Any], env: dict[str, str] | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    url = str(raw.get("server_url", "")).strip()
    if not re.match(r"^wss?://[^\s]+$", url):
        raise ConfigError(
            "server_url muss mit ws:// oder wss:// beginnen (z. B. ws://192.168.0.10:8090/ws/voice)"
        )
    if url.startswith("ws://") and not re.match(
        r"^ws://(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", url
    ):
        raise ConfigError(
            "Unverschlüsseltes ws:// nur im lokalen Netz erlaubt, sonst wss:// verwenden"
        )
    token = (env.get("CAT_SATELLITE_TOKEN") or str(raw.get("token", ""))).strip()
    if len(token) < 20:
        raise ConfigError(
            "token fehlt oder ist zu kurz (scripts/satellite_token.py auf dem Server erzeugt eins)"
        )
    device_id = str(raw.get("device_id", "")).strip()
    if not _DEVICE_ID.match(device_id):
        raise ConfigError("device_id darf nur a-z, 0-9, - und _ enthalten (max. 40 Zeichen)")
    room = str(raw.get("room", "")).strip()
    if not room:
        raise ConfigError("room fehlt (Raum dieses Satelliten, z. B. Küche)")
    threshold = float(raw.get("wakeword_threshold", 0.5))
    if not 0.05 <= threshold <= 0.99:
        raise ConfigError("wakeword_threshold muss zwischen 0,05 und 0,99 liegen")
    return Config(
        server_url=url,
        token=token,
        device_id=device_id,
        room=room,
        wakeword_model=str(raw.get("wakeword_model", "hey_jarvis")),
        wakeword_threshold=threshold,
        input_device=_device(raw.get("input_device"), "input_device"),
        output_device=_device(raw.get("output_device"), "output_device"),
        beep=bool(raw.get("beep", True)),
        cooldown_s=float(raw.get("cooldown_s", 1.5)),
        server_timeout_s=float(raw.get("server_timeout_s", 20.0)),
    )


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"{path} nicht lesbar: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} ist kein gültiges YAML") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: erwartet wird eine Zuordnung (Schlüssel: Wert)")
    return parse_config(raw)
