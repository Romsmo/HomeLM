import json
from typing import Any


def drain_replay(ws: Any) -> list[dict[str, Any]]:
    """Liest das, was der Server beim Verbinden schickt (bis einschließlich provider.state)."""
    seen: list[dict[str, Any]] = []
    for _ in range(100):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if event["type"] == "provider.state":
            return seen
    raise AssertionError(f"provider.state nicht empfangen: {seen}")
