from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from cat.llm.base import ToolSchema
from cat.stage.store import StageStore
from cat.ws.protocol import ServerEvent

Risk = Literal["low", "medium", "high"]


class ToolError(Exception):
    """Erwarteter Fehler eines Werkzeugs; der Text geht an das Modell zurück."""


@dataclass(frozen=True)
class Escalation:
    """Das lokale Modell kommt nicht weiter und reicht die Frage an Claude weiter."""

    reason: str  # "model" (ask_claude), "limit" (zu viele Schritte), "empty", "failed"
    question: str = ""


@dataclass(frozen=True)
class ToolTrace:
    """Ein ausgeführter Werkzeugaufruf eines Zuges (für Sicherung und Lernen)."""

    tool: str
    args: dict[str, Any]
    ok: bool
    result: str


@dataclass
class ToolContext:
    emit: Callable[[ServerEvent], Awaitable[None]]
    stage: StageStore
    # Vom Agenten gesetzt, wenn er abbricht, weil Claude übernehmen soll (siehe agent/router.py).
    escalation: Escalation | None = None
    # Fertige Antworttexte, die Werkzeuge liefern (z. B. nach set_state): Der Agent gibt sie
    # direkt aus und spart den zweiten Modellaufruf (auf der CPU 5 bis 15 Sekunden).
    final_replies: list[str] = field(default_factory=list)
    # Der Nutzer redet (vermutlich) über Geräte: Antworten ohne Gerätewerkzeug sind unbelegt.
    device_related: bool = False
    # Was der Nutzer in dieser Runde gesagt hat (für Prüfungen der Werkzeuge).
    user_text: str = ""
    # Ein Schaltbefehl wurde abgewiesen, weil der Text keiner war: Der Agent fragt nach.
    blocked: bool = False
    # Fester Antworttext statt eines weiteren Modellschritts (z. B. unbekannter Begriff).
    clarify: str = ""
    # Alle Werkzeugaufrufe dieses Zuges in der Reihenfolge der Ausführung.
    trace: list[ToolTrace] = field(default_factory=list)


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # JSON-Schema der Parameter (Objekt).
    parameters: dict[str, Any]
    handler: Handler
    risk: Risk = "low"


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Werkzeug '{tool.name}' ist schon registriert")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def only(self, names: Iterable[str]) -> "ToolRegistry":
        """Neue Registry mit nur diesen Werkzeugen (die lokale KI bekommt eine kleine Auswahl)."""
        wanted = set(names)
        return ToolRegistry({n: t for n, t in self._tools.items() if n in wanted})

    def compact(self, briefs: dict[str, str]) -> "ToolRegistry":
        """Kurzfassung für kleine Modelle: knappe Beschreibung, keine Parameter-Erklärtexte."""
        return ToolRegistry(
            {
                name: replace(
                    tool,
                    description=briefs.get(name, tool.description.split(". ")[0]),
                    parameters=_strip_descriptions(tool.parameters),
                )
                for name, tool in self._tools.items()
            }
        )

    def schemas(self, hide: frozenset[str] = frozenset()) -> list[ToolSchema]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
            if t.name not in hide
        ]


def _strip_descriptions(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_descriptions(v) for k, v in schema.items() if k != "description"}
    if isinstance(schema, list):
        return [_strip_descriptions(v) for v in schema]
    return schema
