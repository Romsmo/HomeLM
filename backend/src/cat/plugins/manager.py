import logging
from collections.abc import Awaitable, Callable

from cat.agent.tools import Tool
from cat.config import Settings
from cat.plugins.base import Plugin, PluginContext, make_update
from cat.ws.protocol import WidgetUpdate

log = logging.getLogger("cat.plugins")


class PluginManager:
    def __init__(
        self,
        plugins: list[Plugin],
        settings: Settings,
        publish: Callable[[WidgetUpdate], Awaitable[None]],
    ) -> None:
        self.plugins = plugins
        self._ctx = PluginContext(settings=settings, publish=publish)
        self._publish = publish
        self._started: list[Plugin] = []

    async def start(self) -> None:
        for plugin in self.plugins:
            # Sofort einen "loading"-Stand zeigen, damit Widgets nicht leer wirken.
            for spec in plugin.widgets():
                await self._publish(make_update(spec, "loading"))
            try:
                await plugin.start(self._ctx)
                self._started.append(plugin)
            except Exception:
                # Ein kaputtes Plugin darf Cat und die anderen Plugins nicht lahmlegen.
                log.exception("Plugin %s konnte nicht starten", plugin.name)
                for spec in plugin.widgets():
                    await self._publish(make_update(spec, "error", error="Plugin nicht gestartet"))

    async def stop(self) -> None:
        for plugin in reversed(self._started):
            try:
                await plugin.stop()
            except Exception:
                log.exception("Plugin %s konnte nicht sauber stoppen", plugin.name)
        self._started.clear()

    def tools(self) -> list[Tool]:
        return [tool for plugin in self.plugins for tool in plugin.tools()]

    async def refresh(self, widget_id: str) -> bool:
        for plugin in self._started:
            if any(w.id == widget_id and w.refreshable for w in plugin.widgets()):
                return await plugin.refresh(widget_id)
        return False
