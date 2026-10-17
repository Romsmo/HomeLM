"""Cat lernt aus Wiederholungen: Was das Modell mehrfach gleich löst, geht künftig sofort.

Es gibt keine vorgefertigten Befehlssätze. Stattdessen beobachtet Cat, was bei einer Anfrage
passiert ist (welche Geräte-Werkzeuge das Modell aufgerufen hat). Führt dieselbe Formulierung
`learn_after` Mal (reine Abfragen: sofort) zu denselben Aktionen, merkt sich Cat sie als
Kurzbefehl und führt sie danach ohne Sprachmodell aus (Antwort in Millisekunden, auch offline).

Bausteine, damit nicht jede Formulierung einzeln gelernt werden muss:
- Gerät als Platzhalter: Steht der Name (oder ein Synonym) des Geräts wörtlich im Satz, wird er
  zum Platzhalter {dev}. "schalte deckenlicht roman an" gilt dann auch für "schalte
  deckenlicht marius an", ohne dass das je gesagt wurde.
- Zahl als Platzhalter: "fahre romans rollo auf 50 prozent" gilt auch für "... auf 30 prozent".
- Mehrere Geräte in einem Satz ("gute nacht") werden als Ablauf gelernt, ganz ohne Platzhalter.

Schutz vor falschem Lernen:
- Gelernt wird nur, wenn alle Werkzeuge der Anfrage Geräte-Werkzeuge waren und erfolgreich liefen.
- Sätze, die sich auf das Gespräch beziehen ("mach es wieder aus" direkt nach demselben Gerät),
  werden nicht gelernt. Bei bekanntem Raum (Satellit) gilt eine Formulierung nur in diesem Raum.
- Führt dieselbe Formulierung einmal zu anderen Aktionen, beginnt das Zählen von vorn.
- Ausgeführt wird immer über denselben Gerätedienst wie sonst (Modus, Risikostufe, Bestätigung).
- Verschwindet ein Gerät, wird der Kurzbefehl vergessen. Alles Gelernte ist in der Oberfläche
  sichtbar und einzeln löschbar.
"""

import contextlib
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cat.agent.tools import ToolTrace
from cat.devices.commands import DeviceError, normalize_command
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService
from cat.intents.replies import confirm_text, state_line
from cat.intents.text import fold, tokenize

log = logging.getLogger("cat.learning")

MAX_ENTRIES = 300
MAX_ACTIONS = 8
_SLOT = re.compile(r"\{(dev|n)\}")
_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
LEARNABLE_TOOLS = {"set_state", "get_state"}
IGNORED_TOOLS = {"list_devices"}  # Nachschlagen ändert nichts am Ergebnis


def phrase_of(text: str) -> str:
    """Formulierung als Schlüssel: Kleinschreibung, ohne Satzzeichen, Umlaute aufgelöst."""
    return " ".join(tokenize(text))


@dataclass
class Action:
    kind: str  # "set" oder "get"
    device: str  # Geräte-id oder "{dev}"
    command: str | None = None  # kanonischer Befehl oder "{n}"

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "device": self.device, "command": self.command}


@dataclass
class Shortcut:
    key: str
    actions: list[Action]
    count: int = 1
    active: bool = False
    created: float = field(default_factory=time.time)
    last_used: float | None = None
    uses: int = 0

    @property
    def id(self) -> str:
        return hashlib.sha1(self.key.encode(), usedforsecurity=False).hexdigest()[:12]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "actions": [a.as_dict() for a in self.actions],
            "count": self.count,
            "active": self.active,
            "created": self.created,
            "last_used": self.last_used,
            "uses": self.uses,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Shortcut":
        return cls(
            key=str(raw["key"]),
            actions=[Action(a["kind"], a["device"], a.get("command")) for a in raw["actions"]],
            count=int(raw.get("count", 1)),
            active=bool(raw.get("active", False)),
            created=float(raw.get("created", time.time())),
            last_used=raw.get("last_used"),
            uses=int(raw.get("uses", 0)),
        )


@dataclass(frozen=True)
class LearnedResult:
    text: str
    device_id: str | None
    command: str | None
    match_ms: float
    total_ms: float


class Learner:
    def __init__(
        self, path: Path, devices: DeviceService, learn_after: int = 2, enabled: bool = True
    ) -> None:
        self._path = path
        self._devices = devices
        self._after = max(1, learn_after)
        self.enabled = enabled
        self._entries: dict[str, Shortcut] = {}
        self._load()

    # --- Speicher ---

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = {s["key"]: Shortcut.from_dict(s) for s in raw.get("shortcuts", [])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("%s ist unlesbar, es wird neu gelernt", self._path)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            data = {"shortcuts": [s.as_dict() for s in self._entries.values()]}
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Gelerntes konnte nicht gespeichert werden")

    def listing(self) -> list[dict[str, Any]]:
        """Für die Oberfläche: gelernte (aktive) Kurzbefehle zuerst, mit lesbarer Beschreibung."""
        rows = []
        for s in sorted(self._entries.values(), key=lambda e: (not e.active, -(e.last_used or 0))):
            rows.append(
                {
                    "id": s.id,
                    "phrase": s.key,
                    "does": self._describe(s),
                    "active": s.active,
                    "seen": s.count,
                    "needed": self._needed(s),
                    "uses": s.uses,
                }
            )
        return rows

    def _needed(self, shortcut: Shortcut) -> int:
        """Reine Abfragen ändern nichts und werden schon nach dem ersten Mal gelernt."""
        return 1 if all(a.kind == "get" for a in shortcut.actions) else self._after

    def forget(self, shortcut_id: str) -> bool:
        for key, entry in list(self._entries.items()):
            if entry.id == shortcut_id:
                del self._entries[key]
                self._save()
                return True
        return False

    def clear(self) -> None:
        self._entries.clear()
        self._save()

    def _describe(self, shortcut: Shortcut) -> str:
        parts = []
        for a in shortcut.actions:
            spec = self._devices.resolve_exact(a.device) if a.device != "{dev}" else None
            who = "{Gerät}" if a.device == "{dev}" else (spec.name if spec else a.device)
            verb = "lesen" if a.kind == "get" else f"senden: {a.command}"
            parts.append(f"{who} ({verb})")
        return ", ".join(parts)

    # --- Lernen ---

    def observe(
        self,
        text: str,
        trace: list[ToolTrace],
        room: str | None = None,
        previous_device: str | None = None,
        context: list[tuple[str, str]] | None = None,
    ) -> Shortcut | None:
        """Nach einer Anfrage, die das Modell gelöst hat. Gibt den Kurzbefehl zurück, wenn er
        dadurch NEU aktiv wurde (dann sagt Cat dem Nutzer, was es sich gemerkt hat)."""
        if not self.enabled or not phrase_of(text):
            return None
        used = [t for t in trace if t.tool not in IGNORED_TOOLS]
        if not used:
            # Nur nachgeschlagen: Findet list_devices genau ein Gerät, war das die Antwort auf eine
            # Frage nach diesem Gerät ("ist das licht an").
            looked = [t for t in trace if t.tool == "list_devices" and t.ok]
            single = [_single_device(t.result) for t in looked]
            if len(looked) == 1 and single[0] is not None:
                used = [ToolTrace("get_state", {"device": single[0]}, True, "")]
        if not used or len(used) > MAX_ACTIONS:
            return None
        if any(t.tool not in LEARNABLE_TOOLS or not t.ok for t in used):
            return None  # andere Werkzeuge (Gedächtnis, Stage, Rechnen ...) oder ein Fehler
        built = self._actions(used)
        if built is None:
            return None
        specs, actions = built
        key, actions = self._generalize(text, specs, actions, room, previous_device, context)
        if key is None:
            return None

        entry = self._entries.get(key)
        if entry is not None and [a.as_dict() for a in entry.actions] == [
            a.as_dict() for a in actions
        ]:
            entry.count += 1
        else:
            entry = Shortcut(key=key, actions=actions)  # neu, oder andere Aktionen: von vorn
            self._entries[key] = entry
        became_active = False
        if not entry.active and entry.count >= self._needed(entry):
            entry.active = True
            became_active = True
        self._trim()
        self._save()
        return entry if became_active else None

    def _actions(self, used: list[ToolTrace]) -> tuple[list[DeviceSpec], list[Action]] | None:
        specs: list[DeviceSpec] = []
        actions: list[Action] = []
        for t in used:
            ref = t.args.get("device")
            spec = self._devices.resolve_exact(ref) if isinstance(ref, str) else None
            if spec is None:
                return None
            if t.tool == "set_state":
                raw = t.args.get("command")
                if not isinstance(raw, str):
                    return None
                try:
                    command = normalize_command(spec, raw)
                except DeviceError:
                    return None
                actions.append(Action("set", spec.id, command))
            else:
                actions.append(Action("get", spec.id))
            specs.append(spec)
        return specs, actions

    def _generalize(
        self,
        text: str,
        specs: list[DeviceSpec],
        actions: list[Action],
        room: str | None = None,
        previous_device: str | None = None,
        context: list[tuple[str, str]] | None = None,
    ) -> tuple[str | None, list[Action]]:
        phrase = phrase_of(text)
        if len(actions) > 1:
            return _scoped(room, phrase), actions  # Ablauf: nur wörtlich, nur wenn stabil
        spec, action = specs[0], actions[0]
        names = sorted(
            {phrase_of(n) for n in [spec.name, spec.id.replace("_", " "), *spec.synonyms]},
            key=len,
            reverse=True,
        )
        template, slotted = phrase, False
        for name in names:
            if name and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", phrase):
                template = re.sub(
                    rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", "{dev}", phrase, count=1
                )
                slotted = True
                break
        if not slotted and (
            spec.id == previous_device or _named_in_context(spec, phrase, context or [])
        ):
            # Das Gerät war gerade im Gespräch (vom Nutzer genannt, vom Modell angeboten oder eben
            # bedient): "mach es aus", "ja" hängen vom Gespräch ab, nicht von der Formulierung.
            return None, actions
        # Ohne Gerätenamen im Satz ("wie warm ist es draußen", "mach das licht an" im Raum) gilt
        # die Formulierung wörtlich für dieses Gerät, bei bekanntem Raum nur in diesem Raum.
        scope = room if room and fold(spec.room) == fold(room) else None
        new = Action(action.kind, "{dev}" if slotted else action.device, action.command)
        if new.command is not None and _NUMBER.match(new.command):
            number = new.command.replace(".", ",")
            tokens = template.split()
            for i, token in enumerate(tokens):
                if token.replace(".", ",") == number:
                    tokens[i] = "{n}"
                    new.command = "{n}"
                    break
            template = " ".join(tokens)
        return _scoped(None if slotted else scope, template), [new]

    def _trim(self) -> None:
        if len(self._entries) <= MAX_ENTRIES:
            return
        ordered = sorted(self._entries.values(), key=lambda e: (e.active, e.last_used or e.created))
        for entry in ordered[: len(self._entries) - MAX_ENTRIES]:
            del self._entries[entry.key]

    # --- Anwenden ---

    def match(self, text: str, room: str | None = None) -> tuple[Shortcut, dict[str, str]] | None:
        """Passender aktiver Kurzbefehl und die Werte der Platzhalter (rein, ohne Netzwerk).
        Kurzbefehle für den aktuellen Raum gehen vor allgemeinen."""
        phrase = phrase_of(text)
        if not phrase:
            return None
        if room:
            scoped = self._entries.get(_scoped(room, phrase))
            if scoped is not None and scoped.active:
                return scoped, {}
        entry = self._entries.get(phrase)
        if entry is not None and entry.active:
            return entry, {}
        best: tuple[int, Shortcut, dict[str, str]] | None = None
        for entry in self._entries.values():
            if not entry.active or "{" not in entry.key:
                continue
            found = _template_match(entry.key, phrase)
            if found is None:
                continue
            score = len(entry.key.replace("{dev}", "").replace("{n}", ""))  # genauer = mehr Text
            if best is None or score > best[0]:
                best = (score, entry, found)
        return (best[1], best[2]) if best else None

    async def handle(self, text: str, room: str | None = None) -> LearnedResult | None:
        started = time.perf_counter()
        if not self.enabled:
            return None
        matched = self.match(text, room)
        match_ms = (time.perf_counter() - started) * 1000
        if matched is None:
            return None
        entry, slots = matched
        resolved: list[tuple[Action, DeviceSpec, str | None]] = []
        for action in entry.actions:
            device = slots.get("dev") if action.device == "{dev}" else action.device
            spec = self._devices.resolve_exact(device) if device else None
            if spec is None:
                if action.device != "{dev}":
                    self._forget_entry(entry)  # das Gerät gibt es nicht mehr
                return None  # Platzhalter ohne bekanntes Gerät: das Modell soll entscheiden
            command = slots.get("n") if action.command == "{n}" else action.command
            if action.command == "{n}":
                try:
                    command = normalize_command(spec, command or "")
                except DeviceError:
                    return None  # z. B. 500 Prozent: nicht raten, das Modell erklärt es
            resolved.append((action, spec, command))
        lines: list[str] = []
        for action, spec, command in resolved:
            try:
                if action.kind == "set":
                    await self._devices.command(spec.id, command or "", source="learned")
                    lines.append(confirm_text(spec, command or ""))
                else:
                    info = await self._devices.get_state(spec.id)
                    lines.append(state_line(spec, info))
            except DeviceError as exc:
                lines.append(str(exc))
                break
        entry.uses += 1
        entry.last_used = time.time()
        self._save()
        total_ms = (time.perf_counter() - started) * 1000
        last = resolved[-1]
        return LearnedResult(" ".join(lines), last[1].id, last[2], match_ms, total_ms)

    def _forget_entry(self, entry: Shortcut) -> None:
        with contextlib.suppress(KeyError):
            del self._entries[entry.key]
            self._save()


def _named_in_context(spec: DeviceSpec, phrase: str, context: list[tuple[str, str]]) -> bool:
    """Steht der Gerätename in den letzten Nachrichten? Nachrichten, die zur selben Formulierung
    gehören (frühere gleiche Frage samt Antwort), zählen nicht: sonst ließe sich nie etwas
    Wiederholtes lernen."""
    names = {phrase_of(n) for n in (spec.name, *spec.synonyms) if phrase_of(n)}
    for i, (role, text) in enumerate(context):
        if role == "user" and phrase_of(text) == phrase:
            continue
        if role == "assistant" and i > 0 and context[i - 1][0] == "user":
            if phrase_of(context[i - 1][1]) == phrase:
                continue
        folded = phrase_of(text)
        if any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", folded) for n in names):
            return True
    return False


def _single_device(result: str) -> str | None:
    """id des einzigen Geräts in einem list_devices-Ergebnis, sonst None."""
    rows = [line for line in result.splitlines()[1:] if line.count(" | ") >= 5]
    if len(rows) != 1:
        return None
    return rows[0].split(" | ", 1)[0].strip() or None


def _scoped(room: str | None, phrase: str) -> str:
    """Schlüssel mit Raum ("kueche|mach das licht an"), ohne Raum nur die Formulierung."""
    return f"{' '.join(tokenize(room))}|{phrase}" if room else phrase


def _template_match(template: str, phrase: str) -> dict[str, str] | None:
    pattern, last = "", 0
    for m in _SLOT.finditer(template):
        pattern += re.escape(template[last : m.start()])
        pattern += r"(?P<dev>.+?)" if m.group(1) == "dev" else r"(?P<n>\d+(?:[.,]\d+)?)"
        last = m.end()
    pattern += re.escape(template[last:])
    found = re.fullmatch(pattern, phrase)
    return {k: v for k, v in found.groupdict().items() if v} if found else None
