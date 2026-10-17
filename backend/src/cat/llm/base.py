"""Eigene Schnittstelle zum Sprachmodell. Der Rest von Cat kennt nur diese Typen."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

# Nachrichten im OpenAI-Format (role/content, tool_calls, tool_call_id).
Message = dict[str, Any]
# Werkzeugbeschreibungen im OpenAI-Format ({"type": "function", "function": {...}}).
ToolSchema = dict[str, Any]


class LLMError(Exception):
    """Fehler mit einer Meldung, die dem Nutzer gezeigt werden darf (ohne Geheimnisse).

    `unavailable` heißt: Der Anbieter ist nicht erreichbar oder überlastet (Internet weg,
    Ausfall, Limit). Nur dann darf auf ein Offline-Modell umgeschaltet werden. Falsche
    Schlüssel oder Modellnamen (`unavailable=False`) müssen den Nutzer erreichen.
    """

    def __init__(self, message: str, unavailable: bool = False) -> None:
        super().__init__(message)
        self.unavailable = unavailable


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # None, wenn das Modell kein gültiges JSON geliefert hat.
    arguments: dict[str, Any] | None
    raw_arguments: str = ""


LLMEvent = TextDelta | ToolCall


class LLMProvider(Protocol):
    def stream(
        self, system: str, messages: list[Message], tools: list[ToolSchema]
    ) -> AsyncIterator[LLMEvent]:
        """Streamt Textteile; Werkzeugaufrufe kommen vollständig am Ende des Antwortschritts."""
        ...
