"""Personen, die Cat kennt, und ihre Stimm-Fingerabdrücke (data/people.json, nur für den Eigentümer
lesbar). Gespeichert wird nur, was die Person erlaubt hat; "vergiss mich" löscht alles."""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz import fuzz

from cat.intents.text import fold
from cat.voice.speaker import cosine

log = logging.getLogger("cat.people")

MAX_EMBEDDINGS = 8
MAX_PEOPLE = 30


@dataclass
class Person:
    id: str
    name: str
    created: float = field(default_factory=time.time)
    last_seen: float = 0.0
    consent_voice: bool = False
    embeddings: list[list[float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created": self.created,
            "last_seen": self.last_seen,
            "consent_voice": self.consent_voice,
            "embeddings": self.embeddings,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Person":
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            created=float(raw.get("created", time.time())),
            last_seen=float(raw.get("last_seen", 0.0)),
            consent_voice=bool(raw.get("consent_voice", False)),
            embeddings=[[float(x) for x in e] for e in raw.get("embeddings", [])],
        )

    def public(self) -> dict[str, Any]:
        """Ohne Fingerabdrücke (für die Oberfläche)."""
        return {
            "id": self.id,
            "name": self.name,
            "created": self.created,
            "last_seen": self.last_seen or None,
            "voice": self.consent_voice and bool(self.embeddings),
            "samples": len(self.embeddings),
        }

    def centroid(self) -> list[float] | None:
        if not self.embeddings:
            return None
        mean = np.mean(np.asarray(self.embeddings, dtype=np.float32), axis=0)
        norm = float(np.linalg.norm(mean))
        return [float(x) for x in mean / norm] if norm else None


@dataclass(frozen=True)
class Match:
    person: Person | None
    score: float  # Cosinus zum besten Treffer (0, wenn niemand eine Stimme hinterlegt hat)
    runner_up: float  # zum zweitbesten (für den Abstand)


class PeopleStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._people: dict[str, Person] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._people = {p["id"]: Person.from_dict(p) for p in raw.get("people", [])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("%s ist unlesbar, Cat kennt niemanden", self._path)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            data = {"people": [p.as_dict() for p in self._people.values()]}
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.chmod(tmp, 0o600)  # biometrische Daten: nur der Eigentümer
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Personen konnten nicht gespeichert werden")

    # --- Personen ---

    def all(self) -> list[Person]:
        return sorted(self._people.values(), key=lambda p: p.name.lower())

    def get(self, person_id: str) -> Person | None:
        return self._people.get(person_id)

    def find_by_name(self, name: str) -> Person | None:
        """Gleicher Name (Groß-/Kleinschreibung, Umlaute egal, kleine Tippfehler erlaubt)."""
        key = fold(name)
        best: tuple[float, Person] | None = None
        for person in self._people.values():
            score = fuzz.ratio(key, fold(person.name))
            if best is None or score > best[0]:
                best = (score, person)
        return best[1] if best and best[0] >= 90 else None

    def add(self, name: str) -> Person:
        if len(self._people) >= MAX_PEOPLE:
            raise ValueError("Zu viele Personen.")
        person = Person(uuid.uuid4().hex[:12], name.strip()[:40])
        self._people[person.id] = person
        self.save()
        return person

    def remove(self, person_id: str) -> bool:
        if self._people.pop(person_id, None) is None:
            return False
        self.save()
        return True

    def forget_voice(self, person_id: str) -> bool:
        person = self._people.get(person_id)
        if person is None:
            return False
        person.embeddings.clear()
        person.consent_voice = False
        self.save()
        return True

    def touch(self, person: Person) -> None:
        person.last_seen = time.time()
        self.save()

    def add_embedding(self, person: Person, embedding: list[float]) -> None:
        """Nur mit Zustimmung (`consent_voice`). Die ältesten werden ersetzt."""
        if not person.consent_voice:
            return
        person.embeddings.append(embedding)
        del person.embeddings[:-MAX_EMBEDDINGS]
        self.save()

    # --- Stimme erkennen ---

    def match(self, embedding: list[float]) -> Match:
        scored: list[tuple[float, Person]] = []
        for person in self._people.values():
            center = person.centroid()
            if center is not None and person.consent_voice:
                scored.append((cosine(embedding, center), person))
        scored.sort(key=lambda s: -s[0])
        if not scored:
            return Match(None, 0.0, 0.0)
        return Match(scored[0][1], scored[0][0], scored[1][0] if len(scored) > 1 else 0.0)
