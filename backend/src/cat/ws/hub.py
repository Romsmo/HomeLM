import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

from cat.ws.protocol import ServerEvent

log = logging.getLogger("cat.ws")


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, event: ServerEvent) -> None:
        # Mehrere Tasks dürfen dieselbe Verbindung nicht gleichzeitig beschreiben.
        async with self._lock:
            await self.ws.send_text(event.model_dump_json())


class Hub:
    def __init__(self) -> None:
        self.connections: set[Connection] = set()

    def add(self, ws: WebSocket) -> Connection:
        conn = Connection(ws)
        self.connections.add(conn)
        return conn

    def remove(self, conn: Connection) -> None:
        self.connections.discard(conn)

    async def broadcast(self, event: ServerEvent) -> None:
        for conn in list(self.connections):
            try:
                await conn.send(event)
            except Exception:  # Verbindung ist weg; der Empfangs-Loop räumt sie auf.
                log.debug("Senden fehlgeschlagen, Verbindung wird entfernt")
                self.connections.discard(conn)
