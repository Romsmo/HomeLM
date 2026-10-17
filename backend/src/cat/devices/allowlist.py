"""Allowlist: nur dort aufgeführte Geräte sind für Cat sichtbar und steuerbar."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from cat.devices.discovery import DiscoverConfig
from cat.devices.models import DeviceSpec

log = logging.getLogger("cat.devices")

EXAMPLE = """\
# Allowlist: nur diese Geräte sind für Cat sichtbar und steuerbar.
# Typen: light, switch, dimmer, shutter, thermostat, sensor, lock, door, garage
# Risiko: low, medium, high. Türen, Schlösser und Garagen sind immer high (Bestätigung Pflicht).
#
# Statt jedes Gerät von Hand einzutragen, kann Cat alle openHAB-Items selbst erkennen (Raum aus dem
# semantischen Modell, Technik und Schlösser nur lesbar). Von Hand eingetragene Geräte gelten vor
# den erkannten. Siehe docs/devices.md.
# discover:
#   openhab:
#     enabled: true
#     readonly_patterns: []    # zusätzliche Regex: Geräte, die Cat nur lesen darf
#     unlisted_patterns: []    # zusätzliche Regex: nur auf Nachfrage, nicht in Listen
#     exclude_patterns: []     # zusätzliche Regex: ganz ausblenden
devices:
  - id: wohnzimmer_licht
    backend: openhab
    item: Wohnzimmer_Licht       # Name des Items in openHAB
    name: Wohnzimmer Licht
    room: Wohnzimmer
    type: light
    synonyms: [Stehlampe]
    test: true                   # Testgerät: steuerbar im Modus "test"
"""


@dataclass
class Allowlist:
    specs: list[DeviceSpec] = field(default_factory=list)
    error: str | None = None
    # Automatische Erkennung je Backend (nur openhab), siehe devices/discovery.py
    discover: dict[str, DiscoverConfig] = field(default_factory=dict)

    def by_id(self, device_id: str) -> DeviceSpec | None:
        return next((s for s in self.specs if s.id == device_id), None)


def parse_allowlist(text: str) -> Allowlist:
    """Liest den YAML-Text. Fehler führen zu einer leeren Liste und einer Meldung (fail closed)."""
    try:
        raw = yaml.safe_load(text) or {}
        entries = raw.get("devices", []) if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return Allowlist(error="devices.yaml: Erwartet wird eine Liste unter 'devices:'.")
        specs = [DeviceSpec.model_validate(e) for e in entries]
        discover = {
            str(name): DiscoverConfig.model_validate(cfg or {})
            for name, cfg in (raw.get("discover") or {}).items()
        }
        if set(discover) - {"openhab"}:
            return Allowlist(error="devices.yaml: discover kennt nur 'openhab'.")
    except yaml.YAMLError:
        return Allowlist(error="devices.yaml ist kein gültiges YAML.")
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return Allowlist(error=f"devices.yaml: {where}: {first['msg']}")

    seen: set[str] = set()
    for spec in specs:
        if spec.id in seen:
            return Allowlist(error=f"devices.yaml: doppelte id '{spec.id}'.")
        seen.add(spec.id)
    return Allowlist(specs=specs, discover=discover)


def load_allowlist(path: Path) -> Allowlist:
    if not path.is_file():
        log.info("Keine Allowlist unter %s: keine Geräte sichtbar", path)
        return Allowlist()
    result = parse_allowlist(path.read_text(encoding="utf-8"))
    if result.error:
        log.warning("%s", result.error)
    return result
