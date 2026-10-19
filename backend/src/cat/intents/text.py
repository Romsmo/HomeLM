"""Textaufbereitung für deutsche Sprachbefehle: Normalisieren, Füllwörter, Zahlwörter."""

import re

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"})
_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?|%")

# Füllwörter, Höflichkeitsformen und Artikel: tragen nichts zum Befehl bei.
FILLERS = frozenset(
    """
    aehm aeh ahm ehm hm hmm oeh also bitte mal doch eben ey hey cat okay ok kurz schnell
    gerne bitteschoen dann und jetzt mir mich fuer koennte koenntest kannst kann du wuerdest
    wuerde ich moechte will eigentlich vielleicht einfach naja sag sage mal bist da noch bisschen
    nur es man denn heute gerade momentan aktuell
    das die der den dem des im in ins vom von zum zur am eine einen einer
    """.split()
)

_UNITS = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwoelf": 12,
    "dreizehn": 13, "vierzehn": 14, "fuenfzehn": 15, "sechzehn": 16, "siebzehn": 17,
    "achtzehn": 18, "neunzehn": 19,
}  # fmt: skip
_TENS = {
    "zwanzig": 20, "dreissig": 30, "vierzig": 40, "fuenfzig": 50, "sechzig": 60,
    "siebzig": 70, "achtzig": 80, "neunzig": 90,
}  # fmt: skip


def fold(text: str) -> str:
    """Kleinschreibung, Umlaute und ß aufgelöst: Grundlage für alle Vergleiche."""
    return text.lower().translate(_FOLD)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(fold(text))


def number_word(token: str) -> int | None:
    """Zahlwort (0 bis 100) als Zahl, z. B. "einundzwanzig" -> 21."""
    if token == "hundert":
        return 100
    if token in _UNITS:
        return _UNITS[token]
    if token in _TENS:
        return _TENS[token]
    if "und" in token:
        unit, _, tens = token.partition("und")
        if unit in _UNITS and tens in _TENS and 1 <= _UNITS[unit] <= 9:
            return _TENS[tens] + _UNITS[unit]
    return None


def parse_number(token: str) -> float | None:
    """Ziffern ("21,5") oder Zahlwörter ("einundzwanzig")."""
    if token and token[0].isdigit():
        try:
            return float(token.replace(",", "."))
        except ValueError:
            return None
    word = number_word(token)
    return float(word) if word is not None else None


def significant(tokens: list[str]) -> list[str]:
    """Tokens ohne Füllwörter."""
    return [t for t in tokens if t not in FILLERS]


# Satzanfänge von Fragen (gefaltet).
QUESTION_STARTS = frozenset(
    "ist sind wie wo was welche welcher welches wer wann warum wieso wieviel wieviele steht stehen "
    "laeuft brennt hat haben gibt kann zeig zeige sag sage nenn nenne lies zaehle zaehl liste "
    "gib erzaehl erzaehle beschreibe finde suche".split()
)


def is_question(text: str) -> bool:
    """Fragezeichen oder Fragewort am Anfang. Sprachtexte haben nicht immer ein Fragezeichen."""
    tokens = tokenize(text)
    return "?" in text or bool(tokens) and tokens[0] in QUESTION_STARTS


_ON_WORDS = frozenset("an ein anmachen anschalten einschalten einmachen aktivieren".split())
_OFF_WORDS = frozenset("aus ausmachen ausschalten abschalten deaktivieren".split())


def power_conflict(user_text: str, command: str) -> str | None:
    """Sagt der Nutzer "aus", das Modell sendet aber "on" (oder umgekehrt)? Dann das Wort des
    Nutzers, sonst None. Nur bei eindeutiger Richtung (nicht "das eine an, das andere aus")."""
    tokens = set(tokenize(user_text))
    wants_on, wants_off = bool(tokens & _ON_WORDS), bool(tokens & _OFF_WORDS)
    if wants_on == wants_off:
        return None
    if command == "on" and wants_off:
        return "aus"
    if command == "off" and wants_on:
        return "an"
    return None


_CONTROL_CUES = (
    _ON_WORDS
    | _OFF_WORDS
    | frozenset(
        "hoch runter herunter zu oeffne oeffnen schliesse schliessen stopp stoppe stoppen dimme "
        "dimm prozent".split()
    )
)


def has_control_cue(text: str) -> bool:
    """Klingt der Text nach einem Schaltbefehl (an, aus, hoch, runter, Prozent, eine Zahl)?"""
    return bool(set(tokenize(text)) & _CONTROL_CUES) or bool(re.search(r"\d\s*%|\d+", text))
