"""Automatische Erkennung aller openHAB-Items (statt einer von Hand gepflegten Allowlist).

Aus der Item-Liste von openHAB (Typ, Etikett, Tags, Gruppen) werden Geräte im Cat-Format. Den
Raum liefert das semantische Modell von openHAB: Das nächste Gruppen-Item mit dem Tag `Location`
über dem Item ist sein Raum. Es wird NICHTS in openHAB verändert: gelesen wird per GET, gesteuert
nur mit Befehlen an Items (siehe plugins/openhab).

Vorsicht ist eingebaut:
- Schlösser, Türen, Garagen, Alarm: nur lesbar (kein automatisches Steuern; wer das will, trägt
  das Gerät mit `command_map` selbst in devices.yaml ein, dann gilt auch die Bestätigungspflicht).
- Technik wie Statusanzeigen der Automatisierung, Wärmepumpe, Lüftungsanlage, Trigger, Tests:
  nur lesbar, damit Cat keine Regeln oder Anlagen verstellt.
- Bei Bedarf `readonly_patterns`, `unlisted_patterns` und `exclude_patterns` in devices.yaml.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cat.devices.models import DeviceSpec, DeviceType

# Vorgaben (Regex ohne Groß-/Kleinschreibung auf Name, Etikett und die Namen übergeordneter
# Gruppen). Eigene Einträge in devices.yaml kommen dazu, sie ersetzen die Vorgaben nicht.
DEFAULT_READONLY = [
    r"^stat[A-Z_]|status|maintenance|shcc|script|automation",
    r"warmepumpe|luxtronik|comfoair|heizung|lüftung|lueftung",
    r"trig|reboot|test",
    r"schloss|\block|garagentor|toröffner|toroeffner|türöffner|tueroeffner|alarm|sirene",
]
DEFAULT_UNLISTED = [
    r"scenario|_sc\d|szenario",
    r"rssi|moving|battery|batterie|firmware|colortemperature|farbtemperatur",
    r"^trig|^tri_|reboot|test",
]
# Messwerte, die in Listen und im Dashboard erscheinen (Rest ist nur auf Nachfrage da).
LISTED_PROPERTIES = {"Temperature", "Humidity", "Pressure", "Power", "Energy", "Co2", "Rain"}
SKIPPED_TYPES = {"Group", "Image", "Player", "Location"}
_ROOM_FALLBACK = "Haus"


class DiscoverConfig(BaseModel):
    """Abschnitt `discover.openhab` in devices.yaml."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    readonly_patterns: list[str] = Field(default_factory=list, max_length=50)
    unlisted_patterns: list[str] = Field(default_factory=list, max_length=50)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=50)
    refresh_s: int = Field(default=600, ge=30)


@dataclass(frozen=True)
class Discovered:
    spec: DeviceSpec
    state: (
        str | None
    )  # Zustand aus der Item-Liste (Rohtext), damit nicht 500 Einzelabfragen nötig sind


@dataclass
class _Patterns:
    readonly: list[re.Pattern[str]] = field(default_factory=list)
    unlisted: list[re.Pattern[str]] = field(default_factory=list)
    exclude: list[re.Pattern[str]] = field(default_factory=list)


def _compile(defaults: Iterable[str], extra: Iterable[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for text in (*defaults, *extra):
        try:
            out.append(re.compile(text, re.IGNORECASE))
        except re.error:
            continue  # kaputter Ausdruck des Nutzers: ignorieren, nicht abstürzen
    return out


def _slug(text: str) -> str:
    folded = (
        text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "item"


def pretty(item_name: str) -> str:
    """Item-Name lesbar: "Hue_Lampe_TerrasseWest_Farbe" -> "Hue Lampe TerrasseWest Farbe"."""
    return re.sub(r"_+", " ", item_name).strip()


def _ancestors(item: dict[str, Any], by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Alle übergeordneten Gruppen, nächste zuerst (Breitensuche, ohne Endlosschleife)."""
    seen: set[str] = {item["name"]}
    order: list[dict[str, Any]] = []
    queue = list(item.get("groupNames") or [])
    while queue:
        name = queue.pop(0)
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        group = by_name[name]
        order.append(group)
        queue.extend(group.get("groupNames") or [])
    return order


def _room(ancestors: list[dict[str, Any]]) -> str:
    for group in ancestors:
        if "Location" in (group.get("tags") or []):
            return str(group.get("label") or group["name"]).strip()[:60] or _ROOM_FALLBACK
    return _ROOM_FALLBACK


def _matches(patterns: list[re.Pattern[str]], texts: Iterable[str]) -> bool:
    return any(p.search(t) for p in patterns for t in texts if t)


def _device_type(item: dict[str, Any], readonly: bool) -> DeviceType | None:
    kind = str(item.get("type", "")).split(":")[0]
    tags = set(item.get("tags") or [])
    if kind in SKIPPED_TYPES:
        return None
    if readonly or kind in {"Number", "String", "DateTime", "Contact"}:
        return "sensor"
    if kind == "Switch":
        return "light" if "Light" in tags else "switch"
    if kind in {"Dimmer", "Color"}:
        return "dimmer"
    if kind == "Rollershutter":
        return "shutter"
    return "sensor"


def discover_openhab(
    items: list[dict[str, Any]], config: DiscoverConfig, taken_items: set[str] | None = None
) -> list[Discovered]:
    """Macht aus der openHAB-Item-Liste Geräte. `taken_items`: schon von Hand eingetragene Items."""
    taken = taken_items or set()
    patterns = _Patterns(
        readonly=_compile(DEFAULT_READONLY, config.readonly_patterns),
        unlisted=_compile(DEFAULT_UNLISTED, config.unlisted_patterns),
        exclude=_compile([], config.exclude_patterns),
    )
    by_name = {str(i["name"]): i for i in items if "name" in i}
    drafts: list[tuple[dict[str, Any], DeviceType, str, bool]] = []
    for item in by_name.values():
        if item["name"] in taken:
            continue
        ancestors = _ancestors(item, by_name)
        label = str(item.get("label") or "")
        texts = [item["name"], label, *(g["name"] for g in ancestors)]
        group_labels = [str(g.get("label") or "") for g in ancestors]
        if _matches(patterns.exclude, texts):
            continue
        readonly = _matches(patterns.readonly, [*texts, *group_labels])
        dtype = _device_type(item, readonly)
        if dtype is None:
            continue
        kind = str(item.get("type", "")).split(":")[0]
        tags = set(item.get("tags") or [])
        unlisted = _matches(patterns.unlisted, [item["name"], label])
        if dtype == "sensor":
            # Nur echte Messwerte erscheinen in Listen, Technik (Texte, Zeiten, Status) nicht.
            measured = kind == "Number" and "Measurement" in tags and bool(tags & LISTED_PROPERTIES)
            unlisted = unlisted or not measured
        drafts.append((item, dtype, _room(ancestors), not unlisted))

    # Namen: Etikett, bei Doppelungen im selben Raum der lesbare Item-Name.
    def base_name(item: dict[str, Any]) -> str:
        label = str(item.get("label") or "").strip()
        return label if label and label != item["name"] else pretty(item["name"])

    counts: dict[tuple[str, str], int] = {}
    for item, _, room, _ in drafts:
        key = (room.lower(), base_name(item).lower())
        counts[key] = counts.get(key, 0) + 1

    used_ids: set[str] = set()
    used_names: set[tuple[str, str]] = set()
    out: list[Discovered] = []
    for item, dtype, room, listed in sorted(drafts, key=lambda d: d[0]["name"]):
        name = base_name(item)
        if counts[(room.lower(), name.lower())] > 1:
            name = pretty(item["name"])
        name = name[:100]
        base = name
        n = 2
        while (room.lower(), name.lower()) in used_names:
            name = f"{base} ({n})"[:100]
            n += 1
        used_names.add((room.lower(), name.lower()))
        slug = _slug(item["name"])[:60]
        device_id, k = slug, 2
        while device_id in used_ids:
            device_id = f"{slug}_{k}"[:64]
            k += 1
        used_ids.add(device_id)
        synonyms = [
            s for s in {pretty(item["name"]), str(item.get("label") or "")} if s and s != name
        ]
        out.append(
            Discovered(
                spec=DeviceSpec(
                    id=device_id,
                    backend="openhab",
                    item=item["name"],
                    name=name,
                    room=room,
                    type=dtype,
                    synonyms=synonyms[:20],
                    listed=listed,
                ),
                state=None if item.get("state") is None else str(item["state"]),
            )
        )
    return out
