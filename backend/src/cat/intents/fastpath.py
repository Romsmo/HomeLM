"""Fast-Path: Gerätebefehle ohne LLM, ohne Internet. Läuft vor dem Agenten.

Trifft der Parser oder die Gerätezuordnung nicht eindeutig, liefert `handle` None und der Text
geht an den Agenten. Geraten wird nie: Bei Mehrdeutigkeit entscheidet der Agent mit Rückfrage.
"""

import logging
import time
from dataclasses import dataclass

from rapidfuzz import fuzz

from cat.devices.commands import DeviceError
from cat.devices.models import DeviceInfo, DeviceSpec, DeviceType
from cat.devices.service import DeviceService
from cat.intents.parser import Parsed, parse
from cat.intents.text import fold
from cat.intents.vocabulary import Vocabulary

log = logging.getLogger("cat.intents")

_TYPES_FOR_CLASS: dict[str, set[DeviceType]] = {
    "light": {"light", "dimmer", "switch"},
    "switch": {"switch", "light"},
    "shutter": {"shutter"},
    "thermostat": {"thermostat"},
    "garage": {"garage", "door"},
    "door": {"door", "lock"},
    "lock": {"lock"},
    "temperature": {"sensor", "thermostat"},
}
# Welche Gerätetypen ein Befehl überhaupt sinnvoll bedienen kann (verengt die Auswahl).
_TYPES_FOR_COMMAND: dict[str, set[DeviceType]] = {
    "on": {"light", "switch", "dimmer"},
    "off": {"light", "switch", "dimmer"},
    "lock": {"lock"},
    "unlock": {"lock"},
}
NAME_CUTOFF = 75.0
NAME_MARGIN = 8.0


@dataclass(frozen=True)
class FastPathResult:
    text: str
    device_id: str | None
    command: str | None
    match_ms: float  # Zeit für Parser und Gerätezuordnung (ohne Backend-Aufruf)
    total_ms: float


def _score(phrase: str, spec: DeviceSpec) -> float:
    names = [fold(spec.name), *(fold(s) for s in spec.synonyms)]
    return max(max(fuzz.WRatio(phrase, n), fuzz.token_set_ratio(phrase, n)) for n in names)


def select_device(
    parsed: Parsed,
    specs: list[DeviceSpec],
    infos: dict[str, DeviceInfo],
    default_room: str | None,
) -> DeviceSpec | None:
    """Wählt genau ein Gerät oder None (nichts passt oder mehrdeutig)."""
    types: set[DeviceType] | None = None
    for cls in parsed.classes:
        types = (types or set()) | _TYPES_FOR_CLASS.get(cls, set())
    candidates = [s for s in specs if types is None or s.type in types]
    if parsed.kind == "temperature":
        candidates = [s for s in candidates if _is_temperature(s, infos.get(s.id))]
        sensors = [s for s in candidates if s.type == "sensor"]
        candidates = sensors or candidates  # Sensoren zuerst, Thermostate nur als Ersatz
    if parsed.kind == "set" and parsed.command is not None:
        candidates = [s for s in candidates if s.type != "sensor"]
        allowed = _TYPES_FOR_COMMAND.get(parsed.command)
        if allowed is None and parsed.command.replace(".", "", 1).isdigit():
            allowed = {"dimmer", "shutter", "thermostat"}
        narrowed = [s for s in candidates if allowed is None or s.type in allowed]
        candidates = narrowed or candidates

    room = parsed.room or default_room
    if room:
        wanted = fold(room)
        in_room = [s for s in candidates if fold(s.room) == wanted]
        if in_room or parsed.room:  # genannter Raum ist verbindlich, Standardraum nur Vorgabe
            candidates = in_room

    if not candidates:
        return None
    if parsed.phrase:
        scored = sorted(((_score(parsed.phrase, s), s) for s in candidates), key=lambda x: -x[0])
        scored = [(sc, s) for sc, s in scored if sc >= NAME_CUTOFF]
        if not scored:
            return None
        if len(scored) == 1 or scored[0][0] - scored[1][0] >= NAME_MARGIN:
            return scored[0][1]
        return None
    return candidates[0] if len(candidates) == 1 else None


def _is_temperature(spec: DeviceSpec, info: DeviceInfo | None) -> bool:
    if spec.type == "thermostat":
        return True
    if info is not None and info.unit and info.unit.strip().lower() in ("°c", "c"):
        return True
    return "temp" in fold(spec.name)


class FastPath:
    def __init__(self, devices: DeviceService, vocab: Vocabulary) -> None:
        self._devices = devices
        self._vocab = vocab

    def _rooms(self) -> list[str]:
        return sorted({fold(s.room) for s in self._devices.specs})

    def match(self, text: str, default_room: str | None = None) -> tuple[Parsed, DeviceSpec] | None:
        """Parser und Zuordnung (rein, ohne Netzwerk)."""
        if not self._devices.specs:
            return None
        parsed = parse(text, self._rooms(), self._vocab)
        if parsed is None:
            return None
        infos = {i.id: i for i in self._devices.snapshot()}
        spec = select_device(parsed, self._devices.specs, infos, default_room)
        return (parsed, spec) if spec else None

    async def handle(self, text: str, default_room: str | None = None) -> FastPathResult | None:
        started = time.perf_counter()
        matched = self.match(text, default_room)
        match_ms = (time.perf_counter() - started) * 1000
        if matched is None:
            return None
        parsed, spec = matched
        try:
            if parsed.kind == "set":
                command = finalize_command(spec, parsed.command or "")
                await self._devices.command(spec.id, command, source="fastpath")
                answer = confirm_text(spec, command)
            else:
                info = await self._devices.get_state(spec.id)
                answer = state_text(spec, info, parsed)
                command = None
        except DeviceError as exc:
            answer, command = str(exc), parsed.command
        total_ms = (time.perf_counter() - started) * 1000
        log.info("fastpath %s -> %s (Zuordnung %.1f ms)", parsed.kind, spec.id, match_ms)
        return FastPathResult(answer, spec.id, command, match_ms, total_ms)


def finalize_command(spec: DeviceSpec, word: str) -> str:
    """Wortbefehl je Gerätetyp: up/down heißen bei Schlössern und Türen anders."""
    if spec.type == "lock":
        return {"up": "unlock", "down": "lock"}.get(word, word)
    if spec.type in ("door", "garage"):
        return {"up": "open", "down": "close"}.get(word, word)
    return word


def _num(value: str) -> str:
    return value.replace(".", ",")


def confirm_text(spec: DeviceSpec, command: str) -> str:
    n = spec.name
    texts = {
        "on": f"Okay, {n} ist an.",
        "off": f"Okay, {n} ist aus.",
        "up": f"Okay, {n} fährt hoch.",
        "down": f"Okay, {n} fährt runter.",
        "stop": f"Okay, {n} hält an.",
        "lock": f"Okay, {n} ist verriegelt.",
        "unlock": f"Okay, {n} ist entriegelt.",
        "open": f"Okay, {n} wird geöffnet.",
        "close": f"Okay, {n} wird geschlossen.",
    }
    if command in texts:
        return texts[command]
    if spec.type == "thermostat":
        return f"Okay, {n} ist auf {_num(command)} Grad gestellt."
    if spec.type == "shutter":
        return f"Okay, {n} ist auf {_num(command)} Prozent zu."
    return f"Okay, {n} steht auf {_num(command)} Prozent."


def state_text(spec: DeviceSpec, info: DeviceInfo, parsed: Parsed) -> str:
    n = spec.name
    if not info.online:
        return f"{n} ist gerade nicht erreichbar."
    if info.state is None:
        return f"Den Zustand von {n} kenne ich nicht."
    state = info.state
    unit = info.unit or ""
    if parsed.kind == "temperature":
        place = f" im Raum {spec.room}" if parsed.room else ""
        return f"{n}{place}: {_num(state)} {unit}".strip() + "."
    if state.upper() in ("ON", "OFF"):
        return f"{n} ist {'an' if state.upper() == 'ON' else 'aus'}."
    if spec.type == "shutter" and state.replace(".", "").isdigit():
        pos = float(state)
        if pos <= 0:
            return f"{n} ist offen."
        if pos >= 100:
            return f"{n} ist zu."
        return f"{n} ist zu {_num(state)} Prozent geschlossen."
    words = {
        "locked": "verriegelt",
        "unlocked": "entriegelt",
        "open": "offen",
        "closed": "geschlossen",
    }
    return f"{n}: {words.get(state.lower(), _num(state))} {unit}".strip() + (
        "." if state.lower() not in words else ""
    )
