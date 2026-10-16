import time
import uuid

from cat.stage.models import ChartSpec, StageItem

MAX_HISTORY = 20


class StageStore:
    """Kleine Historie der Stage-Inhalte (neuester zuletzt)."""

    def __init__(self, max_items: int = MAX_HISTORY) -> None:
        self._max = max_items
        self.items: list[StageItem] = []

    def add(
        self,
        kind: str,
        title: str,
        content: str = "",
        chart: ChartSpec | None = None,
    ) -> StageItem:
        item = StageItem(
            id=uuid.uuid4().hex,
            kind=kind,  # type: ignore[arg-type]
            title=title,
            content=content,
            chart=chart,
            created_at=time.time(),
        )
        self.items.append(item)
        del self.items[: -self._max]
        return item

    def clear(self) -> None:
        self.items.clear()
