"""Regelbasierter Parser für deutsche Gerätebefehle (ohne LLM, ohne Internet)."""

from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from cat.intents.text import fold, parse_number, significant, tokenize
from cat.intents.vocabulary import Vocabulary

Kind = Literal["set", "query", "temperature"]

_QUESTION_START = {"ist", "sind", "laeuft", "brennt", "steht", "wie", "wieviel", "wo"}
_QUERY_WORDS = {"zustand", "status", "offen", "geschlossen", "verriegelt", "entriegelt"}
# Wörter, die nie zum Gerätenamen gehören.
_VERBS = frozenset(
    """
    schalte schalt mach mache stell stelle dimme dimm fahre fahr setze setz zeig zeige
    sag sage ist sind wie viel wieviel welche wo steht laeuft brennt zustand status wird
    helligkeit prozent grad auf zu mit damit ob alle aller
    """.split()
)
_TEMP_WORDS = ("temperatur", "warm", "kalt", "grad")


@dataclass(frozen=True)
class Parsed:
    kind: Kind
    command: str | None  # up/down/stop/lock/unlock/on/off oder eine Zahl als Text
    classes: frozenset[str]
    room: str | None
    phrase: str  # übrig gebliebene Namensbestandteile
    value: float | None


def _matches_word(token: str, word: str) -> bool:
    return token == word or (len(word) >= 4 and word in token)


def find_room(
    tokens: list[str], rooms: list[str], vocab: Vocabulary
) -> tuple[str | None, set[str]]:
    """Erkennt den Raum (auch in Zusammensetzungen wie "wohnzimmerlicht"). Gibt Raum und
    die dafür verbrauchten Tokens zurück."""
    joined = " ".join(tokens)
    best: tuple[int, str, set[str]] | None = None
    for room in rooms:
        names = [room, *vocab.room_synonyms.get(room, [])]
        for name in names:
            consumed = {t for t in tokens if t == name or (len(name) >= 4 and name in t)}
            if not consumed and len(name) >= 5:
                consumed = {
                    t for t in tokens if len(t) >= 5 and fuzz.ratio(t, name) >= 88
                }  # Tippfehler und Erkennungsfehler
            if not consumed and " " in name and name in joined:
                consumed = set(name.split())
            if consumed and (best is None or len(name) > best[0]):
                best = (len(name), room, consumed)
    if best is None:
        return None, set()
    return best[1], best[2]


def parse(text: str, rooms: list[str], vocab: Vocabulary) -> Parsed | None:
    raw_tokens = tokenize(text)
    if not raw_tokens:
        return None
    question = raw_tokens[0] in _QUESTION_START or raw_tokens[:2] == ["wie", "ist"]
    tokens = significant(raw_tokens)
    if not tokens:
        return None

    room, room_tokens = find_room(tokens, rooms, vocab)
    room_names = [room, *vocab.room_synonyms.get(room, [])] if room else []

    classes: set[str] = set()
    class_tokens: set[str] = set()
    residuals: dict[str, str] = {}  # "terrassenlampen" -> "lampen" (Raumwort abgezogen)
    for token in room_tokens:
        residual = token
        for name in room_names:
            residual = residual.replace(name, "")
        residuals[token] = residual
    for cls, words in vocab.classes.items():
        for token in tokens:
            probe = residuals.get(token, token)
            if len(probe) < 3:
                continue  # reines Raumwort
            if any(_matches_word(probe, w) for w in words):
                classes.add(cls)
                if any(probe == w for w in words):
                    class_tokens.add(token)

    command_words = vocab.command_words
    found: set[str] = set()
    command_tokens: set[str] = set()
    for i, token in enumerate(tokens):
        # "auf"/"zu" vor einer Zahl ("auf 21 Grad", "zu 30 Prozent") sind keine Richtungsbefehle.
        followed_by_number = i + 1 < len(tokens) and parse_number(tokens[i + 1]) is not None
        if token in ("auf", "zu") and followed_by_number:
            continue
        cmd = command_words.get(token)
        if cmd is None:
            cmd = next(
                (c for w, c in command_words.items() if len(w) >= 7 and token.startswith(w[:7])),
                None,
            )
        if cmd:
            found.add(cmd)
            command_tokens.add(token)

    value: float | None = None
    for token in tokens:
        number = parse_number(token)
        if number is not None and token not in command_tokens - {"ein"}:
            value = number
            break

    if len(found) > 1:
        return None  # widersprüchliche Befehle ("an" und "aus"): der Agent soll nachfragen
    command = next(iter(found), None)

    percent = "prozent" in tokens or "%" in tokens
    degrees = "grad" in tokens
    temp_words = any(any(w in t for w in _TEMP_WORDS) for t in tokens)

    kind: Kind
    if "temperature" in classes and not (value is not None and ("thermostat" in classes)):
        # "wie warm ist es im Wohnzimmer", "Temperatur draußen"
        if command in ("on", "off") or (value is not None and not degrees):
            return None
        kind, classes, command, value = "temperature", {"temperature"}, None, None
    elif "thermostat" in classes and value is not None and (degrees or "auf" in tokens):
        kind, command = "set", f"{value:g}"
    elif (
        "light" in classes
        and value is not None
        and (percent or "helligkeit" in tokens or any(t.startswith("dimm") for t in tokens))
    ):
        kind, command = "set", f"{value:g}"
    elif "shutter" in classes and value is not None and percent:
        kind, command = "set", f"{value:g}"
    elif question and (command is not None or any(t in _QUERY_WORDS for t in tokens)):
        kind, command = "query", None
    elif question and classes and not temp_words:
        kind, command = "query", None
    elif command is not None:
        kind = "set"
    else:
        return None

    consumed = room_tokens | class_tokens | command_tokens
    phrase_tokens = [
        t
        for t in tokens
        if t not in consumed
        and t not in _VERBS
        and t not in _QUERY_WORDS
        and parse_number(t) is None
        and t != "%"
    ]
    return Parsed(
        kind=kind,
        command=command,
        classes=frozenset(classes),
        room=room,
        phrase=" ".join(phrase_tokens),
        value=value,
    )


def clean_name(value: str) -> str:
    return " ".join(tokenize(fold(value)))
