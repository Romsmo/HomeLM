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
    ) -> None:
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
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if self._api_key:
            kwargs["api_key"] = self._api_key.get_secret_value()

        try:
            response = await litellm.acompletion(**kwargs)
            pending: dict[int, dict[str, str]] = {}
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    slot = pending.setdefault(tc.index or 0, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(_describe(litellm, exc)) from exc

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


def _describe(litellm: Any, exc: Exception) -> str:
    """Nutzerfreundliche Fehlermeldung ohne interne Details oder Schlüssel."""
    log.warning("LLM-Aufruf fehlgeschlagen: %s", type(exc).__name__)
    if isinstance(exc, litellm.AuthenticationError):
        return "Der API-Schlüssel wurde abgelehnt. Bitte ANTHROPIC_API_KEY prüfen."
    if isinstance(exc, litellm.RateLimitError):
        return "Das Sprachmodell ist gerade überlastet oder das Limit ist erreicht."
    if isinstance(exc, litellm.NotFoundError | litellm.BadRequestError):
        return "Das Sprachmodell hat die Anfrage abgelehnt. Modellname (CAT_LLM_MODEL) prüfen."
    if isinstance(exc, litellm.APIConnectionError | litellm.Timeout):
        return "Keine Verbindung zum Sprachmodell. Ist das Internet erreichbar?"
    return "Das Sprachmodell hat nicht geantwortet. Details im Log."
