"""Nur Heimnetz: lässt Anfragen aus dem Internet gar nicht erst an Cat heran.

Zusätzliche Sperre hinter Caddy (docs/public-access.md): Selbst wenn der Reverse-Proxy einmal
falsch eingestellt ist, kommt von einer öffentlichen Adresse nichts durch. Die Client-IP ist die
echte, sobald `CAT_TRUSTED_PROXIES` den Proxy nennt (Uvicorn setzt sie aus `X-Forwarded-For`).

Vertraut wird neben dem Heimnetz (privaten Adressen) optional:

- festen Adressen oder Netzen (`CAT_LAN_TRUSTED_IPS`),
- den **aufgelösten Adressen von Namen** (`CAT_LAN_TRUSTED_HOSTS`, z. B. `ai.catscastlecloud.de`).
  Ruft ein Gerät im Heimnetz die Domain auf, schickt der Router die Anfrage über die öffentliche
  Adresse des Anschlusses zurück (NAT-Loopback), und Caddy sieht diese als Absender. Die Adresse
  ändert sich (dynamische IP), darum wird der Name regelmäßig neu aufgelöst. Aus dem Internet
  kann niemand mit der Adresse des eigenen Anschlusses als Absender kommen.
"""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger("cat.lan")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
Resolver = Callable[[str], Awaitable[Iterable[str]]]


def _parse(host: str | None) -> IPAddress | None:
    if not host:
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_private_host(host: str | None) -> bool:
    """Adresse aus dem Heimnetz (privat, Loopback, Link-Local). Unbekannt oder öffentlich: False."""
    ip = _parse(host)
    if ip is None:
        return False
    return not ip.is_global and not ip.is_multicast and not ip.is_unspecified


async def resolve_name(name: str) -> list[str]:
    """Alle IPv4/IPv6-Adressen eines Namens (ohne den Ereignisloop zu blockieren)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(name, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


class LanPolicy:
    """Entscheidet, ob eine Client-Adresse als "Heimnetz" gilt."""

    def __init__(
        self,
        trusted_hosts: Iterable[str] = (),
        trusted_ips: Iterable[str] = (),
        resolver: Resolver = resolve_name,
        refresh_s: float = 300.0,
    ) -> None:
        self.hosts = list(trusted_hosts)
        self.networks: list[IPNetwork] = [
            ipaddress.ip_network(item, strict=False) for item in trusted_ips
        ]
        self._resolver = resolver
        self._refresh_s = refresh_s
        self._resolved: frozenset[str] = frozenset()

    @property
    def resolved(self) -> frozenset[str]:
        return self._resolved

    def allows(self, host: str | None) -> bool:
        ip = _parse(host)
        if ip is None:
            return False
        if is_private_host(host):
            return True
        return str(ip) in self._resolved or any(ip in net for net in self.networks)

    async def refresh(self) -> None:
        """Löst die Namen neu auf. Schlägt es fehl, bleibt die letzte Liste (nie mehr Vertrauen)."""
        found: set[str] = set()
        for name in self.hosts:
            try:
                found.update(str(ip) for ip in await self._resolver(name))
            except Exception as err:
                log.warning("Auflösen von %s fehlgeschlagen: %s", name, err)
                return
        # Nur öffentliche Adressen sind hier von Belang; private gelten ohnehin.
        new = frozenset(a for a in found if (ip := _parse(a)) is not None and ip.is_global)
        if new != self._resolved:
            log.info("Vertraute Adressen aus %s: %s", ", ".join(self.hosts), ", ".join(sorted(new)))
        self._resolved = new

    async def run(self) -> None:
        """Hintergrundaufgabe: Namen laufend neu auflösen (wird beim Beenden abgebrochen)."""
        while True:
            await self.refresh()
            await asyncio.sleep(self._refresh_s)


class LanOnlyMiddleware:
    """Antwortet Nicht-Heimnetz-Clients mit 403 (WebSocket: Schließen mit 1008)."""

    def __init__(self, app: ASGIApp, policy: LanPolicy | None = None, **_: Any) -> None:
        self.app = app
        self.policy = policy or LanPolicy()
        self._warned: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = client[0] if client else None
        if self.policy.allows(host):
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
