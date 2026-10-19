"""Automationen = openHAB-Regeln (nur lesen: Name, aktiv oder deaktiviert).

Cat liest `GET /rest/rules?summary=true` und verändert nichts: Regeln werden weder ausgeführt noch
ein- oder ausgeschaltet. Viele Regeln sind Varianten einer Automation ("Treppenhaus Beschattung
Ein Ia", "... Ib", "... II"), die zu einem Eintrag mit Anzahl zusammengefasst werden.
"""

import re
from dataclasses import dataclass
from typing import Any

from cat.intents.text import tokenize

LIST_LIMIT = 12
_VARIANT = re.compile(r"(?:\s+(?:part\s?\d+|[ivx]+[a-c]?|\d+))+\s*$", re.IGNORECASE)
# Wörter, die nur "Automation" meinen und nichts eingrenzen.
_GENERIC = frozenset(
    "automation automationen regel regeln automatisierung automatisierungen aktiv aktive aktiven "
    "an ein aus alle alles gerade jetzt".split()
)
_ACTIVE_WORDS = frozenset("aktiv aktiviert an ein eingeschaltet laufen laeuft".split())
_OFF_WORDS = frozenset("aus deaktiviert inaktiv ausgeschaltet abgeschaltet".split())


@dataclass(frozen=True)
class Automation:
    name: str  # Grundname ohne Variantenzusatz
    count: int
    enabled: int  # wie viele davon aktiv sind

    @property
    def active(self) -> bool:
        return self.enabled > 0


def parse_rules(data: Any) -> list[Automation]:
    """Regeln aus der Summary-Antwort, gleiche Grundnamen zusammengefasst."""
    if not isinstance(data, list):
        return []
    groups: dict[str, list[bool]] = {}
    for rule in data:
        if not isinstance(rule, dict) or not isinstance(rule.get("name"), str):
            continue
        status = rule.get("status") if isinstance(rule.get("status"), dict) else {}
        enabled = str(status.get("statusDetail", "")).upper() != "DISABLED"
        base = _VARIANT.sub("", " ".join(rule["name"].split())) or rule["name"].strip()
        groups.setdefault(base, []).append(enabled)
    return [Automation(n, len(v), sum(v)) for n, v in sorted(groups.items())]


def normalize_state(value: object) -> str | None:
    """ "aktiv", "aus" oder None (kein Filter)."""
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    if word in _ACTIVE_WORDS:
        return "aktiv"
    if word in _OFF_WORDS:
        return "aus"
    return None


def _stem(token: str) -> str:
    return token[:5]


def filter_by_query(items: list[Automation], query: str) -> list[Automation]:
    wanted = [t for t in tokenize(query) if len(t) >= 3 and t not in _GENERIC]
    if not wanted:
        return items
    out = []
    for item in items:
        stems = {_stem(t) for t in tokenize(item.name)}
        if all(_stem(t) in stems for t in wanted):
            out.append(item)
    return out


def _names(items: list[Automation]) -> str:
    shown = [
        f"{a.name} ({a.count} Varianten)" if a.count > 1 else a.name for a in items[:LIST_LIMIT]
    ]
    text = ", ".join(shown)
    if len(items) > LIST_LIMIT:
        text += f" und {len(items) - LIST_LIMIT} weitere (mit einem Stichwort eingrenzen)"
    return text


def describe(items: list[Automation], state: str | None, query: str = "") -> str:
    """Antworttext (kurz, ohne Modell)."""
    if not items:
        return "Dazu gibt es keine Automation." if query else "Es gibt keine Automationen."
    if state == "aktiv":
        shown = [a for a in items if a.active]
        title = "Aktiv"
    elif state == "aus":
        shown = [a for a in items if not a.active]
        title = "Deaktiviert"
    else:
        shown = items
        title = "Es gibt"
    if not shown:
        return f"Keine passende Automation ist {'aktiv' if state == 'aktiv' else 'deaktiviert'}."
    total = sum(a.count for a in shown)
    if state is None:
        off = sum(a.count - a.enabled for a in shown)
        counts = f"{total - off} aktiv, {off} deaktiviert"
        return f"{title} {total} Automationen ({counts}): {_names(shown)}."
    return f"{title} sind {total} Automationen: {_names(shown)}."
