import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

from cat.agent.loop import Agent, to_llm_messages
from cat.agent.prompt import build_local_prompt, build_system_prompt
from cat.agent.router import (
    ASK_CLAUDE,
    SPOKEN_HINT,
    RoutedResponder,
    build_ask_claude_tool,
    room_hint,
)
from cat.agent.tools import Tool, ToolContext, ToolRegistry
from cat.claude.bridge import ClaudeBridge
from cat.claude.budget import ClaudeBudget
from cat.devices.service import DeviceService
from cat.devices.tools import build_device_tools
from cat.files import Inbox, build_file_tools
from cat.llm.base import LLMError, LLMProvider
from cat.llm.fallback import FallbackProvider
from cat.llm.litellm_provider import LiteLLMProvider
from cat.llm.ollama import OllamaProvider
from cat.memory.service import MemoryService, build_memory_tools
from cat.plugins.pending import PendingPlugins, build_pending_tools
from cat.sandbox.client import SandboxClient
from cat.sandbox.tools import build_sandbox_tools
from cat.stage.tools import register_stage_tools
from cat.state import AppState
from cat.ws.protocol import ChatMessage

log = logging.getLogger("cat.agent")


class AgentResponder:
    """Verbindet Chatverlauf, Agent-Schleife und Werkzeuge mit dem Dialog."""

    def __init__(self, state: AppState, agent: Agent) -> None:
        self._state = state
        self._agent = agent

    async def reply(
        self, history: list[ChatMessage], spoken: bool = False, room: str | None = None
    ) -> AsyncIterator[str]:
        messages = to_llm_messages([(m.role, m.text) for m in history])
        ctx = ToolContext(emit=self._state.emit, stage=self._state.stage)
        question = next((m.text for m in reversed(history) if m.role == "user"), "")
        previous = self._state.devices.last_device
        # Relevante Erinnerungen vor der Antwort in den Prompt holen (FTS5, lokal, ohne LLM).
        extra = await asyncio.to_thread(self._state.memory.context_for, question)
        if room:
            extra = f"{room_hint(room)}\n\n{extra}".strip()
        if spoken:
            extra = f"{extra}\n\n{SPOKEN_HINT}".strip()
        try:
            async for delta in self._agent.run(messages, ctx, system_extra=extra):
                yield delta
            await self._state.learn_from(question, ctx.trace, room, previous)
        except LLMError as exc:
            # Verständliche Meldung statt Stacktrace; sie erscheint als Assistentennachricht.
            yield f"Das hat leider nicht geklappt: {exc}"


def build_registry(
    extra_tools: Sequence[Tool] = (),
    devices: DeviceService | None = None,
    memory: MemoryService | None = None,
    sandbox: SandboxClient | None = None,
    pending: PendingPlugins | None = None,
    inbox: Inbox | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_stage_tools(registry)
    if devices is not None:
        for tool in build_device_tools(devices):
            registry.register(tool)
    if memory is not None:
        for tool in build_memory_tools(memory):
            registry.register(tool)
    if sandbox is not None:
        for tool in build_sandbox_tools(sandbox):
            registry.register(tool)
    if pending is not None:
        for tool in build_pending_tools(pending):
            registry.register(tool)
    if inbox is not None:
        for tool in build_file_tools(inbox):
            registry.register(tool)
    for tool in extra_tools:
        registry.register(tool)
    return registry


# Was die kleine lokale KI NICHT bekommt: Sie soll kein HTML schreiben oder Plugins entwerfen,
# das ist Sache von Claude (und spart ca. 400 Prompt-Token, die auf der CPU Sekunden kosten).
LOCAL_EXCLUDED_TOOLS = ("show_html", "propose_plugin")


def build_local_provider(state: AppState) -> OllamaProvider:
    s = state.settings
    return OllamaProvider(
        s.local_model,
        s.ollama_url,
        num_ctx=s.local_num_ctx,
        num_thread=s.local_threads,
        keep_alive=s.local_keep_alive,
        timeout_s=s.local_timeout_s,
        max_tokens=s.local_max_tokens,
    )


def build_claude(state: AppState) -> tuple[ClaudeBridge, ClaudeBudget] | None:
    s = state.settings
    if not s.claude_url:
        return None
    bridge = ClaudeBridge(s.claude_url, s.claude_model, s.claude_timeout_s, s.claude_memory)
    return bridge, ClaudeBudget(s.data_dir / "claude-usage.json", s.claude_daily_limit)


def build_responder(
    state: AppState,
    provider: LLMProvider | None = None,
    extra_tools: Sequence[Tool] = (),
    claude: tuple[ClaudeBridge, ClaudeBudget] | None = None,
) -> AgentResponder | RoutedResponder:
    settings = state.settings
    registry = build_registry(
        extra_tools,
        devices=state.devices,
        memory=state.memory,
        sandbox=state.sandbox if settings.sandbox else None,
        pending=state.pending_plugins,
        inbox=state.inbox,
    )
    if settings.local_model:
        return _build_routed(state, registry, provider, claude or build_claude(state))
    provider = provider or _build_provider(state)
    agent = Agent(
        provider=provider,
        registry=registry,
        system_prompt=build_system_prompt,
        max_steps=settings.agent_max_steps,
        audit=state.audit,
    )
    return AgentResponder(state, agent)


def _build_routed(
    state: AppState,
    registry: ToolRegistry,
    provider: LLMProvider | None,
    claude: tuple[ClaudeBridge, ClaudeBudget] | None,
) -> RoutedResponder:
    settings = state.settings
    local_registry = registry.only(
        name for name in registry.names() if name not in LOCAL_EXCLUDED_TOOLS
    )
    if claude:
        local_registry.register(build_ask_claude_tool())
    agent = Agent(
        provider=provider or build_local_provider(state),
        registry=local_registry,
        system_prompt=lambda: build_local_prompt(claude is not None),
        # Jeder Schritt kostet auf der CPU Sekunden: lieber früh an Claude übergeben.
        max_steps=min(settings.agent_max_steps, 4),
        audit=state.audit,
        escalate_tool=ASK_CLAUDE if claude else None,
        extra_in_user=True,
    )
    bridge, budget = claude if claude else (None, None)
    return RoutedResponder(state, agent, settings.local_model, bridge, budget)


def _build_provider(state: AppState) -> LLMProvider:
    """Cloud-Modell, mit Offline-Fallback wenn `CAT_FALLBACK_MODEL` gesetzt ist."""
    settings = state.settings
    if not settings.fallback_model:
        return LiteLLMProvider(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.llm_max_tokens,
        )
    primary = LiteLLMProvider(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
    )
    local = LiteLLMProvider(
        model=settings.fallback_model,
        max_tokens=settings.llm_max_tokens,
        api_base=settings.ollama_url,
        timeout_s=180.0,  # lokale Modelle auf der CPU brauchen länger bis zum ersten Wort
        # Qwen3 denkt standardmäßig laut: "/no_think" schaltet das ab, Reste filtert ThinkFilter.
        system_suffix=" /no_think" if "qwen3" in settings.fallback_model else "",
        strip_think=True,
    )
    return FallbackProvider(
        primary,
        local,
        primary_name=settings.llm_model,
        fallback_name=settings.fallback_model,
        cooldown_s=settings.fallback_cooldown_s,
        on_change=state.set_provider,
    )
