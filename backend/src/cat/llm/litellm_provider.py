import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from pydantic import SecretStr

from cat.llm.base import LLMError, LLMEvent, Message, TextDelta, ToolCall, ToolSchema

log = logging.getLogger("cat.llm")


def _load_litellm() -> Any:
    # Mitgelieferte Preisliste nutzen: kein Abruf von GitHub beim Import, auch offline lauffähig.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    litellm.telemetry = False
    litellm.suppress_debug_info = True
    return litellm


class LiteLLMProvider:
    """LiteLLM als Implementierung der Cat-Schnittstelle (Claude, OpenAI, Ollama, ...)."""

    def __init__(
        self,
        model: str,
        api_key: SecretStr | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.4,
        api_base: str | None = None,
        timeout_s: float | None = None,
        system_suffix: str = "",
        strip_think: bool = False,
    ) -> None:
        self._api_base = api_base
        self._timeout = timeout_s
        self._system_suffix = system_suffix
        self._strip_think = strip_think
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature

    def _needs_key(self) -> bool:
        return self._model.startswith(("anthropic/", "claude")) and not self._api_key

    async def stream(
        self, system: str, messages: list[Message], tools: list[ToolSchema]
    ) -> AsyncIterator[LLMEvent]:
        if self._needs_key():
            raise LLMError(
                "Kein API-Schlüssel gesetzt. Bitte ANTHROPIC_API_KEY in der .env eintragen "
                "und Cat neu starten."
            )
        litellm = _load_litellm()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system + self._system_suffix}, *messages],
            "stream": True,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if self._api_key:
            kwargs["api_key"] = self._api_key.get_secret_value()
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._timeout:
            kwargs["timeout"] = self._timeout
            kwargs["num_retries"] = 0  # schnell scheitern: das Offline-Modell soll rasch übernehmen

        try:
            response = await litellm.acompletion(**kwargs)
            pending: dict[int, dict[str, str]] = {}
            think = ThinkFilter() if self._strip_think else None
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text = think.feed(delta.content) if think else delta.content
                    if text:
                        yield TextDelta(text)
                for tc in delta.tool_calls or []:
                    slot = pending.setdefault(tc.index or 0, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
            if think and (rest := think.flush()):
                yield TextDelta(rest)
        except LLMError:
            raise
        except Exception as exc:
            message, unavailable = _describe(litellm, exc)
            raise LLMError(message, unavailable=unavailable) from exc

        for index in sorted(pending):
            slot = pending[index]
            yield ToolCall(
                id=slot["id"] or f"call_{index}",
                name=slot["name"],
                arguments=_parse_args(slot["args"]),
                raw_arguments=slot["args"],
            )


def _parse_args(raw: str) -> dict[str, Any] | None:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class ThinkFilter:
    """Entfernt <think>...</think>-Blöcke (Qwen3) aus einem Textstrom, auch bei geteilten Tags."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> str:
        self._buffer += text
        out: list[str] = []
        while True:
            if self._inside:
                end = self._buffer.find(self.CLOSE)
                if end == -1:
                    self._buffer = self._buffer[
                        -(len(self.CLOSE) - 1) :
                    ]  # Rest könnte Tag-Anfang sein
                    break
                self._buffer = self._buffer[end + len(self.CLOSE) :].lstrip("\n")
                self._inside = False
                continue
            start = self._buffer.find(self.OPEN)
            if start == -1:
                keep = _partial_suffix(self._buffer, self.OPEN)
                out.append(self._buffer[: len(self._buffer) - keep])
                self._buffer = self._buffer[len(self._buffer) - keep :]
                break
            out.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(self.OPEN) :]
            self._inside = True
        return "".join(out)

    def flush(self) -> str:
        """Am Stromende: zurückgehaltenen Rest freigeben (nicht, wenn ein Denkblock offen ist)."""
        rest, self._buffer = ("" if self._inside else self._buffer), ""
        return rest


def _partial_suffix(text: str, tag: str) -> int:
    """Länge des längsten Endstücks von `text`, das Anfang von `tag` sein könnte."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


_UNAVAILABLE = (
    "APIConnectionError",
    "Timeout",
    "RateLimitError",
    "ServiceUnavailableError",
    "InternalServerError",
)


def _describe(litellm: Any, exc: Exception) -> tuple[str, bool]:
    """Nutzerfreundliche Meldung ohne Interna oder Schlüssel, und ob der Anbieter nur nicht
    erreichbar ist (dann darf ein Offline-Modell übernehmen)."""
    log.warning("LLM-Aufruf fehlgeschlagen: %s", type(exc).__name__)
    unavailable = any(
        isinstance(exc, cls)
        for cls in (getattr(litellm, name, None) for name in _UNAVAILABLE)
        if isinstance(cls, type)
    )
    if isinstance(exc, litellm.AuthenticationError):
        return "Der API-Schlüssel wurde abgelehnt. Bitte ANTHROPIC_API_KEY prüfen.", False
    if isinstance(exc, litellm.RateLimitError):
        return "Das Sprachmodell ist gerade überlastet oder das Limit ist erreicht.", True
    if isinstance(exc, litellm.NotFoundError | litellm.BadRequestError):
        return (
            "Das Sprachmodell hat die Anfrage abgelehnt. CAT_LLM_MODEL prüfen.",
            False,
        )
    if isinstance(exc, litellm.APIConnectionError | litellm.Timeout):
        return "Keine Verbindung zum Sprachmodell. Ist das Internet erreichbar?", True
    return "Das Sprachmodell hat nicht geantwortet. Details im Log.", unavailable
