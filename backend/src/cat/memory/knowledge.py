"""Wissens-Cache: Antworten von Claude werden Notizen, damit dieselbe Frage nicht erneut kostet.

Claude beantwortet, was das kleine lokale Modell nicht kann (Wissen, Erklärungen). Jede dieser
Antworten auf eine allgemeine, zeitlose Frage wird als Notiz im Thema `wissen` abgelegt (Frage,
Antwort, Datum). Kommt dieselbe Frage wieder, antwortet Cat daraus sofort (ohne Claude, ohne
Abo-Kontingent, in Millisekunden). Ähnliche Fragen finden die Notiz außerdem über die normale
Gedächtnissuche, und das lokale Modell kann sie als Hintergrund nutzen.

Nicht gespeichert wird, was sich ändert oder persönlich ist: Wetter, Uhrzeit, Nachrichten, Preise,
alles mit "heute", "jetzt", "aktuell", Fragen über den Nutzer selbst und alles über Geräte.
Notizen älter als `MAX_AGE_DAYS` werden nicht mehr als fertige Antwort benutzt. Wer ausdrücklich
Claude verlangt ("frag Claude ..."), bekommt immer eine frische Antwort.
"""

import time
from dataclasses import dataclass

from cat.intents.text import tokenize
from cat.memory.notes import Note

TOPIC = "wissen"
MAX_AGE_DAYS = 180
MIN_QUESTION_CHARS = 12
MAX_ANSWER_CHARS = 1500
MIN_ANSWER_CHARS = 20
MIN_COVERAGE = 0.75  # so viele Wortanfänge der Frage müssen im Titel der Notiz stehen

_CHANGING = frozenset(
    """
    heute morgen gestern jetzt gerade wetter uhr uhrzeit datum nachrichten news preis preise kurs
    kurse aktie aktien temperatur spielstand ergebnis ergebnisse tabelle wahl dauert
    """.split()
)
_PERSONAL = frozenset("ich mich mir mein meine meinen meinem meiner wir uns unser unsere".split())
_STOP = frozenset(
    "der die das den dem des ein eine einen und oder ist sind war wie was wer wo wann warum wieso "
    "welche welcher welches mit von zu zum zur im in am an auf aus bei nach für fuer "
    "frag frage fragen mal claude bitte kannst koenntest du mir sag sage erklaer erklaere "
    "erklaeren".split()
)


def stems(text: str) -> set[str]:
    return {t[:5] for t in tokenize(text) if len(t) >= 3 and t not in _STOP}


def cacheable(question: str, answer: str, has_pages: bool = False) -> bool:
    """Ist das eine allgemeine, zeitlose Frage mit brauchbarer Antwort?"""
    tokens = set(tokenize(question))
    if has_pages or len(question.strip()) < MIN_QUESTION_CHARS:
        return False
    if not MIN_ANSWER_CHARS <= len(answer.strip()) <= MAX_ANSWER_CHARS:
        return False
    if tokens & _CHANGING or tokens & _PERSONAL:
        return False
    return not any(t.startswith("aktuell") for t in tokens)


@dataclass(frozen=True)
class Cached:
    answer: str
    date: str


def title_of(question: str) -> str:
    return " ".join(question.strip().rstrip("?!. ").split())[:80]


def age_days(date: str) -> float | None:
    try:
        return (time.time() - time.mktime(time.strptime(date, "%Y-%m-%d"))) / 86400
    except ValueError:
        return None


def matches(question: str, note: Note) -> Cached | None:
    """Beantwortet diese Notiz die Frage (fast gleiche Wörter, nicht zu alt)?"""
    wanted = stems(question)
    have = stems(note.title)
    if not wanted or not have:
        return None
    overlap = len(wanted & have) / max(len(wanted), len(have))
    age = age_days(note.date)
    if overlap < MIN_COVERAGE or (age is not None and age > MAX_AGE_DAYS):
        return None
    body = note.body.split("Antwort:", 1)[-1].strip() if "Antwort:" in note.body else note.body
    return Cached(body.strip(), note.date)
