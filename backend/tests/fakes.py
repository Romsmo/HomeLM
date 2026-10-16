from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

from cat.llm.base import LLMEvent, Message, ToolSchema


class FakeProvider:
    """Spielt vorbereitete Antwortschritte ab und merkt sich, was das Modell gesehen hätte."""

    def __init__(self, *steps: list[LLMEvent] | Exception) -> None:
        self._steps = list(steps)
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSchema]
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(
            {"system": system, "messages": deepcopy(messages), "tool_names": _names(tools)}
        )
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        for event in step:
            yield event


def _names(tools: list[ToolSchema]) -> list[str]:
    return [t["function"]["name"] for t in tools]
