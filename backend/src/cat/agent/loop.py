import ast
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable

from cat.agent.tools import Escalation, ToolContext, ToolError, ToolRegistry, ToolTrace
from cat.audit import AuditLog
from cat.intents.claims import claims_action
from cat.intents.text import has_control_cue, is_question, power_conflict
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
        hidden_tools: frozenset[str] = frozenset(),
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
        # Werkzeuge, die das Modell nicht als Schema sieht, sondern als Kurzzeile schreibt
        # ("S|Licht Büro|off", siehe _compact_calls): wenige Ausgabe-Token, schnellere Antwort.
        self._hidden = hidden_tools

    async def run(
        self, history: list[Message], ctx: ToolContext, system_extra: str = ""
    ) -> AsyncIterator[str]:
        """Liefert den Antworttext in Teilen. `history` wird nicht verändert."""
        messages = list(history)
        schemas = self._registry.schemas(self._hidden)
        wrote_text = False
        system = self._system_prompt()
        if system_extra and self._extra_in_user:
            messages = _with_context(messages, system_extra)
        elif system_extra:
            system += f"\n\n{system_extra}"

        corrections = 0
        guard = self._registry.get("set_state") is not None
        # Befehl (keine Frage) über Geräte: erst erledigt, wenn set_state lief. Kleine Modelle
        # lesen gern erst den Zustand und kündigen dann nur an ("Ich schalte es aus").
        asked = _last_user_text(history)
        command = ctx.device_related and not is_question(asked) and has_control_cue(asked)
        for _ in range(self._max_steps):
            step_text: list[str] = []
            calls: list[ToolCall] = []
            held: list[str] = []
            started = False  # in diesem Schritt schon Text ausgegeben?
            # Unbelegte Behauptungen über Geräte abfangen, solange noch kein Gerätewerkzeug lief.
            hold = guard and (
                not any(t.tool in DEVICE_TOOLS for t in ctx.trace)
                or (command and not any(t.tool == "set_state" for t in ctx.trace))
            )

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
                if self._hidden and not started:
                    # Anfang der Antwort puffern: "S|..." ist eine Kurzzeile und wird nie angezeigt.
                    joined = "".join(step_text)
                    if _COMPACT_START.match(joined):
                        hold, held = True, [joined]
                        continue
                    if not joined.strip() or joined.strip() in _COMPACT_LETTERS:
                        continue
                    if wrote_text:
                        yield "\n\n"
                    started = True
                    yield joined
                    continue
                if wrote_text and not started:
                    yield "\n\n"
                started = True
                yield event.text

            model_s = time.perf_counter() - model_started
            raw_out = "".join(step_text)
            if not calls and (typed := _typed_calls("".join(step_text), self._registry)):
                # Kurzzeile ("S|Licht Büro|off") oder als Text geschriebener Aufruf
                # ("get_state(device=...)"): ausführen.
                calls.extend(typed)
                step_text.clear()
                held.clear()
            elif not calls and not started and not held and step_text:
                if wrote_text:
                    yield "\n\n"
                started = True
                yield "".join(step_text)  # kurzer Text, der noch im Puffer war
            if held:
                joined = "".join(held)
                if (ctx.device_related or claims_action(joined)) and not calls:
                    # "Okay, das Licht ist aus" ohne Werkzeugaufruf: nichts davon zeigen.
                    if corrections == 0:
                        corrections += 1
                        log.info("Korrektur: Modell antwortete ohne Werkzeug (%.80r)", joined)
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
            user_text = _last_user_text(history)
            tools_started = time.perf_counter()
            ready = len(ctx.final_replies)
            ok_count = 0
            for call in calls:
                result = await self._execute(call, ctx, user_text)
                ok_count += ctx.trace[-1].ok
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            fresh = ctx.final_replies[ready:]
            log.info(
                "Zug: Modell %.1f s, Werkzeuge %.1f s (%s) Ausgabe %.60r",
                model_s,
                time.perf_counter() - tools_started,
                ", ".join(c.name for c in calls),
                raw_out,
            )
            decided = all(c.name == "set_state" or not command for c in calls)
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
            await warm(self._system_prompt(), self._registry.schemas(self._hidden))

    async def _execute(self, call: ToolCall, ctx: ToolContext, user_text: str = "") -> str:
        """Führt ein Werkzeug aus und protokolliert jeden Aufruf (auch Fehlschläge)."""
        result, ok = await self._run_tool(call, ctx, user_text)
        ctx.trace.append(ToolTrace(call.name, call.arguments or {}, ok, result))
        if self._audit is not None:
            await self._audit.record(call.name, call.arguments, result, ok=ok, source="agent")
        return result

    async def _run_tool(
        self, call: ToolCall, ctx: ToolContext, user_text: str = ""
    ) -> tuple[str, bool]:
        tool = self._registry.get(call.name)
        if tool is None:
            return f"Fehler: Das Werkzeug '{call.name}' gibt es nicht.", False
        if call.arguments is None:
            return "Fehler: Die Argumente sind kein gültiges JSON-Objekt.", False
        if call.name == "set_state" and (
            word := power_conflict(user_text, str(call.arguments.get("command", "")).lower())
        ):
            return (
                f'Fehler: Der Nutzer hat "{word}" gesagt, du hast aber das Gegenteil gesendet. '
                "Nichts wurde geschaltet. Rufe set_state mit dem richtigen Befehl noch einmal auf.",
                False,
            )
        try:
            return await tool.handler(call.arguments, ctx), True
        except ToolError as exc:
            return f"Fehler: {exc}", False
        except Exception:
            log.exception("Werkzeug %s ist abgestürzt", call.name)
            return "Fehler: Das Werkzeug ist intern fehlgeschlagen.", False


_CALL_TEXT = re.compile(r"^\s*(\w+)\((.*)\)\s*$", re.DOTALL)
_COMPACT_START = re.compile(r"^\s*[SGLA]\|")
_COMPACT_LINE = re.compile(r"^\s*([SGLA])\|(.*)$")
_COMPACT_LETTERS = frozenset("SGLA")
MAX_COMPACT_CALLS = 4


def _clean(part: str) -> str:
    return part.strip(" `\"'")


def _compact_calls(text: str, registry: ToolRegistry) -> list[ToolCall]:
    """Kurzzeilen des Modells als Werkzeugaufrufe. Eine Zeile je Aufruf:

    S|Gerät|Befehl (set_state), G|Gerät (get_state), L|Stichwort|Zustand (list_devices),
    A|Stichwort|Zustand (list_automations). Steht in der Antwort etwas anderes, gilt sie nicht.
    """
    calls: list[ToolCall] = []
    for index, line in enumerate(raw for raw in text.splitlines() if raw.strip()):
        match = _COMPACT_LINE.match(line)
        if match is None:
            return []
        kind = match.group(1)
        parts = [_clean(p) for p in match.group(2).split("|")]
        if kind == "S" and len(parts) >= 2 and parts[0] and parts[1]:
            name, args = "set_state", {"device": parts[0], "command": parts[1]}
        elif kind == "G" and parts[0]:
            name, args = "get_state", {"device": parts[0]}
        elif kind in ("L", "A"):
            name = "list_devices" if kind == "L" else "list_automations"
            args = {}
            if parts[0]:
                args["query"] = parts[0]
            if len(parts) > 1 and parts[1]:
                args["state"] = parts[1]
        else:
            return []
        if registry.get(name) is None:
            return []
        calls.append(ToolCall(f"compact-{index}", name, args))
    return calls[:MAX_COMPACT_CALLS]


def _typed_calls(text: str, registry: ToolRegistry) -> list[ToolCall]:
    """Kleine Modelle schreiben Aufrufe als Text statt sie auszulösen: Kurzzeilen oder
    `name(arg="...")`."""
    if compact := _compact_calls(text, registry):
        return compact
    match = _CALL_TEXT.match(text)
    if match is None or registry.get(match.group(1)) is None:
        return []
    try:
        call = ast.parse(f"f({match.group(2)})", mode="eval").body
        assert isinstance(call, ast.Call) and not call.args
        args = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg}
    except (SyntaxError, ValueError, AssertionError):
        return []
    return [ToolCall("text-call", match.group(1), args)]


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


def to_llm_messages(
    items: list[tuple[str, str]], limit: int = 30, max_chars: int | None = None
) -> list[Message]:
    """Wandelt (Rolle, Text) in LLM-Nachrichten: letzte `limit`, beginnend mit Nutzer, ohne
    aufeinanderfolgende gleiche Rollen (nach einem fehlgeschlagenen Turn)."""
    out: list[Message] = []
    kept = items[-limit:]
    for index, (role, text) in enumerate(kept):
        if role not in ("user", "assistant") or not text.strip():
            continue
        if max_chars and index < len(kept) - 1 and len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"  # ältere Nachrichten kürzen
        if not out and role != "user":
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": f"{out[-1]['content']}\n\n{text}"}
        else:
            out.append({"role": role, "content": text})
    return out
