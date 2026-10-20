"""Namen und Ja/Nein aus kurzen Antworten lesen (Vorstellung: "Wie heißt du?" - "Ich bin Roman").

Bewusst klein und streng: Ein Name wird nur angenommen, wenn eine Frage danach offen war oder die
Äußerung ausdrücklich eine Vorstellung ist ("Mein Name ist ...", "Ich heiße ..."). "Ich bin müde"
ist kein Name.
"""

import re
from collections.abc import Iterable

from cat.intents.text import fold, tokenize

DECLINE = "decline"
_INTRO = re.compile(
    r"^(?:ich\s+bin|ich\s+hei(?:ß|ss)e|mein\s+name\s+ist|hier\s+ist|hier\s+spricht|"
    r"man\s+nennt\s+mich|nenn\s+mich|nennt\s+mich|das\s+ist)\s+(?P<name>.+)$",
    re.IGNORECASE,
)
# Nur ausdrückliche Vorstellungen gelten auch ohne offene Frage ("ich bin ..." gehört nicht dazu).
_EXPLICIT = re.compile(
    r"^(?:ich\s+hei(?:ß|ss)e|mein\s+name\s+ist|hier\s+spricht|nenn\s+mich|nennt\s+mich)\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'-]*")
_NOT_NAMES = frozenset(
    "ja nein ok okay hallo hey cat kat ich du er sie es wir ihr wer was wie wo wann warum bitte "
    "danke gut schlecht müde hier da also und oder aber doch nicht kein keine nichts alles egal "
    "später weiß keine ahnung dein deine name heiße heisse bin ist sind mein meine".split()
)
_DECLINE_TOKENS = frozenset(
    "nein nee noe nö nicht spaeter egal keine keinen niemand geheim lieber".split()
)
_YES = frozenset(
    "ja jap jo gerne klar okay ok mach genau stimmt richtig gern sicher natuerlich".split()
)
_NO = frozenset("nein nee noe nicht lieber keine".split())
_TRAILING = frozenset("hier übrigens und bitte nur eigentlich".split())
MAX_NAME_CHARS = 24


def is_decline(text: str) -> bool:
    tokens = set(tokenize(text))
    return bool(tokens & _DECLINE_TOKENS) and not (tokens & _YES)


_BE = re.compile(r"^(?i:also\s+|nein,?\s+|doch,?\s+)?(?i:ich\s+bin)\s+(?P<name>[A-ZÄÖÜ][\wäöüß-]+)")
_REMEMBER_NAME = re.compile(
    r"(?i:merk(?:e)?\s+dir|du\s+sollst\s+dir|nenn\s+mich|nennt\s+mich)\s+(?i:bitte\s+)?"
    r"(?P<name>[A-ZÄÖÜ][\wäöüß-]+)\s+(?i:als\s+(?:nutzer|benutzer|namen)|merken)",
)
_LEADING_NO = re.compile(r"^\s*(?:nein|nee|nö|noe|ne|doch)\b[\s,.!-]*", re.IGNORECASE)


def strip_negation(text: str) -> str:
    """ "Nein, Roman." -> "Roman."."""
    return _LEADING_NO.sub("", text, count=1).strip()


def _clean_name(candidate: str) -> str | None:
    words = [w for w in _WORD.findall(candidate) if w]
    while words and words[-1].lower() in _TRAILING:
        words.pop()
    if not words or len(words) > 2 or words[0].lower() in _NOT_NAMES:
        return None
    name = " ".join(w[0].upper() + w[1:] for w in words)
    return name if 2 <= len(name) <= MAX_NAME_CHARS else None


def parse_name(
    text: str, *, asked: bool, known: Iterable[str] = (), allow_new_be: bool = False
) -> str | None:
    """Der Name aus der Antwort, `DECLINE` bei Ablehnung, sonst None.

    `asked`: Cat hat gerade nach dem Namen gefragt (dann reicht auch ein einzelnes Wort).
    Ohne Frage gelten ausdrückliche Vorstellungen ("Ich heiße ...", "Mein Name ist ...",
    "Merk dir Roman als Nutzer") und "Ich bin <Name>" für bereits bekannte Namen, bei
    `allow_new_be` (Cat weiß gar nicht, wer spricht) auch für neue großgeschriebene Namen."""
    clean = text.strip().strip(".!?,;: ")
    if not clean:
        return None
    if asked and is_decline(clean):
        return DECLINE
    first = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)[0].strip(".!?,;: ")
    if match := _REMEMBER_NAME.search(clean):
        return _clean_name(match.group("name"))
    if match := (_INTRO if asked else _EXPLICIT).match(first):
        return _clean_name(match.group("name"))
    if asked:
        return _clean_name(first)
    if match := _BE.match(first):
        name = _clean_name(match.group("name"))
        if name and (allow_new_be or fold(name) in {fold(k) for k in known}):
            return name
    return None


def parse_yes_no(text: str) -> bool | None:
    tokens = set(tokenize(text))
    yes, no = bool(tokens & _YES), bool(tokens & _NO)
    if yes == no:
        return None
    return yes


_FORGET_VOICE = re.compile(
    r"\b(?:vergiss|loesch|lösch|loeschen|lösche)\w*\s+(?:meine|mein)\s+stimme\b", re.I
)
_FORGET_ME = re.compile(r"\b(?:vergiss|loesch|lösch)\w*\s+mich\b", re.I)


def wants_voice_forgotten(text: str) -> bool:
    return bool(_FORGET_VOICE.search(text))


def wants_person_forgotten(text: str) -> bool:
    return bool(_FORGET_ME.search(text))


_WHO = re.compile(
    r"\bwer\s+bin\s+ich\b|\bkennst\s+du\s+mich\b|\bwie\s+hei(?:ß|ss)e\s+ich\b|"
    r"\berkennst\s+du\s+(?:mich|meine\s+stimme)\b|\bkannst\s+du\s+meine\s+stimme\s+erkennen\b",
    re.IGNORECASE,
)


def asks_who_am_i(text: str) -> bool:
    return bool(_WHO.search(text))
