"""Nur Heimnetz: lässt Anfragen aus dem Internet gar nicht erst an Cat heran.

Zusätzliche Sperre hinter Caddy (docs/public-access.md): Selbst wenn der Reverse-Proxy einmal
falsch eingestellt ist, kommt von einer öffentlichen Adresse nichts durch. Die Client-IP ist die
echte, sobald `CAT_TRUSTED_PROXIES` den Proxy nennt (Uvicorn setzt sie aus `X-Forwarded-For`).
"""

import ipaddress
import logging

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("cat.lan")


def is_private_host(host: str | None) -> bool:
    """Adresse aus dem Heimnetz (privat, Loopback, Link-Local). Unbekannt oder öffentlich: False."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global and not ip.is_multicast and not ip.is_unspecified


class LanOnlyMiddleware:
    """Antwortet Nicht-Heimnetz-Clients mit 403 (WebSocket: Schließen mit 1008)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._warned: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = client[0] if client else None
        if is_private_host(host):
            await self.app(scope, receive, send)
            return
        key = host or "?"
        if key not in self._warned and len(self._warned) < 200:
            self._warned.add(key)
            log.warning("Anfrage von außerhalb des Heimnetzes abgewiesen: %s", key)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
