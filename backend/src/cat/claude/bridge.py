"""Client für die Claude-Brücke (Container `claude-bridge`, siehe docs/claude.md).

Die Brücke startet die Claude-Code-CLI (`claude -p`) mit dem Abo des Nutzers. Cat kennt weder
Token noch Anmeldedaten: es schickt nur Text hin und bekommt Text zurück.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("cat.claude")


@dataclass(frozen=True)
class ClaudeResult:
    ok: bool
    text: str = ""
    # Bei Fehlern: "limit" (Abo-Limit), "auth" (Token fehlt/ungültig), "timeout", "busy",
    # "unreachable" (Brücke nicht erreichbar), "error".
    kind: str = ""
    message: str = ""
    cost_usd: float | None = None
    turns: int | None = None
    duration_s: float = 0.0


class ClaudeBridge:
    def __init__(
        self,
        url: str,
        model: str = "sonnet",
        timeout_s: float = 240.0,
        memory: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self.model = model
        self._timeout = timeout_s
        self._memory = memory
        self._transport = transport

    async def ask(self, prompt: str, system: str) -> ClaudeResult:
        started = time.monotonic()
        body = {"prompt": prompt, "system": system, "model": self.model, "memory": self._memory}
        try:
            async with httpx.AsyncClient(
                # Etwas länger als das Zeitlimit der Brücke, damit deren Antwort ankommt.
                timeout=httpx.Timeout(connect=3.0, read=self._timeout + 15, write=10.0, pool=5.0),
                transport=self._transport,
            ) as http:
                response = await http.post(f"{self._url}/ask", json=body)
            data: dict[str, Any] = response.json()
        except httpx.ConnectError:
            return ClaudeResult(
                False,
                kind="unreachable",
                message="Die Claude-Brücke läuft nicht (docker compose --profile claude up -d).",
            )
        except httpx.TimeoutException:
            return ClaudeResult(False, kind="timeout", message="Claude hat zu lange gebraucht.")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Claude-Brücke: unbrauchbare Antwort (%s)", type(exc).__name__)
            return ClaudeResult(False, kind="error", message="Die Claude-Brücke antwortet nicht.")
        elapsed = time.monotonic() - started
        if response.status_code != 200 or not data.get("ok"):
            return ClaudeResult(
                False,
                kind=str(data.get("kind") or "error"),
                message=str(data.get("message") or "Claude konnte nicht antworten."),
                duration_s=elapsed,
            )
        text = str(data.get("text") or "").strip()
        if not text:
            return ClaudeResult(
                False, kind="error", message="Claude hat leer geantwortet.", duration_s=elapsed
            )
        cost = data.get("cost_usd")
        turns = data.get("turns")
        return ClaudeResult(
            True,
            text=text,
            cost_usd=float(cost) if isinstance(cost, int | float) else None,
            turns=int(turns) if isinstance(turns, int) else None,
            duration_s=elapsed,
        )

    async def health(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=3.0, transport=self._transport) as http:
                response = await http.get(f"{self._url}/health")
            data = response.json()
            return data if response.status_code == 200 and isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None
