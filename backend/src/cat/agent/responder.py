import logging
from collections.abc import AsyncIterator

from cat.agent.loop import Agent, to_llm_messages
from cat.agent.prompt import build_system_prompt
from cat.agent.tools import ToolContext, ToolRegistry
from cat.llm.base import LLMError, LLMProvider
from cat.llm.litellm_provider import LiteLLMProvider
from cat.stage.tools import register_stage_tools
from cat.state import AppState
from cat.ws.protocol import ChatMessage

log = logging.getLogger("cat.agent")


class AgentResponder:
    """Verbindet Chatverlauf, Agent-Schleife und Werkzeuge mit dem Dialog."""

    def __init__(self, state: AppState, agent: Agent) -> None:
        self._state = state
        self._agent = agent

    async def reply(self, history: list[ChatMessage]) -> AsyncIterator[str]:
        messages = to_llm_messages([(m.role, m.text) for m in history])
        ctx = ToolContext(emit=self._state.emit, stage=self._state.stage)
        try:
            async for delta in self._agent.run(messages, ctx):
                yield delta
        except LLMError as exc:
            # Verständliche Meldung statt Stacktrace; sie erscheint als Assistentennachricht.
            yield f"Das hat leider nicht geklappt: {exc}"


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_stage_tools(registry)
    return registry


def build_responder(state: AppState, provider: LLMProvider | None = None) -> AgentResponder:
    settings = state.settings
    provider = provider or LiteLLMProvider(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.llm_max_tokens,
    )
    agent = Agent(
        provider=provider,
        registry=build_registry(),
        system_prompt=build_system_prompt,
        max_steps=settings.agent_max_steps,
    )
    return AgentResponder(state, agent)
