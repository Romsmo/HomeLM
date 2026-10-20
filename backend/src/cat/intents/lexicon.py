"""Wortschatz: Begriffe, die der Nutzer Cat beibringt ("Mit Dach-Rollo meine ich Rollo Roman und
Rollo Marius").

Ein Begriff verweist auf ein oder mehrere Geräte. Danach versteht Cat "Mach alle Dachrollos zu"
als Befehl an genau diese Geräte. Die Auflösung passiert im Code (DeviceService.resolve_many),
nicht im Prompt: Es kostet das lokale Modell keine Token, und es klappt auch für Wörter, die es nie
gesehen hat. Gespeichert in `data/lexicon.json`, einzeln löschbar im Widget "Gelernt".
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cat.intents.text import fold, tokenize

log = logging.getLogger("cat.lexicon")

MAX_TERMS = 200
MAX_TARGETS = 12


def normalize(term: str) -> str:
    """Schlüssel eines Begriffs: ohne Umlaute, Bindestriche und Leerzeichen, Mehrzahl gleich
    ("Dach-Rollos", "dachrollo", "Dach Rollo" sind derselbe Begriff)."""
    key = "".join(ch for ch in fold(term) if ch.isalnum())
    for suffix in ("en", "n", "s", "e"):
        if len(key) > 5 and key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key.rstrip("aeiou") if len(key) > 5 else key  # "dachrollo" = "dachrollen"


@dataclass
class Term:
    term: str  # so, wie der Nutzer ihn zuerst gesagt hat
    ids: list[str]
    created: float = field(default_factory=time.time)
    uses: int = 0

    @property
    def key(self) -> str:
        return normalize(self.term)

    def as_dict(self) -> dict[str, Any]:
        return {"term": self.term, "ids": self.ids, "created": self.created, "uses": self.uses}


class Lexicon:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._terms: dict[str, Term] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for row in raw.get("terms", []):
                term = Term(
                    str(row["term"]),
                    [str(i) for i in row["ids"]][:MAX_TARGETS],
                    float(row.get("created", time.time())),
                    int(row.get("uses", 0)),
                )
                self._terms[term.key] = term
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("%s ist unlesbar, der Wortschatz beginnt neu", self._path)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            data = {"terms": [t.as_dict() for t in self._terms.values()]}
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Wortschatz konnte nicht gespeichert werden")

    def add(self, term: str, ids: list[str]) -> Term:
        """Begriff anlegen oder ersetzen (eine neue Erklärung gilt)."""
        key = normalize(term)
        if not key or not ids:
            raise ValueError("Begriff oder Geräte fehlen.")
        if key not in self._terms and len(self._terms) >= MAX_TERMS:
            raise ValueError("Der Wortschatz ist voll.")
        entry = Term(term.strip()[:60], list(dict.fromkeys(ids))[:MAX_TARGETS])
        self._terms[key] = entry
        self._save()
        return entry

    def lookup(self, text: str) -> Term | None:
        """Der Begriff, den der ganze Text benennt (z. B. das Gerät-Argument des Modells)."""
        words = [w for w in tokenize(text) if w not in _ARTICLES]
        found = self._terms.get(normalize("".join(words)))
        if found is not None:
            found.uses += 1
        return found

    def mentions(self, text: str) -> bool:
        """Kommt irgendwo im Text ein bekannter Begriff vor (auch als Wortpaar)?"""
        words = tokenize(text)
        grams = [*words, *(a + b for a, b in zip(words, words[1:], strict=False))]
        return any(normalize(g) in self._terms for g in grams if len(g) >= 4)

    def remove(self, key: str) -> bool:
        if self._terms.pop(normalize(key), None) is None:
            return False
        self._save()
        return True

    def forget_device(self, device_id: str) -> None:
        for term in self._terms.values():
            if device_id in term.ids:
                term.ids.remove(device_id)
        self._terms = {k: t for k, t in self._terms.items() if t.ids}
        self._save()

    def listing(self) -> list[dict[str, Any]]:
        return [t.as_dict() for t in sorted(self._terms.values(), key=lambda t: t.term.lower())]


_ARTICLES = frozenset("der die das den dem des alle alles meine meinen mein ein eine".split())
