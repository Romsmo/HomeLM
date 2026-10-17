"""Plugin "homeassistant": REST (Zustand lesen, Dienste aufrufen) und WebSocket (Änderungen).

Stand der API laut Dokumentation (contributors.home-assistant.io, "REST API" und
"WebSocket API"):
- Header ``Authorization: Bearer <Langzeit-Token>``
- GET  /api/states/<entity_id>              -> {"state": "on", "attributes": {...}}
- POST /api/services/<domain>/<service>     -> JSON mit entity_id und Parametern
- WS   /api/websocket: auth_required -> {"type": "auth", "access_token"} -> auth_ok, dann
       {"id": n, "type": "subscribe_events", "event_type": "state_changed"}; Ereignisse
       ``event.data.entity_id`` und ``event.data.new_state``.

Es gibt derzeit keinen Home Assistant im Haus. Das Plugin ist gegen Mocks getestet und nur
aktiv, wenn "homeassistant" in CAT_PLUGINS steht.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx
from websockets.asyncio.client import connect

from cat.devices.commands import DeviceError
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.plugins.base import BasePlugin, PluginContext

log = logging.getLogger("cat.plugins.homeassistant")

_UNKNOWN = {"unknown", "unavailable", ""}


def parse_entity(spec_type: str, data: dict[str, Any]) -> RawState:
    """Wandelt ein HA-Zustandsobjekt in Wert und Einheit um (Prozent für Dimmer und Rollläden)."""
    state = str(data.get("state", "")).lower()
    attrs = data.get("attributes") or {}
    if state in _UNKNOWN:
        return RawState(None)
    if spec_type == "dimmer":
        if state == "off":
            return RawState("0", "%")
        brightness = attrs.get("brightness")
        if isinstance(brightness, int | float):
            return RawState(str(round(brightness / 255 * 100)), "%")
        return RawState("100", "%")
    if spec_type == "shutter":
        position = attrs.get("current_position")
        if isinstance(position, int | float):
            # HA: 100 = offen. Cat meldet wie openHAB "Prozent geschlossen".
            return RawState(str(round(100 - position)), "%")
        return RawState(state)
    if spec_type == "thermostat":
        target = attrs.get("temperature")
        if isinstance(target, int | float):
            return RawState(f"{target:g}", "°C")
        return RawState(state)
    if state in ("on", "off"):
        return RawState(state.upper())
    unit = attrs.get("unit_of_measurement")
    return RawState(state, unit if isinstance(unit, str) else None)


def service_call(spec: DeviceSpec, command: str) -> tuple[str, str, dict[str, Any]]:
    """(Domäne, Dienst, Daten) für einen kanonischen Befehl."""
    entity = spec.item
    domain = entity.split(".", 1)[0]
    data: dict[str, Any] = {"entity_id": entity}
    number = _as_number(command)
    match spec.type:
        case "light" | "switch":
            return domain, f"turn_{command}", data
        case "dimmer":
            if number is not None:
                if number == 0:
                    return domain, "turn_off", data
                return domain, "turn_on", {**data, "brightness_pct": number}
            return domain, f"turn_{command}", data
        case "shutter" | "door" | "garage":
            if number is not None:
                # Cat: Prozent geschlossen, HA: Prozent offen.
                return "cover", "set_cover_position", {**data, "position": 100 - number}
            names = {"up": "open_cover", "open": "open_cover", "down": "close_cover"}
            names |= {"close": "close_cover", "stop": "stop_cover"}
            return "cover", names[command], data
        case "thermostat":
            if number is None:
                raise DeviceError("Thermostate brauchen eine Zieltemperatur als Zahl.")
            return "climate", "set_temperature", {**data, "temperature": number}
        case "lock":
            return "lock", command, data
    raise DeviceError(f"Der Gerätetyp '{spec.type}' wird von Home Assistant nicht unterstützt.")


def _as_number(command: str) -> float | None:
    try:
        value = float(command)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


class HomeAssistantPlugin(BasePlugin):
    name = "homeassistant"

    def __init__(
        self,
        devices: DeviceService,
        client: httpx.AsyncClient | None = None,
        backoff_s: Callable[[int], float] = lambda n: min(2.0 * 2**n, 30.0),
    ) -> None:
        self._devices = devices
        self._client = client
        self._owns_client = client is None
        self._backoff = backoff_s
        self._task: asyncio.Task[None] | None = None
        self._url = ""
        self._token = ""
        devices.register_backend("homeassistant", self)

    async def start(self, ctx: PluginContext) -> None:
        self._url = ctx.settings.ha_url.rstrip("/")
        self._token = ctx.settings.ha_token.get_secret_value() if ctx.settings.ha_token else ""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._url,
                timeout=10.0,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._client and self._owns_client:
            await self._client.aclose()
            self._client = None

    # --- DeviceBackend ---

    async def read(self, spec: DeviceSpec) -> RawState:
        assert self._client is not None
        try:
            resp = await self._client.get(f"/api/states/{quote(spec.item, safe='.')}")
        except httpx.HTTPError as exc:
            raise DeviceError("Home Assistant ist nicht erreichbar.") from exc
        _check(resp, spec)
        try:
            return parse_entity(spec.type, resp.json())
        except (ValueError, AttributeError) as exc:
            raise DeviceError("Unerwartete Antwort von Home Assistant.") from exc

    async def send(self, spec: DeviceSpec, command: str) -> None:
        assert self._client is not None
        domain, service, data = service_call(spec, command)
        try:
            resp = await self._client.post(f"/api/services/{domain}/{service}", json=data)
        except httpx.HTTPError as exc:
            raise DeviceError("Home Assistant ist nicht erreichbar, nichts gesendet.") from exc
        _check(resp, spec)

    # --- Hintergrund: Änderungen per WebSocket ---

    async def _run(self) -> None:
        attempt = 0

        def connected() -> None:
            nonlocal attempt
            attempt = 0

        while True:
            try:
                await self._devices.refresh_all("homeassistant")
                await self.listen_once(on_connected=connected)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Home-Assistant-Verbindung unterbrochen: %s", type(exc).__name__)
                # Nur bei einem Fehler gelten die Geräte als offline; ein sauber beendeter
                # Ereignisstrom führt nur zu einer neuen Verbindung.
                await self._devices.set_offline("homeassistant")
            await asyncio.sleep(self._backoff(attempt))
            attempt = min(attempt + 1, 10)

    async def listen_once(self, on_connected: Callable[[], None] | None = None) -> None:
        wanted = {s.item: s for s in self._devices.specs_for("homeassistant")}
        if not wanted:
            await asyncio.sleep(3600)
            return
        ws_url = self._url.replace("http", "ws", 1) + "/api/websocket"
        async with connect(ws_url, open_timeout=10, ping_interval=20) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                raise DeviceError("Unerwartete Begrüßung von Home Assistant.")
            await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            reply = json.loads(await ws.recv())
            if reply.get("type") != "auth_ok":
                raise DeviceError("Home Assistant hat das Token abgelehnt.")
            await ws.send(
                json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
            )
            if on_connected:
                on_connected()
            async for message in ws:
                data = json.loads(message)
                if data.get("type") != "event":
                    continue
                payload = (data.get("event") or {}).get("data") or {}
                spec = wanted.get(payload.get("entity_id"))
                new_state = payload.get("new_state")
                if spec and isinstance(new_state, dict):
                    await self._devices.on_state_change(
                        "homeassistant", spec.item, parse_entity(spec.type, new_state)
                    )


def _check(resp: httpx.Response, spec: DeviceSpec) -> None:
    if resp.status_code == 404:
        raise DeviceError(f"Die Entität '{spec.item}' gibt es in Home Assistant nicht.")
    if resp.status_code in (401, 403):
        raise DeviceError("Home Assistant verweigert den Zugriff (Token prüfen).")
    if resp.status_code >= 400:
        raise DeviceError(f"Home Assistant meldet Fehler {resp.status_code}.")
