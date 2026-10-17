import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from websockets.asyncio.server import serve

from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import parse_allowlist
from cat.devices.commands import DeviceError
from cat.devices.confirm import ConfirmManager
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.plugins.base import PluginContext
from cat.plugins.homeassistant import HomeAssistantPlugin, parse_entity, service_call
from cat.plugins.openhab import (
    OpenHabPlugin,
    iter_sse,
    parse_state,
    state_change,
    translate_command,
)
from cat.ws.protocol import ServerEvent

YAML = """
devices:
  - {id: licht, backend: openhab, item: Licht, name: Licht, room: Wohnzimmer, type: light}
  - {id: temp, backend: openhab, item: Temp, name: Temperatur, room: Wohnzimmer, type: sensor}
  - {id: tuer, backend: openhab, item: Tuer, name: Haustür, room: Flur, type: lock}
  - {id: tuer2, backend: openhab, item: Tuer2, name: Hintertür, room: Flur, type: lock, command_map: {unlock: "OFF", lock: "ON"}}
  - {id: ha_licht, backend: homeassistant, item: light.kueche, name: Küchenlicht, room: Küche, type: dimmer}
  - {id: ha_rollo, backend: homeassistant, item: cover.wz, name: Rollo, room: Wohnzimmer, type: shutter}
  - {id: ha_heiz, backend: homeassistant, item: climate.wz, name: Heizung, room: Wohnzimmer, type: thermostat}
  - {id: ha_schloss, backend: homeassistant, item: lock.haustuer, name: Schloss, room: Flur, type: lock}
  - {id: ha_garage, backend: homeassistant, item: cover.garage, name: Garage, room: Garage, type: garage}
  - {id: ha_sw, backend: homeassistant, item: switch.pumpe, name: Pumpe, room: Keller, type: switch}
"""


def spec(device_id: str) -> DeviceSpec:
    found = parse_allowlist(YAML).by_id(device_id)
    assert found is not None
    return found


def make_service(tmp_path: Path) -> tuple[DeviceService, list[ServerEvent]]:
    events: list[ServerEvent] = []

    async def emit(event: ServerEvent) -> None:
        events.append(event)

    confirm = ConfirmManager(emit, lambda: True, timeout_s=0.2)
    service = DeviceService(
        parse_allowlist(YAML), "full", emit, AuditLog(tmp_path / "a.jsonl"), confirm
    )
    service.settle_delay = 0
    return service, events


# --- openHAB: reine Funktionen ---


@pytest.mark.parametrize(
    ("raw", "state", "unit"),
    [
        ("ON", "ON", None),
        ("75", "75", None),
        ("12.64 °C", "12.64", "°C"),
        ("-3.5 °C", "-3.5", "°C"),
        ("352.1 W", "352.1", "W"),
        ("35.011,65.00,40", "40", "%"),
        ("0,0,0", "0", "%"),
        ("NULL", None, None),
        ("UNDEF", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_parse_state(raw: object, state: str | None, unit: str | None) -> None:
    assert parse_state(raw) == RawState(state, unit)


def test_translate_command_defaults_and_required_map() -> None:
    assert translate_command(spec("licht"), "on") == "ON"
    assert translate_command(spec("licht"), "75") == "75"
    assert translate_command(spec("tuer2"), "unlock") == "OFF"
    with pytest.raises(DeviceError, match="command_map"):
        translate_command(spec("tuer"), "unlock")


async def test_sse_parsing_and_state_change() -> None:
    sample = {
        "topic": "openhab/items/Temp/statechanged",
        "payload": json.dumps({"type": "Quantity", "value": "21.5 °C", "oldValue": "21 °C"}),
        "type": "ItemStateChangedEvent",
    }

    async def lines() -> AsyncIterator[str]:
        for line in [
            "event: message",
            f"data: {json.dumps(sample)}",
            "",
            "data: kein json",
            'data: {"type":"ALIVE","interval":10}',
            'data: ["liste"]',
        ]:
            yield line

    events = [e async for e in iter_sse(lines())]
    assert len(events) == 2
    assert state_change(events[0]) == ("Temp", RawState("21.5", "°C"))
    assert state_change(events[1]) is None
    assert state_change({"type": "ItemStateChangedEvent", "topic": "openhab/things/x/y"}) is None
    assert (
        state_change({"type": "ItemStateChangedEvent", "topic": "openhab/items/A/statechanged"})
        is None
    )


# --- openHAB: Plugin mit gemocktem HTTP ---


class OhServer:
    def __init__(self, sse_body: str = "") -> None:
        self.requests: list[httpx.Request] = []
        self.items = {"Licht": "OFF", "Temp": "21.5 °C", "Tuer2": "ON"}
        self.status_override: int | None = None
        self.sse_body = sse_body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_override:
            return httpx.Response(self.status_override)
        path = request.url.path
        if path == "/rest/events":
            return httpx.Response(200, content=self.sse_body.encode())
        name = path.rsplit("/", 1)[-1]
        if name not in self.items:
            return httpx.Response(404)
        if request.method == "POST":
            self.items[name] = request.content.decode()
            return httpx.Response(200)
        return httpx.Response(200, json={"name": name, "state": self.items[name]})


def oh_plugin(tmp_path: Path, server: OhServer) -> tuple[OpenHabPlugin, DeviceService]:
    service, _ = make_service(tmp_path)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(server.handler), base_url="http://oh.test"
    )
    return OpenHabPlugin(service, client=client, backoff_s=lambda _: 0.01), service


async def test_openhab_read_and_send(tmp_path: Path) -> None:
    server = OhServer()
    plugin, service = oh_plugin(tmp_path, server)
    assert await plugin.read(spec("temp")) == RawState("21.5", "°C")
    out = await service.command("licht", "on")
    assert "gesendet" in out and "ON" in out
    post = next(r for r in server.requests if r.method == "POST")
    assert post.url.path == "/rest/items/Licht"
    assert post.content == b"ON" and post.headers["content-type"] == "text/plain"


async def test_openhab_errors_become_device_errors(tmp_path: Path) -> None:
    server = OhServer()
    plugin, service = oh_plugin(tmp_path, server)
    missing = DeviceSpec.model_validate(
        {
            "id": "x",
            "backend": "openhab",
            "item": "Gibtsnicht",
            "name": "X",
            "room": "R",
            "type": "light",
        }
    )
    with pytest.raises(DeviceError, match="gibt es in openHAB nicht"):
        await plugin.read(missing)
    server.status_override = 401
    with pytest.raises(DeviceError, match="verweigert"):
        await plugin.read(spec("licht"))
    server.status_override = 500
    with pytest.raises(DeviceError, match="Fehler 500"):
        await plugin.send(spec("licht"), "on")


async def test_openhab_unreachable_sends_nothing(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("weg", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://oh.test")
    plugin = OpenHabPlugin(service, client=client)
    with pytest.raises(DeviceError, match="nicht erreichbar"):
        await plugin.send(spec("licht"), "on")
    with pytest.raises(DeviceError, match="nicht erreichbar"):
        await plugin.read(spec("licht"))


async def test_openhab_lock_without_command_map_never_sends(tmp_path: Path) -> None:
    server = OhServer()
    plugin, service = oh_plugin(tmp_path, server)
    task = asyncio.create_task(service.command("tuer", "unlock"))
    # Bestätigung kommt nie (Test-Confirm läuft in den Timeout); der Befehl darf nie raus.
    with pytest.raises(DeviceError):
        await task
    assert not [r for r in server.requests if r.method == "POST"]
    assert plugin is not None


async def test_openhab_listen_once_updates_only_allowlisted_items(tmp_path: Path) -> None:
    def event(item: str, value: str) -> str:
        data = {
            "topic": f"openhab/items/{item}/statechanged",
            "payload": json.dumps({"type": "Quantity", "value": value}),
            "type": "ItemStateChangedEvent",
        }
        return f"event: message\ndata: {json.dumps(data)}\n\n"

    body = event("Temp", "23 °C") + event("Fremd", "1") + event("Licht", "ON")
    server = OhServer(sse_body=body)
    plugin, service = oh_plugin(tmp_path, server)
    connected: list[bool] = []
    await plugin.listen_once(on_connected=lambda: connected.append(True))
    states = {i.id: i.state for i in service.snapshot()}
    assert connected == [True]
    assert states["temp"] == "23" and states["licht"] == "ON"
    request = server.requests[-1]
    assert request.url.params["topics"] == "openhab/items/*/statechanged"


async def test_openhab_plugin_marks_offline_and_recovers(tmp_path: Path) -> None:
    server = OhServer(sse_body="")
    plugin, service = oh_plugin(tmp_path, server)
    settings = Settings(_env_file=None, static_dir=None)  # type: ignore[call-arg]

    async def publish(_: object) -> None: ...

    await plugin.start(PluginContext(settings, publish))
    await asyncio.sleep(0.15)
    initial = {i.id: i.state for i in service.snapshot()}
    assert initial["temp"] == "21.5"  # Lesen beim Start
    server.status_override = 503  # openHAB fällt aus
    await asyncio.sleep(0.15)
    assert all(not i.online for i in service.snapshot() if i.id in ("licht", "temp", "tuer"))
    server.status_override = None  # und kommt zurück
    await asyncio.sleep(0.2)
    assert next(i for i in service.snapshot() if i.id == "temp").online
    await plugin.stop()


async def test_openhab_token_is_sent_as_basic_auth_user(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    seen: list[str] = []

    async def publish(_: object) -> None: ...

    plugin = OpenHabPlugin(service)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        static_dir=None,
        openhab_url="http://127.0.0.1:9",
        openhab_token=SecretStr("oh.tok"),
    )
    await plugin.start(PluginContext(settings, publish))
    assert plugin._client is not None and plugin._client.auth is not None
    seen.append(str(plugin._client.auth._auth_header))  # type: ignore[attr-defined]
    await plugin.stop()
    import base64

    assert base64.b64decode(seen[0].split()[1]) == b"oh.tok:"


# --- Home Assistant: reine Funktionen ---


@pytest.mark.parametrize(
    ("device", "command", "expected"),
    [
        ("ha_sw", "on", ("switch", "turn_on", {"entity_id": "switch.pumpe"})),
        ("ha_licht", "off", ("light", "turn_off", {"entity_id": "light.kueche"})),
        (
            "ha_licht",
            "40",
            ("light", "turn_on", {"entity_id": "light.kueche", "brightness_pct": 40}),
        ),
        ("ha_licht", "0", ("light", "turn_off", {"entity_id": "light.kueche"})),
        ("ha_rollo", "up", ("cover", "open_cover", {"entity_id": "cover.wz"})),
        ("ha_rollo", "stop", ("cover", "stop_cover", {"entity_id": "cover.wz"})),
        (
            "ha_rollo",
            "30",
            ("cover", "set_cover_position", {"entity_id": "cover.wz", "position": 70}),
        ),
        (
            "ha_heiz",
            "21.5",
            ("climate", "set_temperature", {"entity_id": "climate.wz", "temperature": 21.5}),
        ),
        ("ha_schloss", "unlock", ("lock", "unlock", {"entity_id": "lock.haustuer"})),
        ("ha_garage", "open", ("cover", "open_cover", {"entity_id": "cover.garage"})),
        ("ha_garage", "close", ("cover", "close_cover", {"entity_id": "cover.garage"})),
    ],
)
def test_ha_service_call_mapping(
    device: str, command: str, expected: tuple[str, str, dict[str, Any]]
) -> None:
    assert service_call(spec(device), command) == expected


def test_ha_thermostat_needs_number() -> None:
    with pytest.raises(DeviceError):
        service_call(spec("ha_heiz"), "on")


@pytest.mark.parametrize(
    ("device_type", "data", "state", "unit"),
    [
        ("switch", {"state": "on"}, "ON", None),
        ("dimmer", {"state": "on", "attributes": {"brightness": 128}}, "50", "%"),
        ("dimmer", {"state": "off"}, "0", "%"),
        ("shutter", {"state": "open", "attributes": {"current_position": 70}}, "30", "%"),
        ("thermostat", {"state": "heat", "attributes": {"temperature": 21.5}}, "21.5", "°C"),
        ("sensor", {"state": "22.4", "attributes": {"unit_of_measurement": "°C"}}, "22.4", "°C"),
        ("lock", {"state": "locked"}, "locked", None),
        ("switch", {"state": "unavailable"}, None, None),
    ],
)
def test_ha_parse_entity(
    device_type: str, data: dict[str, Any], state: str | None, unit: str | None
) -> None:
    assert parse_entity(device_type, data) == RawState(state, unit)


# --- Home Assistant: Plugin mit gemocktem HTTP ---


def ha_plugin(tmp_path: Path, handler: Any) -> tuple[HomeAssistantPlugin, DeviceService]:
    service, _ = make_service(tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ha.test")
    return HomeAssistantPlugin(service, client=client), service


async def test_ha_rest_read_and_send(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"state": "on", "attributes": {"brightness": 255}})
        return httpx.Response(200, json=[])

    plugin, service = ha_plugin(tmp_path, handler)
    assert await plugin.read(spec("ha_licht")) == RawState("100", "%")
    await service.command("ha_licht", "40")
    post = next(c for c in calls if c.method == "POST")
    assert post.url.path == "/api/services/light/turn_on"
    assert json.loads(post.content) == {"entity_id": "light.kueche", "brightness_pct": 40}


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(404, "gibt es in Home Assistant nicht"), (401, "verweigert"), (500, "Fehler 500")],
)
async def test_ha_errors(tmp_path: Path, status: int, fragment: str) -> None:
    plugin, _ = ha_plugin(tmp_path, lambda r: httpx.Response(status))
    with pytest.raises(DeviceError, match=fragment):
        await plugin.read(spec("ha_licht"))
    with pytest.raises(DeviceError, match=fragment):
        await plugin.send(spec("ha_licht"), "on")


async def test_ha_websocket_auth_subscribe_and_updates(tmp_path: Path) -> None:
    received: list[dict[str, Any]] = []

    async def handler(ws: Any) -> None:
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "test"}))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "auth_ok"}))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"id": 1, "type": "result", "success": True}))
        for entity, state in (
            ("light.kueche", "off"),
            ("light.fremd", "on"),
            ("switch.pumpe", "on"),
        ):
            event = {
                "id": 1,
                "type": "event",
                "event": {
                    "event_type": "state_changed",
                    "data": {"entity_id": entity, "new_state": {"state": state, "attributes": {}}},
                },
            }
            await ws.send(json.dumps(event))
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        service, _ = make_service(tmp_path)
        plugin = HomeAssistantPlugin(service)
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            static_dir=None,
            ha_url=f"http://127.0.0.1:{port}",
            ha_token=SecretStr("langzeit"),
        )

        async def publish(_: object) -> None: ...

        plugin._url = settings.ha_url
        plugin._token = "langzeit"
        await plugin.listen_once()
        assert received[0] == {"type": "auth", "access_token": "langzeit"}
        assert received[1] == {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
        states = {i.id: i.state for i in service.snapshot()}
        assert states["ha_licht"] == "0" and states["ha_sw"] == "ON"
        assert plugin is not None and settings is not None and publish is not None


async def test_ha_websocket_rejects_bad_token(tmp_path: Path) -> None:
    async def handler(ws: Any) -> None:
        await ws.send(json.dumps({"type": "auth_required"}))
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_invalid", "message": "nein"}))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        service, _ = make_service(tmp_path)
        plugin = HomeAssistantPlugin(service)
        plugin._url = f"http://127.0.0.1:{port}"
        plugin._token = "falsch"
        with pytest.raises(DeviceError, match="Token abgelehnt"):
            await plugin.listen_once()
