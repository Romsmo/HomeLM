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
    | frozenset("hoch runter herunter rauf zu auf stopp stoppe stoppen prozent".split())
)
# Wortanfänge von Schaltwörtern ("öffne", "schließ", "aufmachen", "entriegel" ...).
_CUE_PREFIXES = (
    "oeffn", "schliess", "runterfahr", "hochfahr", "zumach", "aufmach", "anmach", "ausmach",
    "einschalt", "ausschalt", "anschalt", "abschalt", "dimm", "entriegel", "verriegel",
    "aufschliess", "abschliess",
)  # fmt: skip
# Rückblick, Verneinung oder Frage nach dem Warum: Das ist kein Befehl, auch wenn "Rollo öffnen"
# darin vorkommt ("Ich hab doch nie gesagt, dass du das Rollo öffnen sollst").
_NOT_A_COMMAND = frozenset(
    "nicht nie niemals kein keine nichts warum wieso weshalb gesagt gemeint meinte meinst "
    "versehentlich faelschlich".split()
)


def has_control_cue(text: str) -> bool:
    """Klingt der Text nach einem Schaltbefehl (an, aus, auf, zu, hoch, runter, Prozent, Zahl)?"""
    tokens = tokenize(text)
    if set(tokens) & _CONTROL_CUES or re.search(r"\d", text):
        return True
    return any(t.startswith(_CUE_PREFIXES) for t in tokens)


def negated_or_reported(text: str) -> bool:
    """Verneint oder berichtet der Text nur ("Ich habe nie gesagt, dass ...")?"""
    return bool(set(tokenize(text)) & _NOT_A_COMMAND)


_OPEN_PREFIXES = ("oeffn", "hochfahr", "aufmach", "rauf", "hoch")
_CLOSE_PREFIXES = ("schliess", "runterfahr", "zumach", "runter", "herunter")


def shutter_conflict(user_text: str, command: str) -> str | None:
    """Der Nutzer sagt "schließen", das Modell sendet "öffnen" (0 Prozent, up) oder umgekehrt?
    Dann das Wort des Nutzers, sonst None. Mit Zahl im Text ("auf 30 Prozent") keine Prüfung."""
    if re.search(r"\d", user_text):
        return None
    tokens = tokenize(user_text)
    wants_open = (
        "auf" in tokens or "offen" in tokens or any(t.startswith(_OPEN_PREFIXES) for t in tokens)
    )
    wants_close = "zu" in tokens or any(t.startswith(_CLOSE_PREFIXES) for t in tokens)
    if wants_open == wants_close:
        return None
    cmd = command.strip().lower().replace(",", ".")
    try:
        number: float | None = float(cmd)
    except ValueError:
        number = None
    opening = cmd in {"up", "open", "auf"} or number == 0
    closing = cmd in {"down", "close", "zu"} or (number is not None and number >= 100)
    if wants_close and opening:
        return "schließen"
    if wants_open and closing:
        return "öffnen"
    return None
