import asyncio
import json
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.config import Settings
from cat.main import create_app
from cat.plugins.base import BasePlugin, PluginContext, WidgetSpec, make_update
from cat.plugins.manager import PluginManager
from cat.plugins.system import SystemPlugin, collect_system, collect_uptime, describe
from cat.plugins.weather import NO_LOCATION, WeatherPlugin
from cat.plugins.weather import describe as describe_weather
from cat.plugins.weather.wmo import wmo_label
from cat.stage.store import StageStore
from cat.ws.protocol import WidgetUpdate
from tests.conftest import PASSWORD
from tests.helpers import drain_replay


class Recorder:
    def __init__(self) -> None:
        self.updates: list[WidgetUpdate] = []

    async def __call__(self, update: WidgetUpdate) -> None:
        self.updates.append(update)

    def last(self, widget_id: str) -> WidgetUpdate:
        return next(u for u in reversed(self.updates) if u.id == widget_id)


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, static_dir=None, plugins="", **kw)  # type: ignore[call-arg]


def tool_ctx() -> ToolContext:
    async def emit(_: object) -> None: ...

    return ToolContext(emit=emit, stage=StageStore())


# --- System ---


def test_collect_system_has_sane_values() -> None:
    data = collect_system("/")
    assert 0 <= float(data["cpu_percent"]) <= 100  # type: ignore[arg-type]
    assert 0 < float(data["mem_percent"]) <= 100  # type: ignore[arg-type]
    assert int(data["mem_used"]) <= int(data["mem_total"])  # type: ignore[call-overload]
    assert len(data["load"]) == 3  # type: ignore[arg-type]
    now = time.time()
    up = collect_uptime(started_at=now - 100, now=now)
    assert up["cat_seconds"] == 100 and int(up["system_seconds"]) > 0  # type: ignore[call-overload]
    assert "CPU" in describe(data, up)


async def test_system_plugin_pushes_live_updates_and_stops() -> None:
    rec = Recorder()
    plugin = SystemPlugin()
    await plugin.start(PluginContext(settings(system_interval_s=0.05), rec))
    await asyncio.sleep(0.25)
    await plugin.stop()
    count = len(rec.updates)
    system = [u for u in rec.updates if u.id == "system"]
    assert len(system) >= 3 and all(u.status == "ok" for u in system)
    assert {"cpu_percent", "mem_percent", "disk_percent"} <= system[-1].data.keys()
    assert {"system_seconds", "cat_seconds"} <= rec.last("uptime").data.keys()
    await asyncio.sleep(0.15)
    assert len(rec.updates) == count  # nach stop() kommt nichts mehr


async def test_system_plugin_reports_unreadable_values_without_crashing() -> None:
    rec = Recorder()
    plugin = SystemPlugin()
    bad = settings(system_interval_s=0.05, disk_path="/gibt/es/nicht/xyz")
    await plugin.start(PluginContext(bad, rec))
    await asyncio.sleep(0.15)
    await plugin.stop()
    assert rec.last("system").status == "error"
    assert rec.last("system").error == "Systemwerte nicht lesbar"


async def test_system_tool_describes_status() -> None:
    plugin = SystemPlugin()
    await plugin.start(PluginContext(settings(system_interval_s=60), Recorder()))
    try:
        text = await plugin.tools()[0].handler({}, tool_ctx())
    finally:
        await plugin.stop()
    assert "Arbeitsspeicher" in text


# --- Wetter ---

FORECAST = {
    "current": {
        "temperature_2m": 12.4,
        "apparent_temperature": 10.1,
        "relative_humidity_2m": 71,
        "weather_code": 2,
        "wind_speed_10m": 14.0,
        "precipitation": 0.0,
    },
    "daily": {
        "time": ["2026-10-16", "2026-10-17"],
        "temperature_2m_max": [14.0, 13.0],
        "temperature_2m_min": [7.0, 6.5],
        "weather_code": [2, 61],
    },
}


class Net:
    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._call))

    def _call(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def ok_net() -> Net:
    return Net(lambda r: httpx.Response(200, json=FORECAST))


def offline_net() -> Net:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Netz", request=request)

    return Net(boom)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


LOCATED = {"weather_lat": 52.5, "weather_lon": 13.4, "weather_name": "Berlin", "weather_ttl_s": 600}


async def started_weather(net: Net, clock: Clock, rec: Recorder, **kw: Any) -> WeatherPlugin:
    plugin = WeatherPlugin(client=net.client, clock=clock)
    await plugin.start(PluginContext(settings(**{**LOCATED, **kw}), rec))
    await asyncio.sleep(0.05)  # erster Abruf im Hintergrund
    return plugin


async def test_weather_fetches_parses_and_sends_expected_query() -> None:
    net, rec = ok_net(), Recorder()
    plugin = await started_weather(net, Clock(), rec)
    await plugin.stop()
    update = rec.last("weather")
    assert update.status == "ok" and update.refreshable
    assert update.data["temperature"] == 12.4 and update.data["label"] == "Teils bewölkt"
    assert update.data["name"] == "Berlin"
    assert [d["label"] for d in update.data["daily"]] == ["Teils bewölkt", "Leichter Regen"]  # type: ignore[union-attr,index]
    query = net.requests[0].url.params
    assert query["latitude"] == "52.5" and query["longitude"] == "13.4"


async def test_weather_uses_cache_within_ttl_and_throttles_refresh() -> None:
    net, clock, rec = ok_net(), Clock(), Recorder()
    plugin = await started_weather(net, clock, rec)
    assert len(net.requests) == 1
    clock.now += 2  # innerhalb der Drossel
    assert await plugin.refresh("weather") is True
    assert len(net.requests) == 1
    clock.now += 10  # Refresh-Knopf nach der Drossel ruft neu ab
    await plugin.refresh("weather")
    assert len(net.requests) == 2
    assert rec.last("weather").status == "ok"
    await plugin.stop()


async def test_weather_offline_shows_clean_error_and_keeps_old_data() -> None:
    online = ok_net()
    clock, rec = Clock(), Recorder()
    plugin = await started_weather(online, clock, rec)
    assert rec.last("weather").status == "ok"
    await plugin.stop()

    offline = offline_net()
    rec2 = Recorder()
    plugin2 = await started_weather(offline, clock, rec2)
    update = rec2.last("weather")
    assert update.status == "error"
    assert update.error == "Wetterdaten nicht erreichbar (kein Internet?)."
    assert update.data == {}
    await plugin2.stop()

    # Erst Daten, dann Ausfall: der letzte gute Stand bleibt sichtbar.
    flaky = Net(lambda r: httpx.Response(200, json=FORECAST))
    rec3 = Recorder()
    plugin3 = await started_weather(flaky, clock, rec3)
    flaky._handler = lambda r: (_ for _ in ()).throw(httpx.ConnectError("weg", request=r))
    clock.now += 700
    await plugin3.refresh("weather")
    stale = rec3.last("weather")
    assert stale.status == "error" and stale.data["temperature"] == 12.4
    await plugin3.stop()


@pytest.mark.parametrize(
    ("handler", "fragment"),
    [
        (lambda r: httpx.Response(500), "abgelehnt"),
        (lambda r: httpx.Response(200, json={"unerwartet": 1}), "Unerwartete Antwort"),
        (lambda r: httpx.Response(200, content=b"<html>"), "nicht erreichbar"),
    ],
)
async def test_weather_bad_responses_become_widget_errors(handler: Any, fragment: str) -> None:
    rec = Recorder()
    plugin = await started_weather(Net(handler), Clock(), rec)
    await plugin.stop()
    assert rec.last("weather").status == "error"
    assert fragment in (rec.last("weather").error or "")


async def test_weather_without_location_makes_no_request() -> None:
    net, rec = ok_net(), Recorder()
    plugin = WeatherPlugin(client=net.client)
    await plugin.start(PluginContext(settings(), rec))
    await asyncio.sleep(0.05)
    await plugin.stop()
    assert net.requests == []
    assert rec.last("weather").error == NO_LOCATION
    with pytest.raises(ToolError, match="Standort"):
        await plugin.tools()[0].handler({}, tool_ctx())


async def test_weather_tool_and_unknown_widget_refresh() -> None:
    net, rec = ok_net(), Recorder()
    plugin = await started_weather(net, Clock(), rec)
    text = await plugin.tools()[0].handler({}, tool_ctx())
    await plugin.stop()
    assert "12.4 °C" in text and "Berlin" in text and "Vorhersage" in text
    assert await plugin.refresh("system") is False


def test_wmo_labels_and_describe() -> None:
    assert (
        wmo_label(95) == "Gewitter"
        and wmo_label(999) == "Unbekannt"
        and wmo_label(None) == "Unbekannt"
    )
    assert "kein" not in describe_weather(
        {"temperature": 1, "apparent": 0, "label": "Klar", "humidity": 50, "wind": 3}
    )


# --- Manager ---


class Crashing(BasePlugin):
    name = "crashing"

    def widgets(self) -> list[WidgetSpec]:
        return [WidgetSpec("crash", "Crash", "x", refreshable=True)]

    async def start(self, ctx: PluginContext) -> None:
        raise RuntimeError("kaputt")


class Healthy(BasePlugin):
    name = "healthy"

    def __init__(self) -> None:
        self.refreshed: list[str] = []
        self.stopped = False

    def widgets(self) -> list[WidgetSpec]:
        return [WidgetSpec("fine", "Fine", "x", refreshable=True), WidgetSpec("fixed", "F", "x")]

    async def start(self, ctx: PluginContext) -> None:
        await ctx.publish(make_update(self.widgets()[0], "ok", {"v": 1}))

    async def stop(self) -> None:
        self.stopped = True

    async def refresh(self, widget_id: str) -> bool:
        self.refreshed.append(widget_id)
        return True

    def tools(self) -> list[Tool]:
        async def handler(_: dict[str, Any], __: ToolContext) -> str:
            return "x"

        return [Tool("healthy_tool", "", {"type": "object"}, handler)]


async def test_manager_isolates_failing_plugin_and_routes_refresh() -> None:
    rec, healthy = Recorder(), Healthy()
    manager = PluginManager([Crashing(), healthy], settings(), rec)
    await manager.start()
    assert rec.last("crash").status == "error"
    assert rec.last("fine").status == "ok"
    assert [t.name for t in manager.tools()] == ["healthy_tool"]

    assert await manager.refresh("fine") is True
    assert healthy.refreshed == ["fine"]
    assert await manager.refresh("fixed") is False  # nicht aktualisierbar
    assert await manager.refresh("crash") is False  # Plugin läuft nicht
    assert await manager.refresh("nope") is False

    await manager.stop()
    assert healthy.stopped


# --- Ende zu Ende über WebSocket ---


def recv(ws: Any) -> dict[str, Any]:
    return json.loads(ws.receive_text())


def test_widgets_arrive_live_over_websocket_without_reload() -> None:
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="system",
        system_interval_s=0.05,
    )
    with TestClient(create_app(cfg)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        with c.websocket_connect("/ws") as ws:
            seen: list[float] = []
            while len(seen) < 3:
                event = recv(ws)
                if event["type"] == "widget.update" and event["id"] == "system":
                    if event["status"] == "ok":
                        seen.append(event["updated_at"])
            assert seen == sorted(seen) and len(set(seen)) == 3


def test_weather_error_and_refresh_over_websocket() -> None:
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="weather",
    )
    with TestClient(create_app(cfg)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        with c.websocket_connect("/ws") as ws:
            replay = drain_replay(ws)
            widget = [e for e in replay if e["type"] == "widget.update"]
            # Der Hintergrundabruf kann noch laufen: dann erst auf das Ergebnis warten.
            first = widget[-1] if widget else {}
            while first.get("status") != "error":
                event = recv(ws)
                if event["type"] == "widget.update":
                    first = event
            assert first["error"] == NO_LOCATION and first["refreshable"] is True
            ws.send_text(json.dumps({"type": "widget.refresh", "id": "weather"}))
            again = recv(ws)
            while again["type"] != "widget.update":
                again = recv(ws)
            assert again["id"] == "weather"
            ws.send_text(json.dumps({"type": "widget.refresh", "id": "system"}))
            assert recv(ws)["type"] == "error"
