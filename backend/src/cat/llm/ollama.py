"""Lokales Modell über die native Ollama-API (`/api/chat`), ohne LiteLLM.

Eigener Client, weil wir hier alles selbst steuern müssen: Kontextgröße und Threads je Anfrage,
`keep_alive`, `think: false` und die Werkzeugaufrufe (Ollama liefert sie vollständig und mit
Argumenten als Objekt, nicht als JSON-Text).
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from cat.llm.base import LLMError, LLMEvent, Message, TextDelta, ToolCall, ToolSchema
from cat.llm.litellm_provider import ThinkFilter

log = logging.getLogger("cat.llm")


class OllamaProvider:
    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        num_ctx: int = 4096,
        num_thread: int | None = None,
        keep_alive: str = "10m",
        timeout_s: float = 240.0,
        max_tokens: int = 700,
        temperature: float = 0.3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._url = base_url.rstrip("/") + "/api/chat"
        self._options: dict[str, Any] = {
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if num_thread:
            self._options["num_thread"] = num_thread
        self._keep_alive = keep_alive
        self._timeout = httpx.Timeout(connect=3.0, read=timeout_s, write=10.0, pool=5.0)
        self._transport = transport

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSchema]
    ) -> AsyncIterator[LLMEvent]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *_to_ollama(messages)],
            "stream": True,
            "think": False,
            "keep_alive": self._keep_alive,
            "options": self._options,
        }
        if tools:
            body["tools"] = tools
        think = ThinkFilter()
        calls: list[ToolCall] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
                async with http.stream("POST", self._url, json=body) as response:
                    if response.status_code != 200:
                        raise _http_error(response.status_code, await response.aread(), self._model)
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise LLMError(
                                f"Das lokale Modell meldet einen Fehler: {chunk['error']}",
                                unavailable=True,
                            )
                        message = chunk.get("message") or {}
                        if text := message.get("content"):
                            if shown := think.feed(text):
                                yield TextDelta(shown)
                        for raw in message.get("tool_calls") or []:
                            calls.append(_tool_call(raw))
        except LLMError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            log.warning("Ollama nicht erreichbar: %s", type(exc).__name__)
            raise LLMError(
                "Das lokale Modell ist nicht erreichbar (läuft der Ollama-Container?).",
                unavailable=True,
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Das lokale Modell hat zu lange gebraucht.", unavailable=True) from exc
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.warning("Ollama-Antwort unbrauchbar: %s", type(exc).__name__)
            raise LLMError(
                "Das lokale Modell hat nicht verständlich geantwortet.", unavailable=True
            ) from exc
        if rest := think.flush():
            yield TextDelta(rest)
        for call in calls:
            yield call


def _http_error(status: int, body: bytes, model: str) -> LLMError:
    detail = ""
    try:
        detail = str(json.loads(body).get("error", ""))[:200]
    except (ValueError, AttributeError):
        pass
    log.warning("Ollama antwortet mit HTTP %s: %s", status, detail)
    if status == 404:
        return LLMError(
            f"Das lokale Modell '{model}' ist nicht installiert (ollama pull {model}).",
            unavailable=True,
        )
    return LLMError(
        "Das lokale Modell konnte nicht antworten" + (f": {detail}" if detail else "."),
        unavailable=True,
    )


def _tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    arguments = function.get("arguments")
    raw_text = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = None
    return ToolCall(
        id=raw.get("id") or f"call_{uuid.uuid4().hex[:8]}",
        name=str(function.get("name", "")),
        arguments=arguments if isinstance(arguments, dict) else None,
        raw_arguments=raw_text,
    )


def _to_ollama(messages: list[Message]) -> list[dict[str, Any]]:
    """OpenAI-Nachrichten (Cat-intern) in das Ollama-Format: Argumente als Objekt, Werkzeug-
    ergebnisse mit dem Namen des Werkzeugs statt der Aufruf-ID."""
    names: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call["function"]
                names[call["id"]] = function["name"]
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                calls.append({"function": {"name": function["name"], "arguments": arguments}})
            out.append(
                {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_name": names.get(message.get("tool_call_id", ""), ""),
                    "content": message.get("content") or "",
                }
            )
        else:
            out.append({"role": role, "content": message.get("content") or ""})
    return out
