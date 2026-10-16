"""Plugin-Schnittstelle von Cat. Jedes Plugin liegt in plugins/<name>/ und implementiert Plugin."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from cat.agent.tools import Tool
from cat.config import Settings
from cat.ws.protocol import WidgetStatus, WidgetUpdate


@dataclass(frozen=True)
class WidgetSpec:
    """Beschreibt ein Dashboard-Widget; `kind` wählt im Frontend die Darstellung."""

    id: str
    title: str
    kind: str
    refreshable: bool = False


@dataclass(frozen=True)
class IntentSpec:
    """Fast-Path-Intent (ohne LLM). Wird in Phase 5 ausgebaut."""

    name: str


@dataclass(frozen=True)
class PluginContext:
    settings: Settings
    publish: Callable[[WidgetUpdate], Awaitable[None]]


class Plugin(Protocol):
    name: str

    async def start(self, ctx: PluginContext) -> None: ...

    async def stop(self) -> None: ...

    def tools(self) -> list[Tool]: ...

    def widgets(self) -> list[WidgetSpec]: ...

    def intents(self) -> list[IntentSpec]: ...

    async def refresh(self, widget_id: str) -> bool:
        """Widget sofort neu laden. False, wenn dieses Widget nicht aktualisierbar ist."""
        ...


class BasePlugin:
    """Sinnvolle Vorgaben, damit Plugins nur überschreiben, was sie brauchen."""

    name = "base"

    async def start(self, ctx: PluginContext) -> None:
        return None

    async def stop(self) -> None:
        return None

    def tools(self) -> list[Tool]:
        return []

    def widgets(self) -> list[WidgetSpec]:
        return []

    def intents(self) -> list[IntentSpec]:
        return []

    async def refresh(self, widget_id: str) -> bool:
        return False


def make_update(
    spec: WidgetSpec,
    status: WidgetStatus,
    data: dict[str, object] | None = None,
    error: str | None = None,
) -> WidgetUpdate:
    return WidgetUpdate(
        id=spec.id,
        kind=spec.kind,
        title=spec.title,
        status=status,
        data=data or {},
        error=error,
        updated_at=time.time(),
        refreshable=spec.refreshable,
    )
