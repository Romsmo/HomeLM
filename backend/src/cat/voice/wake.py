"""Aktivierungsphrasen für das Browser-Mikrofon ("Hey Cat, mach das Licht an").

Das Browser-Mikrofon ist immer an. Damit Cat nicht auf jedes Gespräch im Raum antwortet, gilt
eine Äußerung nur, wenn sie mit einer Aktivierungsphrase beginnt oder endet, oder wenn Cat gerade
selbst gesprochen hat (Gesprächsfenster: die Antwort auf eine Rückfrage braucht keine Phrase).
Satelliten haben ihr eigenes Wake-Word (openWakeWord) und brauchen das hier nicht.

Die Phrase wird im erkannten TEXT gesucht, nicht im Ton: Whisper schreibt "Cat" oft anders
("Kat", "Kät", "Katt"), darum werden gängige Schreibweisen akzeptiert. Es läuft nichts Zusätzliches
auf der CPU, und nichts von dem, was ohne Phrase gesprochen wird, geht an ein Sprachmodell,
wird gespeichert oder im Verlauf angezeigt.
"""

import re
import time
from dataclasses import dataclass

from cat.intents.text import fold

# Schreibweisen, die Whisper für die Wörter der Phrasen liefert (gefaltet, ohne Umlaute).
_VARIANTS: dict[str, frozenset[str]] = {
    "cat": frozenset(
        {
            "cat",
            "kat",
            "katt",
            "kaet",
            "cet",
            "ket",
            "kett",
            "caet",
            "cad",
            "kad",
            "card",
            "kart",
            "kard",
        }
    ),
    "hey": frozenset({"hey", "hei", "hej", "hay", "ey", "hai", "he"}),
    "hallo": frozenset({"hallo", "hello", "halo", "hallooo", "hall"}),
    "okay": frozenset({"okay", "ok", "okey", "okei", "oke", "okaay", "kay"}),
}
# Füllwörter, die vor der Phrase stehen dürfen ("ähm, hey Cat, ...").
_LEAD = frozenset({"ah", "aeh", "aehm", "ahm", "hm", "hmm", "also", "na"})
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß0-9]+")
_STRIP = " \t\n,.;:!?-–—"
DEFAULT_PHRASES = ("hey cat", "hallo cat", "okay cat")
ACKS = ("Ja?", "Ich höre.", "Ja, bitte?")


@dataclass(frozen=True)
class WakeResult:
    woke: bool
    rest: str = ""  # die Äußerung ohne Phrase (leer: nur die Phrase wurde gesagt)


def _same(word: str, token: str) -> bool:
    """Passt das erkannte Wort zum Wort der Phrase (Schreibweisen von Whisper inklusive)?"""
    token = fold(token)
    return token == word or token in _VARIANTS.get(word, ())


class WakeDetector:
    def __init__(
        self, phrases: tuple[str, ...] | list[str] = DEFAULT_PHRASES, followup_s: float = 20.0
    ) -> None:
        self.phrases = [fold(p).split() for p in phrases if p.strip()]
        self.display = [p.strip() for p in phrases if p.strip()]
        self.followup_s = followup_s
        self._ack = 0

    def match(self, text: str) -> WakeResult:
        """Beginnt (oder endet) die Äußerung mit einer Aktivierungsphrase?"""
        tokens = [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(text)]
        for start in range(min(3, len(tokens))):
            if start and not all(fold(t[0]) in _LEAD for t in tokens[:start]):
                break
            for phrase in self.phrases:
                end = start + len(phrase)
                if end <= len(tokens) and all(
                    _same(w, t[0]) for w, t in zip(phrase, tokens[start:end], strict=True)
                ):
                    return WakeResult(True, text[tokens[end - 1][2] :].lstrip(_STRIP).strip())
        for phrase in self.phrases:
            n = len(phrase)
            if len(tokens) > n and all(
                _same(w, t[0]) for w, t in zip(phrase, tokens[-n:], strict=True)
            ):
                return WakeResult(True, text[: tokens[-n][1]].rstrip(_STRIP).strip())
        return WakeResult(False)

    def ack(self) -> str:
        """Kurze Rückmeldung, wenn nur die Phrase gesagt wurde (abwechselnd)."""
        self._ack = (self._ack + 1) % len(ACKS)
        return ACKS[self._ack]


class WakeWindow:
    """Gesprächsfenster: Solange es offen ist, braucht die nächste Äußerung keine Phrase."""

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._until = 0.0

    def open(self) -> None:
        self._until = time.monotonic() + self._seconds

    def close(self) -> None:
        self._until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self._until
