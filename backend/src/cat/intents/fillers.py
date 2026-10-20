"""Füllsätze: Cat sagt etwas Passendes, während es nachdenkt ("Moment, ich schaue kurz nach").

Das lokale Modell braucht für eine Antwort 4 bis 15 Sekunden. Ohne Rückmeldung wirkt Cat in dieser
Zeit tot. Deshalb wird nach kurzer Wartezeit (`CAT_FILLER_DELAY_S`) ein Füllsatz aus einer Liste
gesprochen bzw. angezeigt, passend zur Art der Anfrage (nachsehen, schalten, merken, Weitergabe an
Claude, sonstiges Nachdenken).

Die Auswahl ist bewusst KEINE Anfrage an ein Sprachmodell: Auch eine kurze Modellanfrage kostet auf
dieser CPU 3 bis 5 Sekunden und käme zu spät. Sie läuft in Mikrosekunden, rein aus den Wörtern der
Anfrage (Frage oder Schaltbefehl, kommt ein Gerät vor, geht es an Claude).

Die Liste lernt dazu:
- Sie wächst von selbst: Ist Cat untätig, lässt es das lokale Modell neue Sätze für die Kategorie
  schreiben, die am häufigsten gebraucht wird (`FillerWorkshop`). Jeder neue Satz wird geprüft
  (kurz, ohne Zahlen, ohne Ergebnis-Behauptung, nicht doppelt) und erst dann aufgenommen.
- Gebrauch wird gezählt, der am längsten nicht benutzte Satz kommt zuerst (keine Wiederholung).
- Sätze lassen sich über die Oberfläche löschen; gelöschte Sätze kommen nicht wieder (Sperrliste).
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cat.intents.claims import claims_action
from cat.intents.text import fold, is_question, tokenize

log = logging.getLogger("cat.fillers")

CATEGORIES = ("lookup", "control", "memory", "think", "claude")
# Beschreibung für die Werkstatt: was Cat gerade tut (Grundlage für neue Sätze).
DESCRIPTIONS = {
    "lookup": "gerade nachsieht, wie etwas im Haus steht",
    "control": "gerade einen Schaltbefehl ausführt",
    "memory": "sich etwas merkt",
    "think": "kurz über eine Frage nachdenkt",
    "claude": "eine schwierigere Frage nachschlägt und das etwas länger dauert",
}
BUILTIN: dict[str, tuple[str, ...]] = {
    "lookup": (
        "Moment, ich schaue kurz nach.",
        "Warte kurz, ich schaue schnell nach.",
        "Einen Augenblick, ich sehe mal nach.",
        "Ich schau mal eben nach.",
        "Gleich, ich prüfe das kurz.",
        "Ich schaue kurz bei {topic} nach.",
        "Moment, ich sehe schnell bei {topic} nach.",
    ),
    "control": (
        "Mach ich, einen Moment.",
        "Okay, ich kümmere mich drum.",
        "Gib mir kurz einen Moment, ich mach das.",
        "Alles klar, gleich geht's los.",
    ),
    "memory": (
        "Ich merke mir das kurz.",
        "Okay, ich schreibe es mir auf.",
        "Moment, ich notiere das.",
    ),
    "think": (
        "Lass mich kurz überlegen.",
        "Hm, einen Moment.",
        "Moment, ich denke kurz nach.",
        "Gleich, ich überlege kurz.",
    ),
    "claude": (
        "Das muss ich kurz nachschlagen.",
        "Dazu muss ich kurz nachfragen, einen Moment.",
        "Einen Moment, das dauert etwas länger.",
        "Das schaue ich mir genauer an, bitte kurz warten.",
    ),
}
_MEMORY_WORDS = frozenset("merk merke notiere notier schreib vergiss erinner erinnere".split())
# Ein Füllsatz sagt, dass es gleich weitergeht: Er enthält "ich" oder ein Wort der Wartezeit.
_WAIT_WORDS = frozenset(
    "moment augenblick sekunde gleich kurz warte warten gedulden bitte schnell mal".split()
)
# Mittelwort der Vergangenheit ("nachgedacht", "geschaut"): klingt als Füllsatz schief.
_PARTICIPLE = re.compile(r"^(?:\w+ge\w+|ge\w{3,})t$")
# Neu geschriebene Sätze kommen seltener dran als die geprüften Vorgaben.
GENERATED_WEIGHT = 0.35
MAX_WORDS = 9
MAX_CHARS = 70
PER_CATEGORY_TARGET = 14  # so viele Sätze je Kategorie, dann wächst die Liste nicht weiter
MAX_TOTAL = 200


@dataclass
class Filler:
    text: str
    category: str
    source: str = "builtin"  # builtin | generated
    uses: int = 0
    last_used: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "category": self.category,
            "source": self.source,
            "uses": self.uses,
            "last_used": self.last_used or None,
        }


def valid_phrase(text: str) -> str | None:
    """Gibt den bereinigten Satz zurück, wenn er als Füllsatz taugt, sonst None."""
    clean = " ".join(text.strip().strip("-*•\"„“' ").split())
    if clean[:2].rstrip(".) ").isdigit():  # Aufzählung "1. ..."
        clean = clean.split(" ", 1)[-1] if " " in clean else ""
    clean = clean.strip("\"„“' ")
    words = clean.split()
    if not (2 <= len(words) <= MAX_WORDS) or len(clean) > MAX_CHARS:
        return None
    if not clean.endswith((".", "!", "?")):
        return None
    if any(ch.isdigit() for ch in clean) or any(ch in clean for ch in "*#_`<>[]()/\\@"):
        return None
    if clean.count("{") != clean.count("}") or clean.count("{") > 1:
        return None
    if "{" in clean and "{topic}" not in clean:
        return None
    if claims_action(clean):
        return None  # keine Ergebnisse behaupten ("Das Licht ist aus.")
    if any(w in fold(clean) for w in ("http", "www", "ergebnis", "fertig", "erledigt")):
        return None
    tokens = tokenize(clean)
    if not ({"ich"} | _WAIT_WORDS) & set(tokens):
        return None
    if any(_PARTICIPLE.match(t) for t in tokens):
        return None
    return clean


def user_phrase(text: str) -> str | None:
    """Ein vom Nutzer genannter Füllsatz: weniger streng als bei selbst geschriebenen (der Nutzer
    entscheidet), aber kurz, ohne Markdown und Zahlen."""
    clean = " ".join(text.strip().strip("\"„“'`*- ").split())
    if not clean or not 2 <= len(clean.split()) <= MAX_WORDS or len(clean) > MAX_CHARS:
        return None
    if any(ch.isdigit() for ch in clean) or any(ch in clean for ch in "*#_`<>[]\\@"):
        return None
    if not clean.endswith((".", "!", "?")):
        clean += "."
    return clean


def category_for(text: str, *, device_related: bool, claude: bool) -> str:
    """Welche Art Füllsatz passt zur Anfrage? Rein aus den Wörtern, ohne Modell."""
    from cat.intents.text import has_control_cue

    tokens = tokenize(text)
    if claude:
        return "claude"
    if any(t[:4] in _MEMORY_WORDS or t in _MEMORY_WORDS for t in tokens):
        return "memory"
    if device_related and has_control_cue(text) and not is_question(text):
        return "control"
    if device_related:
        return "lookup"
    return "think"


@dataclass
class FillerBank:
    path: Path
    enabled: bool = True
    _items: dict[str, Filler] = field(default_factory=dict)  # gefalteter Text -> Filler
    _banned: set[str] = field(default_factory=set)
    _last: str = ""

    def __post_init__(self) -> None:
        self._load()
        for category, texts in BUILTIN.items():
            for text in texts:
                key = fold(text)
                if key not in self._banned and key not in self._items:
                    self._items[key] = Filler(text, category)

    # --- Speicher ---

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for row in raw.get("fillers", []):
                filler = Filler(
                    str(row["text"]),
                    str(row["category"]),
                    str(row.get("source", "generated")),
                    int(row.get("uses", 0)),
                    float(row.get("last_used") or 0.0),
                )
                if filler.category in CATEGORIES:
                    self._items[fold(filler.text)] = filler
            self._banned = {str(b) for b in raw.get("banned", [])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("%s ist unlesbar, die Füllsätze beginnen neu", self.path)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            data = {
                "fillers": [f.as_dict() for f in self._items.values()],
                "banned": sorted(self._banned),
            }
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.warning("Füllsätze konnten nicht gespeichert werden")

    # --- Auswahl ---

    def pick(self, category: str, topic: str | None = None) -> str | None:
        """Der am längsten nicht benutzte Satz der Kategorie (mit etwas Zufall unter den
        gleich alten). Sätze mit {topic} nur, wenn es ein Stichwort gibt."""
        if not self.enabled:
            return None
        pool = [
            f
            for f in self._items.values()
            if f.category == category and ("{topic}" not in f.text or topic)
        ]
        if not pool:
            return None
        if len(pool) > 1:
            pool = [f for f in pool if fold(f.text) != self._last] or pool
        # Mit Stichwort bevorzugt die Sätze, die es nennen (passt besser zur Anfrage).
        if topic:
            with_topic = [f for f in pool if "{topic}" in f.text]
            if with_topic and random.random() < 0.6:
                pool = with_topic
        builtin = [f for f in pool if f.source == "builtin"]
        if builtin and len(builtin) < len(pool) and random.random() > GENERATED_WEIGHT:
            pool = builtin  # meistens die geprüften Vorgaben, neue Sätze nur ab und zu
        pool.sort(key=lambda f: f.last_used)
        oldest = [f for f in pool if f.last_used == pool[0].last_used]
        chosen = random.choice(oldest)
        chosen.uses += 1
        chosen.last_used = time.time()
        self._last = fold(chosen.text)
        self._save()
        return chosen.text.replace("{topic}", topic or "")

    # --- Lernen: Liste erweitern, Sätze sperren ---

    def count(self, category: str) -> int:
        return sum(1 for f in self._items.values() if f.category == category)

    def needs_more(self) -> str | None:
        """Die Kategorie, für die neue Sätze am meisten nützen: viel gebraucht, wenige Sätze."""
        if len(self._items) >= MAX_TOTAL:
            return None
        scored: list[tuple[float, str]] = []
        for category in CATEGORIES:
            have = self.count(category)
            if have >= PER_CATEGORY_TARGET:
                continue
            used = sum(f.uses for f in self._items.values() if f.category == category)
            scored.append(((used + 1) / (have + 1), category))
        return max(scored)[1] if scored else None

    def add_generated(self, category: str, texts: list[str]) -> list[str]:
        """Nimmt geprüfte neue Sätze auf. Gibt die tatsächlich aufgenommenen zurück."""
        added: list[str] = []
        for raw in texts:
            clean = valid_phrase(raw)
            if clean is None or category not in CATEGORIES:
                continue
            key = fold(clean)
            if key in self._items or key in self._banned:
                continue
            if self.count(category) >= PER_CATEGORY_TARGET * 2 or len(self._items) >= MAX_TOTAL:
                break
            self._items[key] = Filler(clean, category, "generated")
            added.append(clean)
        if added:
            self._save()
        return added

    def add_user(self, category: str, text: str) -> bool:
        """Satz des Nutzers aufnehmen (auch wenn er vorher gelöscht wurde). False: gibt es schon."""
        if category not in CATEGORIES:
            return False
        key = fold(text)
        if key in self._items:
            return False
        self._banned.discard(key)
        self._items[key] = Filler(text, category, "user")
        self._save()
        return True

    def remove(self, text: str) -> bool:
        """Satz löschen und sperren (kommt nicht wieder, auch nicht aus der Vorgabe)."""
        key = fold(text)
        if key not in self._items:
            return False
        del self._items[key]
        self._banned.add(key)
        self._save()
        return True

    def listing(self) -> list[dict[str, Any]]:
        order = {c: i for i, c in enumerate(CATEGORIES)}
        rows = sorted(self._items.values(), key=lambda f: (order[f.category], f.text))
        return [f.as_dict() for f in rows]


# --- Werkstatt: neue Sätze schreiben lassen, wenn Cat untätig ist ---

Generate = Callable[[str], Awaitable[str]]


def workshop_prompt(category: str, examples: list[str]) -> str:
    shown = "\n".join(f"- {e.replace('{topic}', 'dem Thema')}" for e in examples[:3])
    return (
        f"Ein freundlicher Heimassistent sagt kurze Sätze, während er {DESCRIPTIONS[category]}. "
        f"Beispiele:\n{shown}\n\n"
        "Formuliere diese Sätze auf 5 neue, natürliche Arten um, so wie man sie im Alltag sagt. "
        "Höchstens 8 Wörter je Satz, in der Du-Form, ruhig und freundlich. Der Satz sagt nur, "
        "dass es gleich weitergeht, und nennt kein Ergebnis. Keine Zahlen, keine Emojis, kein "
        "Markdown. Jeder Satz steht in einer eigenen Zeile, sonst nichts."
    )


class FillerWorkshop:
    """Hintergrundaufgabe: erweitert die Liste in ruhigen Zeiten (höchstens `per_day` Läufe)."""

    def __init__(
        self,
        bank: FillerBank,
        generate: Generate,
        idle: Callable[[], bool],
        per_day: int = 4,
        interval_s: float = 600.0,
    ) -> None:
        self._bank = bank
        self._generate = generate
        self._idle = idle
        self._per_day = per_day
        self._interval = interval_s
        self._runs: list[float] = []

    async def run_once(self) -> list[str]:
        """Ein Durchlauf, falls erlaubt. Gibt die neu aufgenommenen Sätze zurück."""
        now = time.time()
        self._runs = [t for t in self._runs if now - t < 86400]
        if len(self._runs) >= self._per_day or not self._idle():
            return []
        category = self._bank.needs_more()
        if category is None:
            return []
        self._runs.append(now)
        examples = [f.text for f in self._bank._items.values() if f.category == category]
        try:
            text = await self._generate(workshop_prompt(category, examples))
        except Exception:
            log.info("Füllsätze: Das Modell war nicht erreichbar, später wieder")
            return []
        added = self._bank.add_generated(category, text.splitlines())
        if added:
            log.info("Füllsätze (%s) dazugelernt: %s", category, " | ".join(added))
        return added

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self.run_once()
