import ast
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable

from cat.agent.tools import Escalation, ToolContext, ToolError, ToolRegistry, ToolTrace
from cat.audit import AuditLog
from cat.intents.claims import claims_action
from cat.llm.base import LLMProvider, Message, TextDelta, ToolCall

log = logging.getLogger("cat.agent")

LIMIT_NOTICE = "(Ich breche hier ab: zu viele Werkzeugschritte für eine Antwort.)"
# Werkzeuge, mit denen eine Aussage über Geräte belegt wird.
DEVICE_TOOLS = frozenset({"set_state", "get_state", "list_devices"})
# So viele Zeichen einer Antwort werden zurückgehalten, bis klar ist, dass sie keine unbelegte
# Erfolgsmeldung ("Okay, das Licht ist aus") ist, oder bis der erste Satz zu Ende ist.
HOLD_CHARS = 80
CORRECTION = (
    "Hinweis des Systems: Du hast kein Werkzeug aufgerufen, deshalb ist nichts passiert und "
    "deine Antwort ist unbelegt. Rufe jetzt das passende Werkzeug auf (set_state zum Schalten, "
    "get_state oder list_devices zum Nachsehen) oder sag ehrlich, dass du es nicht kannst."
)
UNVERIFIED = (
    "Das habe ich nicht ausgeführt, weil ich dafür kein Gerät angesprochen habe. "
    "Bitte sag es noch einmal genauer, zum Beispiel mit dem Namen des Geräts."
)


def _sentence_end(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?", "\n"))


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

        corrections = 0
        guard = self._registry.get("set_state") is not None
        for _ in range(self._max_steps):
            step_text: list[str] = []
            calls: list[ToolCall] = []
            held: list[str] = []
            started = False  # in diesem Schritt schon Text ausgegeben?
            # Unbelegte Behauptungen über Geräte abfangen, solange noch kein Gerätewerkzeug lief.
            hold = guard and not any(t.tool in DEVICE_TOOLS for t in ctx.trace)

            model_started = time.perf_counter()
            async for event in self._provider.stream(system, messages, schemas):
                if not isinstance(event, TextDelta):
                    calls.append(event)
                    continue
                step_text.append(event.text)
                if hold:
                    held.append(event.text)
                    joined = "".join(held)
                    if ctx.device_related or claims_action(joined):
                        continue  # erst am Ende des Schritts entscheiden (kommt noch ein Werkzeug?)
                    if len(joined) < HOLD_CHARS and not _sentence_end(joined):
                        continue
                    hold = False
                    if wrote_text and not started:
                        yield "\n\n"  # Text nach einem Werkzeugschritt als neuer Absatz
                    started = True
                    yield joined
                    held.clear()
                    continue
                if wrote_text and not started:
                    yield "\n\n"
                started = True
                yield event.text

            model_s = time.perf_counter() - model_started
            if not calls and (typed := _typed_call("".join(step_text), self._registry)):
                # Aufruf als Text geschrieben ("get_state(device=...)"): trotzdem ausführen.
                calls.append(typed)
                step_text.clear()
                held.clear()
            if held:
                joined = "".join(held)
                if (ctx.device_related or claims_action(joined)) and not calls:
                    # "Okay, das Licht ist aus" ohne Werkzeugaufruf: nichts davon zeigen.
                    if corrections == 0:
                        corrections += 1
                        messages.append({"role": "assistant", "content": joined})
                        messages.append({"role": "user", "content": CORRECTION})
                        continue
                    if claims_action(joined):
                        yield ("\n\n" if wrote_text else "") + UNVERIFIED
                        return
                    # nur Gerätebezug vermutet (z. B. ein Name wie "Roman"): Antwort gilt
                if wrote_text and not started:
                    yield "\n\n"
                started = True
                yield joined

            if step_text and started:
                wrote_text = True
            if not calls:
                return

            if self._escalate_tool and (asked := _find(calls, self._escalate_tool)):
                question = (asked.arguments or {}).get("question", "")
                ctx.escalation = Escalation("model", question if isinstance(question, str) else "")
                return
            messages.append(_assistant_message("".join(step_text), calls))
            tools_started = time.perf_counter()
            ready = len(ctx.final_replies)
            ok_count = 0
            for call in calls:
                result = await self._execute(call, ctx)
                ok_count += ctx.trace[-1].ok
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            fresh = ctx.final_replies[ready:]
            log.info(
                "Zug: Modell %.1f s, Werkzeuge %.1f s (%s)",
                model_s,
                time.perf_counter() - tools_started,
                ", ".join(c.name for c in calls),
            )
            asks = "?" in _last_user_text(history)
            decided = all(c.name == "set_state" or asks for c in calls)
            if ok_count == len(calls) and len(fresh) == len(calls) and decided:
                # Jedes Werkzeug lieferte seinen fertigen Antworttext: kein zweiter Modellaufruf.
                yield ("\n\n" if wrote_text else "") + "\n".join(fresh)
                return

        if self._escalate_tool:
            ctx.escalation = Escalation("limit")
            return
        yield ("\n\n" if wrote_text else "") + LIMIT_NOTICE

    async def warm(self) -> None:
        """Lässt den Anbieter Systemprompt und Werkzeuge vorab verarbeiten (falls er das kann)."""
        warm = getattr(self._provider, "warm", None)
        if warm is not None:
            await warm(self._system_prompt(), self._registry.schemas())

    async def _execute(self, call: ToolCall, ctx: ToolContext) -> str:
        """Führt ein Werkzeug aus und protokolliert jeden Aufruf (auch Fehlschläge)."""
        result, ok = await self._run_tool(call, ctx)
        ctx.trace.append(ToolTrace(call.name, call.arguments or {}, ok, result))
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


_CALL_TEXT = re.compile(r"^\s*(\w+)\((.*)\)\s*$", re.DOTALL)


def _typed_call(text: str, registry: ToolRegistry) -> ToolCall | None:
    """Kleine Modelle schreiben Aufrufe manchmal als Text, statt sie auszulösen."""
    match = _CALL_TEXT.match(text)
    if match is None or registry.get(match.group(1)) is None:
        return None
    try:
        call = ast.parse(f"f({match.group(2)})", mode="eval").body
        assert isinstance(call, ast.Call) and not call.args
        args = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg}
    except (SyntaxError, ValueError, AssertionError):
        return None
    return ToolCall("text-call", match.group(1), args)


def _last_user_text(history: list[Message]) -> str:
    for message in reversed(history):
        if message["role"] == "user":
            return str(message.get("content") or "")
    return ""


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
