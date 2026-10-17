from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
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


@dataclass
class ToolContext:
    emit: Callable[[ServerEvent], Awaitable[None]]
    stage: StageStore
    # Vom Agenten gesetzt, wenn er abbricht, weil Claude übernehmen soll (siehe agent/router.py).
    escalation: Escalation | None = None


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

    def schemas(self) -> list[ToolSchema]:
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
        ]
