"""Plugin "weather": Open-Meteo (ohne API-Schlüssel), Standort per Konfiguration, mit Cache."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.plugins.base import BasePlugin, PluginContext, WidgetSpec, make_update
from cat.plugins.weather.wmo import wmo_label

log = logging.getLogger("cat.plugins.weather")

WEATHER = WidgetSpec("weather", "Wetter", "weather", refreshable=True)
API_URL = "https://api.open-meteo.com/v1/forecast"
# Zwischen zwei erzwungenen Abrufen (Refresh-Knopf) mindestens so viele Sekunden.
MIN_REFRESH_GAP_S = 5.0
NO_LOCATION = "Kein Standort konfiguriert (CAT_WEATHER_LAT und CAT_WEATHER_LON in der .env)."


class WeatherUnavailable(Exception):
    """Abruf fehlgeschlagen; die Meldung darf im Widget stehen."""


def parse_forecast(payload: dict[str, Any], name: str) -> dict[str, object]:
    """Wandelt die Open-Meteo-Antwort in die Widget-Daten um."""
    try:
        cur = payload["current"]
        daily = payload["daily"]
        days = [
            {
                "date": daily["time"][i],
                "tmax": daily["temperature_2m_max"][i],
                "tmin": daily["temperature_2m_min"][i],
                "label": wmo_label(daily["weather_code"][i]),
            }
            for i in range(len(daily["time"]))
        ]
        return {
            "name": name,
            "temperature": cur["temperature_2m"],
            "apparent": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"],
            "wind": cur["wind_speed_10m"],
            "precipitation": cur["precipitation"],
            "label": wmo_label(cur["weather_code"]),
            "daily": days,
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise WeatherUnavailable("Unerwartete Antwort des Wetterdienstes.") from exc


def describe(data: dict[str, object]) -> str:
    place = f" in {data['name']}" if data.get("name") else ""
    text = (
        f"Aktuell{place}: {data['temperature']} °C (gefühlt {data['apparent']} °C), "
        f"{str(data['label']).lower()}, Luftfeuchte {data['humidity']} %, "
        f"Wind {data['wind']} km/h."
    )
    days = data.get("daily")
    if isinstance(days, list) and days:
        parts = [f"{d['date']}: {d['tmin']} bis {d['tmax']} °C, {d['label']}" for d in days]
        text += " Vorhersage: " + "; ".join(parts) + "."
    return text


class WeatherPlugin(BasePlugin):
    name = "weather"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._clock = clock
        self._ctx: PluginContext | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_data: dict[str, object] | None = None
        self._last_fetch = -1e9
        self._last_attempt = -1e9
        self._last_error: str | None = None

    def widgets(self) -> list[WidgetSpec]:
        return [WEATHER]

    async def start(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._client and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def refresh(self, widget_id: str) -> bool:
        if widget_id != WEATHER.id:
            return False
        await self._update(force=True)
        return True

    async def _loop(self) -> None:
        assert self._ctx is not None
        ttl = self._ctx.settings.weather_ttl_s
        while True:
            await self._update(force=False)
            await asyncio.sleep(ttl)

    async def _update(self, force: bool) -> None:
        assert self._ctx is not None
        async with self._lock:
            now = self._clock()
            ttl = self._ctx.settings.weather_ttl_s
            fresh = self._last_data is not None and now - self._last_fetch < ttl
            # Cache: nicht neu abrufen, solange die Daten gültig sind. Ein erzwungener Abruf
            # (Refresh-Knopf) wird gedrosselt, damit Klick-Serien den Dienst nicht belasten.
            if (force and now - self._last_attempt < MIN_REFRESH_GAP_S) or (not force and fresh):
                await self._publish_current()
                return
            self._last_attempt = now
            try:
                data = await self._fetch()
            except WeatherUnavailable as exc:
                self._last_error = str(exc)
                await self._publish_current()
                return
            self._last_data = data
            self._last_fetch = now
            self._last_error = None
            await self._publish_current()

    async def _publish_current(self) -> None:
        assert self._ctx is not None
        if self._last_error is not None:
            # Letzten guten Stand mitliefern, damit das Widget nicht leer wird.
            update = make_update(WEATHER, "error", self._last_data, error=self._last_error)
        else:
            update = make_update(WEATHER, "ok", self._last_data)
        await self._ctx.publish(update)

    async def _fetch(self) -> dict[str, object]:
        assert self._ctx is not None and self._client is not None
        s = self._ctx.settings
        if s.weather_lat is None or s.weather_lon is None:
            raise WeatherUnavailable(NO_LOCATION)
        params = {
            "latitude": s.weather_lat,
            "longitude": s.weather_lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 3,
            "timezone": "auto",
            "wind_speed_unit": "kmh",
        }
        try:
            resp = await self._client.get(API_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPStatusError as exc:
            log.warning("Open-Meteo antwortete mit %s", exc.response.status_code)
            raise WeatherUnavailable("Der Wetterdienst hat die Anfrage abgelehnt.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Wetterabruf fehlgeschlagen: %s", type(exc).__name__)
            raise WeatherUnavailable("Wetterdaten nicht erreichbar (kein Internet?).") from exc
        return parse_forecast(payload, s.weather_name)

    def tools(self) -> list[Tool]:
        async def get_weather(_: dict[str, Any], __: ToolContext) -> str:
            if self._ctx is None:
                raise ToolError("Das Wetter-Plugin läuft nicht.")
            await self._update(force=False)
            if self._last_data is None:
                raise ToolError(
                    NO_LOCATION
                    if self._ctx.settings.weather_lat is None
                    else "Wetterdaten sind gerade nicht erreichbar."
                )
            return describe(self._last_data)

        return [
            Tool(
                name="get_weather",
                description="Liest aktuelles Wetter und 3-Tage-Vorhersage am Standort des Hauses.",
                parameters={"type": "object", "properties": {}},
                handler=get_weather,
            )
        ]
