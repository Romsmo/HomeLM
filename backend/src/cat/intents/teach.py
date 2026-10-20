"""Beibringen und Klarstellen, ohne Sprachmodell: Der Nutzer erklärt Cat etwas.

Das lokale Modell hält "Mit Dach-Rollo meine ich Rollo Roman und Rollo Marius" für einen Befehl und
fährt die Rollläden hoch. Erklärungen, Korrekturen und "merk dir" werden deshalb VOR dem Modell
erkannt und fest verarbeitet (schnell, ohne Fehlschaltung):

- **Begriff erklären:** "Mit Dach-Rollo meine ich Rollo Roman und Rollo Marius." Danach gilt "Mach
  die Dachrollos zu" für beide Geräte (`intents/lexicon.py`). Es zählt nur, wenn alle genannten
  Geräte eindeutig gefunden werden und der Begriff selbst kein Gerät ist.
- **Korrigieren:** "Ähm, bitte schließen, meinte ich." wendet das neue Wort auf die Geräte der
  letzten Schaltung an. Nie bei Türen, Schlössern oder Toren (dort immer ein vollständiger Befehl).
- **Merken:** "Merk dir, dass ..." oder "..., merk dir das" legt eine Notiz an.
- **Füllsatz aufnehmen:** "Nimm folgenden Füllsatz auf: ... (bei Schalten)".
- **Nachfragen:** "Was ist ein Dachrollo?", "Welche Begriffe kennst du?"
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cat.devices.commands import DeviceError
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService
from cat.intents.fillers import CATEGORIES, FillerBank, user_phrase
from cat.intents.lexicon import Lexicon
from cat.intents.replies import confirm_text
from cat.intents.text import fold, tokenize
from cat.memory.notes import NoteError
from cat.memory.service import MemoryService

log = logging.getLogger("cat.teach")

_SPLIT = re.compile(r"\s*(?:,|;|\bund\b|\bsowie\b|&|\bplus\b)\s*", re.IGNORECASE)
_ARTICLE = re.compile(r"^(?:der|die|das|den|dem|ein|eine|einen|alle|meine|mein)\s+", re.IGNORECASE)

_ALIAS_PATTERNS = (
    re.compile(
        r"^(?:also\s+|nein,?\s+)?(?:mit|unter)\s+(?P<term>.+?)\s+(?:meine|verstehe)\s+ich\s+"
        r"(?:immer\s+|damit\s+)?(?P<tgt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^wenn\s+ich\s+(?P<term>.+?)\s+sage,?\s+(?:dann\s+)?meine\s+ich\s+(?P<tgt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<term>.+?)\s+(?:meine\s+ich|ist|sind|bedeutet|bedeuten|heißt|heißen|steht\s+für)\s+"
        r"(?P<tgt>.+)$",
        re.IGNORECASE,
    ),
)
_FILLER = re.compile(r"füllsatz|fuellsatz", re.IGNORECASE)
_FILLER_VERB = re.compile(
    r"\b(?:nimm|nehm|nehme|füge|füg|speichere|speicher|ergänze|merk|merke|nehmen)\b", re.IGNORECASE
)
_FILLER_CATEGORY = (
    ("control", ("schalt", "befehl", "steuer", "mach")),
    ("lookup", ("nachsehen", "nachschau", "nachseh", "abfrage", "lesen", "fragen zu")),
    ("memory", ("merk", "notier", "speicher")),
    ("claude", ("claude", "schwer", "nachschlagen")),
    ("think", ("nachdenk", "überleg", "ueberleg", "denk")),
)
_REMEMBER_LEAD = re.compile(
    r"^(?:bitte\s+)?(?:merk(?:e)?\s+dir|notier(?:e)?(?:\s+dir)?|schreib(?:e)?\s+(?:dir\s+)?auf|"
    r"speicher(?:e)?(?:\s+dir)?)\s*[,:]?\s*(?:bitte\s+)?(?:dass\s+|folgendes[:,]?\s*)?(?P<fact>.+)$",
    re.IGNORECASE,
)
_REMEMBER_TAIL = re.compile(
    r"^(?P<fact>.+?)[,.;]?\s*(?:bitte\s+)?merk(?:e)?\s+dir\s+(?:das|es)(?:\s+bitte)?[.!]?$",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"\b(?:ich\s+meinte|meinte\s+ich|meine\s+ich|ich\s+meine)\b", re.IGNORECASE
)
_EXPLAIN = re.compile(
    r"^(?:was\s+(?:ist|sind|bedeutet|bedeuten|heißt|heißen)|was\s+meinst\s+du\s+mit)\s+"
    r"(?:ein|eine|der|die|das|dem|den)?\s*(?P<term>.+?)\s*\??$",
    re.IGNORECASE,
)
_WHICH_TERMS = re.compile(
    r"\b(?:welche|was\s+für)\s+(?:begriffe|wörter|woerter|namen)\b.*\b(?:kennst|weißt|weisst)\b",
    re.IGNORECASE,
)

_PERSONAL = frozenset("ich mein meine meinen meinem meiner wir uns unser unsere".split())
_CLOSE = ("schliess", "runter", "herunter", "zumach")
_OPEN = ("oeffn", "hoch", "rauf", "aufmach")
MAX_TARGETS = 8


@dataclass(frozen=True)
class Taught:
    text: str


class TeachService:
    def __init__(
        self,
        devices: DeviceService,
        lexicon: Lexicon,
        fillers: FillerBank,
        memory: MemoryService,
        audit: Any | None = None,
        speaker_name: Callable[[], str | None] = lambda: None,
        enabled: bool = True,
    ) -> None:
        self._devices = devices
        self._lexicon = lexicon
        self._fillers = fillers
        self._memory = memory
        self._audit = audit
        self._speaker = speaker_name
        self.enabled = enabled

    async def intercept(self, text: str) -> str | None:
        """Eine feste Antwort, wenn der Text etwas beibringt oder klarstellt, sonst None."""
        if not self.enabled:
            return None
        clean = " ".join(text.split()).strip()
        if not clean:
            return None
        for handler in (
            self._filler,
            self._explain,
            self._correction,
            self._remember,
            self._alias,
        ):
            reply = handler(clean)
            if isinstance(reply, Awaitable):
                reply = await reply
            if reply is not None:
                return reply
        return None

    # --- Füllsatz aufnehmen ---

    def _filler(self, text: str) -> str | None:
        if not (_FILLER.search(text) and _FILLER_VERB.search(text)):
            return None
        body = text.split(":", 1)[1] if ":" in text else ""
        if not body.strip():
            return ASK_FILLER
        hint = ""
        if match := re.search(r"\(([^)]*)\)\s*[.!]?\s*$", body):
            hint = match.group(1)
            body = body[: match.start()]
        elif match := re.search(r"\b(?:bei|für|fuer)\s+([\wäöüß ]+)$", body, re.IGNORECASE):
            hint = match.group(1)
            body = body[: match.start()]
        category = _category(hint or text.split(":", 1)[0])
        phrase = user_phrase(body)
        if phrase is None:
            return BAD_FILLER
        if not self._fillers.add_user(category, phrase):
            return "Diesen Füllsatz kenne ich schon."
        return f"Okay, neuer Füllsatz ({_CATEGORY_NAME[category]}): „{phrase}“"

    # --- Merken ---

    def _remember(self, text: str) -> str | None:
        match = _REMEMBER_TAIL.match(text) or _REMEMBER_LEAD.match(text)
        if match is None:
            return None
        fact = match.group("fact").strip().rstrip(".!")
        if len(fact) < 6:
            return None
        definition = bool(
            re.search(r"entspricht|bedeutet|heißt|ist gleich|meine ich|=", fact, re.I)
        )
        if not definition and set(tokenize(fact)) & _PERSONAL:
            return (
                None  # persönliche Fakten ("ich trinke ...") schreibt das Modell in dritter Person
            )
        who = self._speaker()
        title = " ".join(fact.split()[:5])[:40]
        topic = (
            "wortschatz"
            if re.search(r"entspricht|bedeutet|heißt|ist gleich", fact, re.I)
            else "allgemein"
        )
        tags = ["gemerkt", *([who] if who else [])]
        try:
            self._memory.remember(title, f"{who or 'Der Nutzer'} sagt: {fact}.", topic, tags)
        except NoteError as exc:
            return str(exc)
        extra = ""
        if re.search(r"rollo|rollladen|rolladen|markise|prozent", fact, re.I):
            extra = " Für Rollläden gilt bei mir: 0 Prozent ist offen, 100 Prozent ist zu."
        return f"Okay, ich habe mir gemerkt: {fact}.{extra}"

    # --- Begriffe erklären ---

    def _targets(self, raw: str) -> list[DeviceSpec] | None:
        parts = [p for p in _SPLIT.split(raw.strip().rstrip(".!?")) if p.strip()]
        if not 1 <= len(parts) <= MAX_TARGETS:
            return None
        specs: list[DeviceSpec] = []
        for part in parts:
            name = _ARTICLE.sub("", part.strip())
            try:
                spec = self._devices.resolve(name)
            except DeviceError:
                return None  # nur wenn ALLE Geräte eindeutig gefunden werden
            if not _covers(spec, name):
                return None  # unscharfer Treffer ("Haus" -> "Haustür"): nicht raten
            if spec not in specs:
                specs.append(spec)
        return specs

    def _alias(self, text: str) -> str | None:
        for pattern in _ALIAS_PATTERNS:
            match = pattern.match(text.rstrip(".! "))
            if match is None:
                continue
            term = _ARTICLE.sub("", match.group("term").strip())
            if not term or len(term.split()) > 4 or term.lower().split()[0] in _QUESTION_WORDS:
                continue
            try:
                self._devices.resolve(term)
                continue  # der Begriff ist selbst ein Gerät: keine Erklärung
            except DeviceError:
                pass
            specs = self._targets(match.group("tgt"))
            if not specs:
                continue
            try:
                self._lexicon.add(term, [s.id for s in specs])
            except ValueError as exc:
                return str(exc)
            names = _join([s.name for s in specs])
            return f"Okay, ab jetzt verstehe ich „{term}“ als {names}."
        return None

    def _explain(self, text: str) -> str | None:
        if _WHICH_TERMS.search(text):
            rows = self._lexicon.listing()
            if not rows:
                return NO_TERMS
            return "Ich kenne: " + "; ".join(f"„{r['term']}“" for r in rows) + "."
        match = _EXPLAIN.match(text)
        if match is None:
            return None
        term = self._lexicon.lookup(match.group("term"))
        if term is None:
            return None
        known = {s.id: s.name for s in self._devices.specs}
        names = _join([known[i] for i in term.ids if i in known])
        return f"„{term.term}“ habe ich von dir als {names} gelernt."

    # --- Korrigieren ---

    async def _correction(self, text: str) -> str | None:
        if _CORRECTION.search(text) is None:
            return None
        tokens = tokenize(text)
        command = _command_word(tokens, text)
        if command is None:
            return None
        group = self._devices.last_group()
        if not group:
            return "Ich weiß gerade nicht, welches Gerät du meinst. Sag es bitte als ganzen Befehl."
        lines: list[str] = []
        for spec, _ in group:
            if spec.effective_risk == "high":
                return (
                    "Bei Türen, Schlössern und Toren brauche ich immer einen vollständigen Befehl."
                )
            wanted = _fit(spec, command)
            if wanted is None:
                continue
            try:
                result = await self._devices.command_detailed(spec.id, wanted, source="correction")
            except DeviceError as exc:
                lines.append(str(exc))
                continue
            lines.append(confirm_text(result.spec, result.command))
        if not lines:
            return "Das passt nicht zu den Geräten von eben. Sag es bitte als ganzen Befehl."
        if self._audit is not None:
            await self._audit.record(
                "correction", {"text": text, "command": command}, " ".join(lines), source="teach"
            )
        return "\n".join(lines)


ASK_FILLER = (
    "Welchen Füllsatz soll ich aufnehmen? Sag zum Beispiel: Nimm folgenden Füllsatz auf: "
    "Ich bin gleich so weit (bei Schalten)."
)
BAD_FILLER = (
    "Den Satz nehme ich nicht auf: Er soll kurz sein (höchstens 9 Wörter) und ohne Zahlen oder "
    "Sonderzeichen."
)
NO_TERMS = (
    "Ich kenne noch keine Begriffe von dir. Erkläre mir zum Beispiel: Mit Dachrollos meine ich "
    "Romans Rollo und Marius Rollo."
)
_QUESTION_WORDS = frozenset("was wer wie wo wann warum wieso welche welcher welches ob".split())
_CATEGORY_NAME = {
    "control": "Schalten",
    "lookup": "Nachsehen",
    "memory": "Merken",
    "think": "Nachdenken",
    "claude": "Claude",
}


def _covers(spec: DeviceSpec, name: str) -> bool:
    """Kommen alle Wörter der Eingabe (auf 5 Buchstaben genau) im Gerätenamen oder Raum vor?"""
    have = {t[:5] for t in tokenize(f"{spec.name} {spec.room} {' '.join(spec.synonyms)}")}
    wanted = [t[:5] for t in tokenize(name) if len(t) >= 3]
    return bool(wanted) and all(w in have for w in wanted)


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " und " + names[-1]


def _category(hint: str) -> str:
    folded = fold(hint)
    for category, words in _FILLER_CATEGORY:
        if any(w in folded for w in words):
            return category if category in CATEGORIES else "think"
    return "think"


def _command_word(tokens: list[str], text: str) -> str | None:
    """Das neue Wort der Korrektur: schließen, öffnen, an, aus oder eine Prozentzahl."""
    if match := re.search(r"(\d{1,3})\s*(?:%|prozent)", text, re.IGNORECASE):
        return match.group(1)
    if any(t.startswith(_CLOSE) or t == "zu" for t in tokens):
        return "close"
    if any(t.startswith(_OPEN) or t in ("auf", "offen") for t in tokens):
        return "open"
    if "aus" in tokens or any(t.startswith(("ausmach", "ausschalt")) for t in tokens):
        return "off"
    if (
        "an" in tokens
        or "ein" in tokens
        or any(t.startswith(("anmach", "anschalt")) for t in tokens)
    ):
        return "on"
    return None


def _fit(spec: DeviceSpec, command: str) -> str | None:
    """Das Wort als Befehl, der zum Gerätetyp passt (sonst None)."""
    if command.isdigit():
        return command if spec.type in ("shutter", "dimmer", "thermostat") else None
    if spec.type == "shutter":
        return {"close": "down", "open": "up"}.get(command)
    if spec.type in ("light", "switch", "dimmer"):
        return command if command in ("on", "off") else None
    return None
