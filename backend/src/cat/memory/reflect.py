"""Selbst Lernen aus Gesprächen: Cat merkt sich dauerhafte Fakten, ohne dass "merk dir" nötig ist.

Sagt der Nutzer etwas wie "Ich trinke morgens Kaffee mit Hafermilch" oder "Meine Tochter heißt
Lena", soll Cat das später wissen. Der Ablauf ist dreistufig und schont die CPU:

1. Ein billiger Vorfilter (`looks_personal`, nur Wörter) merkt sich, welche Äußerungen überhaupt
   nach einem persönlichen Fakt klingen. Befehle an Geräte und Fragen zählen nicht.
2. Ist Cat untätig (kein Gespräch seit `reflect_idle_s`), fragt es das lokale Modell EINMAL für
   mehrere gesammelte Äußerungen: "Welche dauerhaften Fakten stehen darin?" (JSON).
3. Jeder Fakt wird geprüft (dritte Person, kurz, keine Geheimnisse, nichts Tagesaktuelles) und als
   Notiz im Gedächtnis abgelegt (Tag `auto`). Cat sagt im Chat, was es sich gemerkt hat, und
   "vergiss ..." löscht es wieder. Die Notizen sind normale Markdown-Dateien in `data/memory`.
"""

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cat.intents.text import has_control_cue, is_question, tokenize
from cat.memory.notes import NoteError

log = logging.getLogger("cat.memory")

_FIRST_PERSON = frozenset(
    "ich mich mir mein meine meinen meinem meiner wir uns unser unsere unseren".split()
)
_FACT_WORDS = frozenset(
    """
    mag moegen liebe lieben hasse hassen esse essen trinke trinken bin heisse wohne wohnen arbeite
    arbeiten studiere habe hab brauche moechte will allergisch vegetarisch vegan geburtstag geboren
    immer normalerweise meistens jeden jede morgens abends nachts lieblings lieblingsessen favorit
    kinder kind tochter sohn frau mann freundin freund hund katze bruder schwester mutter vater
    heisst heissen beruf hobby spiele spielen fahre schlafe aufstehe stehe
    """.split()
)
TOPICS = ("vorlieben", "haushalt", "personen", "gewohnheiten")
MAX_QUEUE = 20
BATCH = 5


def looks_personal(text: str, device_related: bool = False) -> bool:
    """Klingt die Äußerung nach einem dauerhaften persönlichen Fakt (billiger Vorfilter)?"""
    if device_related or is_question(text) or (has_control_cue(text) and len(text) < 40):
        return False
    tokens = set(tokenize(text))
    return len(text) >= 15 and bool(tokens & _FIRST_PERSON) and bool(tokens & _FACT_WORDS)


@dataclass(frozen=True)
class Fact:
    title: str
    text: str
    topic: str


def build_prompt(statements: list[str]) -> str:
    lines = "\n".join(f"- {s}" for s in statements)
    return (
        "Ein Nutzer hat zu seinem Heimassistenten gesagt:\n"
        f"{lines}\n\n"
        "Welche DAUERHAFTEN persönlichen Fakten oder Vorlieben stehen darin (Name, Familie, "
        "Gewohnheiten, Vorlieben, Haushalt)? Keine Tagesereignisse, keine Wünsche für heute, keine "
        "Passwörter. Antworte NUR mit einer JSON-Liste, jedes Element mit "
        '"title" (1 bis 3 Wörter), "text" (ein Satz in der dritten Person, beginnend mit '
        '"Der Nutzer") und "topic" (eines von: vorlieben, haushalt, personen, gewohnheiten). '
        "Steht nichts Dauerhaftes darin, antworte mit []."
    )


def parse_facts(output: str) -> list[Fact]:
    """Liest die JSON-Liste des Modells tolerant und prüft jeden Fakt."""
    start, end = output.find("["), output.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(output[start : end + 1])
    except ValueError:
        return []
    facts: list[Fact] = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        title, text, topic = row.get("title"), row.get("text"), row.get("topic")
        if not isinstance(title, str) or not isinstance(text, str):
            continue
        title, text = " ".join(title.split())[:40], " ".join(text.split())
        if not title or not 12 <= len(text) <= 300:
            continue
        if set(tokenize(text)) & _FIRST_PERSON:  # soll dritte Person sein
            continue
        facts.append(Fact(title, text, topic if topic in TOPICS else "vorlieben"))
    return facts[:5]


Generate = Callable[[str], Awaitable[str]]
Save = Callable[[Fact, str | None], Awaitable[bool]]


class Reflector:
    def __init__(self, idle_s: float = 60.0) -> None:
        self._queue: deque[tuple[str, str | None]] = deque(maxlen=MAX_QUEUE)
        self._idle_s = idle_s

    @property
    def pending(self) -> int:
        return len(self._queue)

    def observe(self, text: str, speaker: str | None = None, device_related: bool = False) -> bool:
        if looks_personal(text, device_related):
            self._queue.append((text.strip(), speaker))
            return True
        return False

    async def run_once(
        self, generate: Generate, save: Save, last_activity: float, busy: bool
    ) -> list[Fact]:
        """Ein Durchlauf, wenn Cat untätig ist. Gibt die gespeicherten Fakten zurück."""
        if not self._queue or busy or time.monotonic() - last_activity < self._idle_s:
            return []
        batch = [self._queue.popleft() for _ in range(min(BATCH, len(self._queue)))]
        # Eine Anfrage je Sprecher, damit Fakten der richtigen Person zugeordnet werden.
        by_speaker: dict[str | None, list[str]] = {}
        for text, speaker in batch:
            by_speaker.setdefault(speaker, []).append(text)
        saved: list[Fact] = []
        for speaker, statements in by_speaker.items():
            try:
                output = await generate(build_prompt(statements))
            except Exception:
                log.info("Gedächtnis: Das Modell war nicht erreichbar, später wieder")
                for s in statements:
                    self._queue.append((s, speaker))
                return saved
            for fact in parse_facts(output):
                try:
                    if await save(fact, speaker):
                        saved.append(fact)
                except NoteError:
                    continue
        return saved

    async def run(
        self,
        generate: Generate,
        save: Save,
        last_activity: Callable[[], float],
        busy: Callable[[], bool],
        interval_s: float = 120.0,
    ) -> None:
        while True:
            await asyncio.sleep(interval_s)
            await self.run_once(generate, save, last_activity(), busy())
