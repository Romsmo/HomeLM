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
