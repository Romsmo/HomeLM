import json
import logging
from collections.abc import AsyncIterator, Callable

from cat.agent.tools import Escalation, ToolContext, ToolError, ToolRegistry
from cat.audit import AuditLog
from cat.llm.base import LLMProvider, Message, TextDelta, ToolCall

log = logging.getLogger("cat.agent")

LIMIT_NOTICE = "(Ich breche hier ab: zu viele Werkzeugschritte für eine Antwort.)"


class Agent:
    """Tool-Calling-Schleife: Modell fragen, Werkzeuge ausführen, wiederholen bis Text kommt."""

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        system_prompt: Callable[[], str],
        max_steps: int = 6,
        audit: AuditLog | None = None,
        escalate_tool: str | None = None,
        extra_in_user: bool = False,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._audit = audit
        # Lokal-zuerst-Modus: Ruft das Modell dieses Werkzeug auf (ask_claude), bricht der Agent
        # ab und setzt `ctx.escalation`; die Schleife wird dann nicht "zu lang", sondern
        # übergibt (kein LIMIT_NOTICE). Der Router fragt Claude.
        self._escalate_tool = escalate_tool
        # Zeit und Erinnerungen an die letzte Nutzernachricht hängen statt an den Systemprompt.
        # Der Systemprompt samt Werkzeugen bleibt dadurch unverändert, und Ollama muss ihn nicht
        # jedes Mal neu verarbeiten (auf der CPU sind das sonst über eine Minute).
        self._extra_in_user = extra_in_user

    async def run(
        self, history: list[Message], ctx: ToolContext, system_extra: str = ""
    ) -> AsyncIterator[str]:
        """Liefert den Antworttext in Teilen. `history` wird nicht verändert."""
        messages = list(history)
        schemas = self._registry.schemas()
        wrote_text = False
        system = self._system_prompt()
        if system_extra and self._extra_in_user:
            messages = _with_context(messages, system_extra)
        elif system_extra:
            system += f"\n\n{system_extra}"

        for _ in range(self._max_steps):
            step_text: list[str] = []
            calls: list[ToolCall] = []
            async for event in self._provider.stream(system, messages, schemas):
                if isinstance(event, TextDelta):
                    if not step_text and wrote_text:
                        yield "\n\n"  # Text nach einem Werkzeugschritt als neuer Absatz
                    step_text.append(event.text)
                    yield event.text
                else:
                    calls.append(event)

            if step_text:
                wrote_text = True
            if not calls:
                return

            if self._escalate_tool and (asked := _find(calls, self._escalate_tool)):
                question = (asked.arguments or {}).get("question", "")
                ctx.escalation = Escalation("model", question if isinstance(question, str) else "")
                return
            messages.append(_assistant_message("".join(step_text), calls))
            for call in calls:
                result = await self._execute(call, ctx)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        if self._escalate_tool:
            ctx.escalation = Escalation("limit")
            return
        yield ("\n\n" if wrote_text else "") + LIMIT_NOTICE

    async def _execute(self, call: ToolCall, ctx: ToolContext) -> str:
        """Führt ein Werkzeug aus und protokolliert jeden Aufruf (auch Fehlschläge)."""
        result, ok = await self._run_tool(call, ctx)
        if self._audit is not None:
            await self._audit.record(call.name, call.arguments, result, ok=ok, source="agent")
        return result

    async def _run_tool(self, call: ToolCall, ctx: ToolContext) -> tuple[str, bool]:
        tool = self._registry.get(call.name)
        if tool is None:
            return f"Fehler: Das Werkzeug '{call.name}' gibt es nicht.", False
        if call.arguments is None:
            return "Fehler: Die Argumente sind kein gültiges JSON-Objekt.", False
        try:
            return await tool.handler(call.arguments, ctx), True
        except ToolError as exc:
            return f"Fehler: {exc}", False
        except Exception:
            log.exception("Werkzeug %s ist abgestürzt", call.name)
            return "Fehler: Das Werkzeug ist intern fehlgeschlagen.", False


def _find(calls: list[ToolCall], name: str) -> ToolCall | None:
    return next((c for c in calls if c.name == name), None)


def _with_context(messages: list[Message], context: str) -> list[Message]:
    """Setzt den Kontext vor die letzte Nutzernachricht (die Liste wird nicht verändert)."""
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if out[i]["role"] == "user":
            out[i] = {"role": "user", "content": f"[{context}]\n\n{out[i]['content']}"}
            break
    return out


def _assistant_message(text: str, calls: list[ToolCall]) -> Message:
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": json.dumps(c.arguments, ensure_ascii=False)
                    if c.arguments is not None
                    else (c.raw_arguments or "{}"),
                },
            }
            for c in calls
        ],
    }


def to_llm_messages(items: list[tuple[str, str]], limit: int = 30) -> list[Message]:
    """Wandelt (Rolle, Text) in LLM-Nachrichten: letzte `limit`, beginnend mit Nutzer, ohne
    aufeinanderfolgende gleiche Rollen (nach einem fehlgeschlagenen Turn)."""
    out: list[Message] = []
    for role, text in items[-limit:]:
        if role not in ("user", "assistant") or not text.strip():
            continue
        if not out and role != "user":
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": f"{out[-1]['content']}\n\n{text}"}
        else:
            out.append({"role": role, "content": text})
    return out
