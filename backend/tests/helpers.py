import json
from typing import Any


def drain_replay(ws: Any) -> list[dict[str, Any]]:
    """Liest das, was der Server beim Verbinden schickt (bis einschließlich device.list)."""
    seen: list[dict[str, Any]] = []
    for _ in range(100):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if event["type"] == "device.list":
            return seen
    raise AssertionError(f"device.list nicht empfangen: {seen}")
