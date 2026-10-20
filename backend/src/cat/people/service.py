"""Personen kennenlernen und erkennen: an der Stimme, sonst durch Fragen (Sprache und Chat).

Ablauf ohne Sprachmodell (feste, kurze Sätze, damit es schnell geht und nichts Falsches entsteht):

1. Bei jeder Sprachäußerung (nach der Aktivierungsphrase) wird ein Stimm-Fingerabdruck berechnet
   und mit den gespeicherten verglichen: sicher erkannt, unsicher ("Bist du Roman?") oder unbekannt.
2. Antwortet Cat auf eine Anfrage, hängt es bei Bedarf EINE Frage an: unbekannte Stimme oder
   unbekannte Person im Chat: "Wie heißt du?". Die Anfrage selbst wird nie aufgehalten.
3. Nennt jemand seinen Namen, wird die Person angelegt. Ihre Stimme merkt sich Cat NUR nach einem
   ausdrücklichen Ja. "Vergiss meine Stimme" und "Vergiss mich" löschen sofort.
4. Wer spricht, steht danach im Kontext des Modells ("Du sprichst gerade mit Roman"), und die
   Notizen dieser Person werden bevorzugt aus dem Gedächtnis geholt.

Die Erkennung dient nur der Personalisierung. Sie schaltet nichts frei: Bestätigungen für Türen
und Schlösser gelten unabhängig davon für jeden gleich.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from cat.intents.text import fold
from cat.people.parse import (
    DECLINE,
    asks_who_am_i,
    parse_name,
    parse_yes_no,
    strip_negation,
    wants_person_forgotten,
    wants_voice_forgotten,
)
from cat.people.store import PeopleStore, Person
from cat.voice.speaker import cosine

log = logging.getLogger("cat.people")

ASK_GAP_S = 20 * 60  # frühestens nach 20 Minuten wieder fragen
GREET_GAP_S = 6 * 3600  # Begrüßung mit Namen höchstens alle 6 Stunden
RECENT_VOICE_S = 10 * 60  # der Chat übernimmt, wer gerade per Stimme erkannt wurde
TOUCH_GAP_S = 60.0


class Encoder(Protocol):
    def embed(self, pcm: bytes) -> list[float] | None: ...


@dataclass
class Pending:
    kind: str  # "name" | "consent" | "confirm"
    person_id: str | None = None
    embedding: list[float] | None = None


@dataclass
class Channel:
    speaker_id: str | None = None
    source: str = "none"  # voice | intro | chat
    since: float = 0.0
    pending: Pending | None = None
    unknown: list[list[float]] = field(default_factory=list)
    asked_at: float = -1e9
    declined_until: float = 0.0
    tries: int = 0
    greeted: dict[str, float] = field(default_factory=dict)
    learn_person: str | None = None  # frisch angemeldet: die nächsten Äußerungen lernen mit
    learn_left: int = 0
    guess: Pending | None = None  # unsichere Zuordnung der letzten Äußerung


@dataclass(frozen=True)
class Identity:
    status: str  # known | uncertain | unknown | none
    person: Person | None = None
    score: float = 0.0
    embedding: list[float] | None = None


NONE = Identity("none")


class PeopleService:
    def __init__(
        self,
        store: PeopleStore,
        *,
        enabled: bool = True,
        accept: float = 0.60,
        uncertain: float = 0.50,
        margin: float = 0.08,
        ttl_s: float = 6 * 3600,
        ask_voice: bool = True,
        ask_chat: bool = True,
        is_request: Callable[[str], bool] = lambda _: False,
        on_new: Callable[[Person], Awaitable[None]] | None = None,
        on_forget: Callable[[Person], Awaitable[None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.encoder: Encoder | None = None
        self._accept, self._uncertain, self._margin = accept, uncertain, margin
        self._ttl = ttl_s
        self._ask_voice, self._ask_chat = ask_voice, ask_chat
        self._is_request = is_request
        self._on_new, self._on_forget = on_new, on_forget
        self._now = clock
        self._channels: dict[str, Channel] = {}
        self._last_voice: tuple[str, float] | None = None

    def channel(self, key: str) -> Channel:
        return self._channels.setdefault(key, Channel())

    def drop_channel(self, key: str) -> None:
        self._channels.pop(key, None)

    # --- Wer spricht? ---

    def _set(self, ch: Channel, person: Person, source: str) -> None:
        ch.speaker_id, ch.source, ch.since = person.id, source, self._now()

    def speaker_for(self, key: str) -> Person | None:
        if not self.enabled:
            return None
        ch = self.channel(key)
        if ch.speaker_id and (person := self.store.get(ch.speaker_id)):
            if ch.source == "voice" or self._now() - ch.since < self._ttl:
                return person
        if not key.startswith("voice:") and self._last_voice:
            person_id, when = self._last_voice
            if self._now() - when < RECENT_VOICE_S and (person := self.store.get(person_id)):
                return person  # der Chat übernimmt, wer eben per Stimme erkannt wurde
        return None

    async def identify_voice(self, key: str, pcm: bytes) -> Identity:
        """Stimm-Fingerabdruck der Äußerung berechnen und zuordnen."""
        if not self.enabled or self.encoder is None:
            return NONE
        embedding = await asyncio.to_thread(self.encoder.embed, pcm)
        if embedding is None:
            return NONE
        ch = self.channel(key)
        self._learn(ch, embedding)
        match = self.store.match(embedding)
        person = match.person
        clear = person is not None and (
            match.runner_up == 0.0 or match.score - match.runner_up >= self._margin
        )
        log.info(
            "Stimme: bester Treffer %s %.2f (zweiter %.2f), Schwellen %.2f/%.2f",
            person.name if person else "-",
            match.score,
            match.runner_up,
            self._uncertain,
            self._accept,
        )
        if person is not None and match.score >= self._accept and clear:
            self._set(ch, person, "voice")
            self._last_voice = (person.id, self._now())
            if match.score >= self._accept + 0.08:  # sehr sicher: Fingerabdruck auffrischen
                self.store.add_embedding(person, embedding)
            if time.time() - person.last_seen > TOUCH_GAP_S:
                self.store.touch(person)
            return Identity("known", person, match.score, embedding)
        if ch.source == "voice":
            ch.speaker_id = None  # andere oder unklare Stimme: nicht der Vorige
        if person is not None and match.score >= self._uncertain:
            ch.guess = Pending("confirm", person.id, embedding)
            return Identity("uncertain", person, match.score, embedding)
        ch.guess = None
        ch.unknown = [*ch.unknown, embedding][-3:]
        return Identity("unknown", None, match.score, embedding)

    def _learn(self, ch: Channel, embedding: list[float]) -> None:
        """Gerade angemeldet: Die nächsten Äußerungen in dieser Sitzung stammen sehr wahrscheinlich
        von derselben Person und verbessern ihren Fingerabdruck (eine einzige kurze Probe reicht
        nicht, um sie von anderen zu unterscheiden)."""
        if ch.learn_person is None or ch.learn_left <= 0:
            return
        person = self.store.get(ch.learn_person)
        center = person.centroid() if person else None
        if person is None or not person.consent_voice or center is None:
            ch.learn_person, ch.learn_left = None, 0
            return
        if cosine(embedding, center) >= 0.35:  # grobe Plausibilität: klingt nicht völlig anders
            self.store.add_embedding(person, embedding)
        ch.learn_left -= 1

    # --- Fragen und Antworten ---

    def greeting(self, key: str, identity: Identity) -> str | None:
        """ "Hallo Roman!" beim ersten Erkennen nach längerer Pause (nur Sprache)."""
        if identity.status != "known" or identity.person is None:
            return None
        ch = self.channel(key)
        last = ch.greeted.get(identity.person.id)
        if last is not None and self._now() - last < GREET_GAP_S:
            return None
        ch.greeted[identity.person.id] = self._now()
        return f"Hallo {identity.person.name}! "

    def follow_up(self, key: str, identity: Identity) -> str | None:
        """Eine Frage, die an die Antwort angehängt wird (oder None)."""
        if not self.enabled:
            return None
        ch = self.channel(key)
        now = self._now()
        if ch.pending or now - ch.asked_at < ASK_GAP_S or now < ch.declined_until:
            return None
        voice = key.startswith("voice:")
        if identity.status == "uncertain" and identity.person is not None:
            ch.pending = Pending("confirm", identity.person.id, identity.embedding)
            ch.asked_at = now
            return f"Bist du {identity.person.name}?"
        if identity.status == "unknown" and self._ask_voice and self.encoder is not None:
            ch.pending, ch.asked_at, ch.tries = Pending("name"), now, 0
            return "Übrigens, ich kenne deine Stimme noch nicht. Wie heißt du?"
        if self.speaker_for(key) is None and (self._ask_voice if voice else self._ask_chat):
            if voice and self.encoder is not None:
                return None  # die Stimmerkennung läuft: sie entscheidet, ob gefragt wird
            ch.pending, ch.asked_at, ch.tries = Pending("name"), now, 0
            return "Übrigens, mit wem spreche ich eigentlich? Wie heißt du?"
        return None

    async def intercept(self, key: str, text: str) -> str | None:
        """Antwort auf eine offene Frage oder ein Personen-Befehl. None: normale Anfrage."""
        if not self.enabled:
            return None
        ch = self.channel(key)
        if wants_voice_forgotten(text):
            return self._forget_voice(key)
        if wants_person_forgotten(text):
            return await self._forget_person(key)
        pending = ch.pending
        if pending is None:
            name = parse_name(
                text,
                asked=False,
                known=[p.name for p in self.store.all()],
                allow_new_be=self.speaker_for(key) is None,
            )
            if name and name != DECLINE:
                return await self._introduce(ch, key, name)
            return self._who(ch, key) if asks_who_am_i(text) else None
        if pending.kind == "name":
            return await self._answer_name(ch, key, text)
        if pending.kind == "consent":
            return self._answer_consent(ch, text)
        return await self._answer_confirm(ch, key, text)

    async def _answer_name(self, ch: Channel, key: str, text: str) -> str | None:
        name = parse_name(text, asked=True)
        if name not in (None, DECLINE) and not self._is_request(text):
            return await self._introduce(ch, key, str(name))  # auch "Roman": Name und Gerät
        if self._is_request(text):  # der Nutzer hat die Frage übergangen und etwas anderes gefragt
            ch.pending, ch.declined_until = None, self._now() + 3600
            return None
        if name == DECLINE:
            ch.pending, ch.declined_until = None, self._now() + 6 * 3600
            return "Alles klar, ich frage nicht weiter."
        if name is None:
            ch.tries += 1
            if ch.tries >= 2:
                ch.pending, ch.declined_until = None, self._now() + 3600
                return None
            return "Das habe ich nicht verstanden. Wie heißt du?"
        return await self._introduce(ch, key, name)

    async def _introduce(self, ch: Channel, key: str, name: str) -> str:
        person = self.store.find_by_name(name)
        created = person is None
        if person is None:
            try:
                person = self.store.add(name)
            except ValueError:
                ch.pending = None
                return "Ich kenne schon zu viele Leute, ich kann mir niemand Neuen merken."
            if self._on_new:
                await self._on_new(person)
        self._set(ch, person, "intro")
        self.store.touch(person)
        if key.startswith("voice:") and ch.unknown and not person.consent_voice:
            ch.pending = Pending("consent", person.id)
            hello = (
                f"Hallo {person.name}, schön dich kennenzulernen."
                if created
                else f"Hallo {person.name}!"
            )
            return (
                f"{hello} Darf ich mir deine Stimme merken, damit ich dich nächstes Mal erkenne? "
                "Das bleibt nur hier im Haus."
            )
        ch.pending = None
        return (
            f"Freut mich, {person.name}!"
            if created
            else f"Hallo {person.name}, schön dich zu hören."
        )

    def _answer_consent(self, ch: Channel, text: str) -> str | None:
        pending = ch.pending
        assert pending is not None and pending.person_id is not None
        person = self.store.get(pending.person_id)
        answer = parse_yes_no(text)
        if answer is None:
            if self._is_request(text) or ch.tries >= 1:
                ch.pending = None
                return None
            ch.tries += 1
            return "Ja oder nein: Darf ich mir deine Stimme merken?"
        ch.pending, ch.tries = None, 0
        if person is None or not answer:
            ch.unknown.clear()
            return "Okay, ich merke sie mir nicht."
        person.consent_voice = True
        for embedding in ch.unknown:
            self.store.add_embedding(person, embedding)
        ch.unknown.clear()
        self.store.save()
        ch.learn_person, ch.learn_left = person.id, 3
        return (
            "Danke, ich merke mir deine Stimme. Sprich gern noch ein paar Sätze mit mir, dann "
            "erkenne ich dich sicherer. Mit „Vergiss meine Stimme“ löschst du sie jederzeit."
        )

    async def _answer_confirm(self, ch: Channel, key: str, text: str) -> str | None:
        pending = ch.pending
        assert pending is not None and pending.person_id is not None
        person = self.store.get(pending.person_id)
        if person is None:
            ch.pending = None
            return None
        name = parse_name(strip_negation(text), asked=True)
        said_other = name not in (None, DECLINE) and fold(str(name)) != fold(person.name)
        answer = parse_yes_no(text)
        if name not in (None, DECLINE) and not said_other:
            answer = True  # "Ja, Christian." / "Christian."
        if said_other and not self._is_request(text):
            self._reject(person, pending.embedding, ch)
            return await self._introduce(ch, key, str(name))
        if answer is None:
            ch.pending = None  # keine klare Antwort: weiter wie gewohnt
            return None
        if answer:
            ch.pending = None
            self._set(ch, person, "intro")
            if pending.embedding:
                self.store.add_embedding(person, pending.embedding)
            self.store.touch(person)
            return f"Schön, {person.name}."
        self._reject(person, pending.embedding, ch)
        ch.pending = Pending("name")
        ch.tries = 0
        return "Dann sag mir bitte, wie du heißt."

    def _reject(self, person: Person, embedding: list[float] | None, ch: Channel) -> None:
        """ "Nein, das bin ich nicht": Die Stimme gehört NICHT zu `person` (merken, damit es nicht
        wieder passiert) und kann zur richtigen Person werden."""
        if embedding:
            self.store.add_negative(person, embedding)
            ch.unknown = [*ch.unknown, embedding][-3:]
        if ch.speaker_id == person.id:
            ch.speaker_id = None

    def _who(self, ch: Channel, key: str) -> str:
        person = self.speaker_for(key)
        if person is None and ch.guess is not None and ch.guess.person_id:
            guessed = self.store.get(ch.guess.person_id)
            if guessed is not None:
                ch.pending, ch.guess = ch.guess, None
                return f"Ich glaube, du bist {guessed.name}. Stimmt das?"
        if person is None:
            ch.pending, ch.tries = Pending("name"), 0
            return "Das weiß ich noch nicht. Wie heißt du?"
        if ch.source == "voice" or (self._last_voice and self._last_voice[0] == person.id):
            return f"Du bist {person.name}, ich habe dich an der Stimme erkannt."
        suffix = (
            " Meine Stimme-Erkennung kennt dich noch nicht." if not person.consent_voice else ""
        )
        return f"Du hast dich als {person.name} vorgestellt.{suffix}"

    # --- Vergessen ---

    def _forget_voice(self, key: str) -> str:
        person = self.speaker_for(key)
        if person is None:
            return "Ich weiß gerade nicht, wessen Stimme ich vergessen soll."
        self.store.forget_voice(person.id)
        return "Okay, ich habe deine Stimme vergessen."

    async def _forget_person(self, key: str) -> str:
        person = self.speaker_for(key)
        if person is None:
            return "Ich weiß gerade nicht, wen ich vergessen soll."
        self.store.remove(person.id)
        for ch in self._channels.values():
            if ch.speaker_id == person.id:
                ch.speaker_id = None
        if self._last_voice and self._last_voice[0] == person.id:
            self._last_voice = None
        if self._on_forget:
            await self._on_forget(person)
        return (
            f"Okay, {person.name}, ich habe deinen Namen und deine Stimme vergessen "
            "und die Notizen über dich gelöscht."
        )

    # --- Kontext für das Modell ---

    def context_line(self, person: Person | None) -> str:
        if person is None:
            return ""
        return (
            f"Du sprichst gerade mit {person.name}. Sprich {person.name} gelegentlich mit dem "
            "Namen an und beachte die Notizen über diese Person."
        )
