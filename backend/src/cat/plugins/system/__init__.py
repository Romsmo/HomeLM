"""Plugin "system": CPU, RAM, Datenträger und Uptime per psutil, live per WebSocket."""

import asyncio
import logging
import time
from typing import Any

import psutil

from cat.agent.tools import Tool, ToolContext
from cat.plugins.base import BasePlugin, PluginContext, WidgetSpec, make_update

log = logging.getLogger("cat.plugins.system")

SYSTEM = WidgetSpec("system", "System", "system")
UPTIME = WidgetSpec("uptime", "Uptime", "uptime")


def collect_system(disk_path: str) -> dict[str, object]:
    """Messwerte des Rechners (im Container die des Hosts bei CPU/RAM, siehe docs)."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(disk_path)
    load = psutil.getloadavg()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(logical=True),
        "load": [round(x, 2) for x in load],
        "mem_total": mem.total,
        "mem_used": mem.total - mem.available,
        "mem_percent": mem.percent,
        "disk_path": disk_path,
        "disk_total": disk.total,
        "disk_used": disk.used,
        "disk_percent": disk.percent,
    }


def collect_uptime(started_at: float, now: float | None = None) -> dict[str, object]:
    now = now or time.time()
    return {
        "system_seconds": max(0, int(now - psutil.boot_time())),
        "cat_seconds": max(0, int(now - started_at)),
    }


def _gb(value: object) -> str:
    return f"{float(value) / 1024**3:.1f}"  # type: ignore[arg-type]


def describe(system: dict[str, object], uptime: dict[str, object]) -> str:
    days, rest = divmod(int(uptime["system_seconds"]), 86400)  # type: ignore[call-overload]
    hours = rest // 3600
    return (
        f"CPU {system['cpu_percent']} % ({system['cpu_count']} Kerne), "
        f"Arbeitsspeicher {_gb(system['mem_used'])} von {_gb(system['mem_total'])} GB "
        f"({system['mem_percent']} %), Datenträger {system['disk_path']} "
        f"{_gb(system['disk_used'])} von {_gb(system['disk_total'])} GB "
        f"({system['disk_percent']} %), Rechner läuft seit {days} Tagen und {hours} Stunden."
    )


class SystemPlugin(BasePlugin):
    name = "system"

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._ctx: PluginContext | None = None
        self._started_at = time.time()
        self._disk_path = "/"

    def widgets(self) -> list[WidgetSpec]:
        return [SYSTEM, UPTIME]

    async def start(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._disk_path = ctx.settings.disk_path
        self._started_at = time.time()
        psutil.cpu_percent(interval=None)  # erster Aufruf liefert immer 0, daher vorwärmen
        self._task = asyncio.create_task(self._loop(ctx.settings.system_interval_s))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self, interval: float) -> None:
        while True:
            await self._publish_once()
            await asyncio.sleep(interval)

    async def _publish_once(self) -> None:
        assert self._ctx is not None
        try:
            # Plattenzugriffe laufen im Thread, damit der Event-Loop nie blockiert.
            system = await asyncio.to_thread(collect_system, self._disk_path)
            uptime = collect_uptime(self._started_at)
        except Exception as exc:
            log.warning("Systemwerte nicht lesbar: %s", type(exc).__name__)
            message = "Systemwerte nicht lesbar"
            await self._ctx.publish(make_update(SYSTEM, "error", error=message))
            await self._ctx.publish(make_update(UPTIME, "error", error=message))
            return
        await self._ctx.publish(make_update(SYSTEM, "ok", system))
        await self._ctx.publish(make_update(UPTIME, "ok", uptime))

    def tools(self) -> list[Tool]:
        async def get_system_status(_: dict[str, Any], __: ToolContext) -> str:
            system = await asyncio.to_thread(collect_system, self._disk_path)
            return describe(system, collect_uptime(self._started_at))

        return [
            Tool(
                name="get_system_status",
                description="Liest CPU, Arbeitsspeicher, Datenträger und Laufzeit des Servers.",
                parameters={"type": "object", "properties": {}},
                handler=get_system_status,
            )
        ]
