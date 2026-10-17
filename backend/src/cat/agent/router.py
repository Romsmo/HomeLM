"""Lokal zuerst, Claude nur für den Rest.

Das lokale Modell (Ollama) beantwortet alles selbst. Claude (über die Brücke und das Abo des
Nutzers) kommt nur ins Spiel, wenn

- das lokale Modell `ask_claude` aufruft ("das kann ich nicht sicher"),
- der Nutzer ausdrücklich Claude verlangt ("frag Claude ..."),
- das lokale Modell ausfällt, zu viele Schritte braucht oder nichts antwortet.

Der Fast-Path (Gerätebefehle) läuft davor in `dialog.py` und fragt nie Claude. Jede Frage an
Claude steht im Audit-Log und zählt gegen das Tageslimit.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from cat.agent.loop import Agent, to_llm_messages
from cat.agent.prompt import build_context
from cat.agent.tools import Escalation, Tool, ToolContext, ToolError
from cat.claude.bridge import ClaudeBridge, ClaudeResult
from cat.claude.budget import ClaudeBudget
from cat.claude.text import (
    CLAUDE_SYSTEM,
    FOOTER_PREFIX,
    build_prompt,
    chunk,
    is_explicit_request,
    split_html,
)
from cat.llm.base import LLMError
from cat.stage.tools import show_html
from cat.state import AppState
from cat.ws.protocol import ChatMessage

log = logging.getLogger("cat.agent")

ASK_CLAUDE = "ask_claude"
SPOKEN_HINT = (
    "Diese Antwort wird laut vorgelesen: höchstens 1 bis 2 kurze Sätze, kein Markdown, keine "
    "Aufzählungen, keine Sonderzeichen. Stelle bei Bedarf genau eine kurze Rückfrage."
)
# Wie lange Claude nach einem Fehler ruht (Sekunden).
BLOCK_LIMIT_S = 30 * 60
BLOCK_AUTH_S = 60 * 60
BLOCK_DOWN_S = 60


def build_ask_claude_tool() -> Tool:
    """Schema für das lokale Modell. Der Agent fängt den Aufruf ab (`Agent(escalate_tool=...)`),
    der Handler läuft nie."""

    async def never(_: dict[str, object], __: ToolContext) -> str:
        raise ToolError("ask_claude wird vom Router behandelt.")

    return Tool(
        name=ASK_CLAUDE,
        description=(
            "Gibt die Frage an Claude weiter, ein viel stärkeres Modell. Nutze es, wenn du "
            "die Aufgabe nicht sicher lösen kannst. Claude antwortet dem Nutzer direkt."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Die Aufgabe oder Frage, vollständig und verständlich.",
                }
            },
            "required": ["question"],
        },
        handler=never,
    )


class RoutedResponder:
    """Responder für den Lokal-zuerst-Modus (Protokoll `state.Responder`)."""

    def __init__(
        self,
        state: AppState,
        agent: Agent,
        local_name: str,
        claude: ClaudeBridge | None = None,
        budget: ClaudeBudget | None = None,
    ) -> None:
        self._state = state
        self._agent = agent
        self._local_name = local_name
        self._claude = claude
        self._budget = budget

    async def reply(self, history: list[ChatMessage], spoken: bool = False) -> AsyncIterator[str]:
        question = next((m.text for m in reversed(history) if m.role == "user"), "")
        if self._claude and is_explicit_request(question):
            async for part in self._escalate(history, Escalation("explicit"), spoken):
                yield part
            return

        ctx = ToolContext(emit=self._state.emit, stage=self._state.stage)
        memory = await asyncio.to_thread(self._state.memory.context_for, question)
        extra = "\n\n".join(
            p for p in (build_context(), memory, SPOKEN_HINT if spoken else "") if p
        )
        messages = to_llm_messages([(m.role, m.text) for m in history])
        shown = False
        try:
            async for delta in self._agent.run(messages, ctx, system_extra=extra):
                shown = shown or bool(delta.strip())
                yield delta
        except LLMError as exc:
            if self._claude and not shown:
                log.warning("Lokales Modell ausgefallen, Claude übernimmt: %s", exc)
                async for part in self._escalate(history, Escalation("failed", str(exc)), spoken):
                    yield part
                return
            yield f"Das hat leider nicht geklappt: {exc}"
            return

        escalation = ctx.escalation or (None if shown else Escalation("empty"))
        if escalation is None:
            return
        if shown:
            yield "\n\n"
        if self._claude is None:
            yield "Dazu fällt mir lokal keine verlässliche Antwort ein."
            return
        async for part in self._escalate(history, escalation, spoken):
            yield part

    async def _escalate(
        self, history: list[ChatMessage], escalation: Escalation, spoken: bool
    ) -> AsyncIterator[str]:
        assert self._claude is not None and self._budget is not None
        if reason := self._budget.blocked():
            yield self._refusal(escalation, reason)
            return
        question = next((m.text for m in reversed(history) if m.role == "user"), "")
        memory = await asyncio.to_thread(self._state.memory.context_for, question)
        # Das lokale Modell darf die Frage präzisieren; bei Ausfall steht dort nur der Fehlertext.
        note = escalation.question if escalation.reason == "model" else ""
        prompt = build_prompt(history, note, memory, spoken)
        self._budget.record()
        await self._state.set_provider(f"claude/{self._claude.model}", False)
        try:
            result = await self._claude.ask(prompt, CLAUDE_SYSTEM)
        finally:
            await self._state.set_provider(self._local_name, False)
        await self._audit(escalation, question, prompt, result)

        if not result.ok:
            self._block_after(result)
            yield self._refusal(escalation, result.message)
            return
        text, pages = split_html(result.text)
        ctx = ToolContext(emit=self._state.emit, stage=self._state.stage)
        for title, html in pages:
            try:
                await show_html({"title": title, "html": html}, ctx)
            except ToolError as exc:
                text += f"\n\n(Die Grafik konnte nicht angezeigt werden: {exc})"
        for part in chunk(text or "Das habe ich auf der Stage angezeigt."):
            yield part
        if not spoken:
            yield FOOTER_PREFIX

    def _block_after(self, result: ClaudeResult) -> None:
        assert self._budget is not None
        if result.kind == "limit":
            self._budget.block(BLOCK_LIMIT_S, "Das Abo-Limit von Claude ist gerade erreicht.")
        elif result.kind == "auth":
            self._budget.block(BLOCK_AUTH_S, "Claude ist nicht angemeldet (Token prüfen).")
        elif result.kind == "unreachable":
            self._budget.block(BLOCK_DOWN_S, result.message)

    async def _audit(
        self, escalation: Escalation, question: str, prompt: str, result: ClaudeResult
    ) -> None:
        assert self._claude is not None
        await self._state.audit.record(
            "claude_escalation",
            {
                "reason": escalation.reason,
                "model": self._claude.model,
                "question": question,
                "prompt_chars": len(prompt),
            },
            f"{len(result.text)} Zeichen, {result.duration_s:.1f} s"
            if result.ok
            else f"{result.kind}: {result.message}",
            ok=result.ok,
            source="router",
        )

    @staticmethod
    def _refusal(escalation: Escalation, reason: str) -> str:
        if escalation.reason == "failed":
            return (
                f"Das lokale Modell hat nicht geantwortet, und Claude geht gerade nicht: {reason}"
            )
        return f"Dafür bräuchte ich Claude, aber das geht gerade nicht: {reason}"
