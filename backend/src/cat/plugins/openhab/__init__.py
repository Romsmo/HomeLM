"""Plugin "openhab": Items lesen, Befehle senden, Änderungen per SSE (Server-Sent Events).

API-Stand (openHAB 4.2, geprüft gegen den laufenden Server, nur lesend):
- GET  /rest/items/{name}                       Item, Feld "state" ("ON", "75", "12.6 °C", "NULL")
- POST /rest/items/{name}  (text/plain)         Befehl senden, z. B. ON, OFF, UP, 75
- GET  /rest/events?topics=openhab/items/*/statechanged   SSE, "data:" mit JSON; "payload" ist
  ein JSON-Text mit "value". Alle 10 s kommt ein "alive"-Ereignis.
- GET  /rest/items?fields=...    alle Items auf einmal (für die automatische Erkennung)
- API-Token: laut Dokumentation als Benutzername bei HTTP Basic (Passwort leer).

Cat verändert nichts an openHAB selbst: nur GET (lesen) und POST /rest/items/{name} mit einem Befehl
(steuern). Kein Anlegen, Ändern oder Löschen von Items, Things oder Regeln (Test in test_backends).
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import quote

import httpx

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.devices.commands import DeviceError
from cat.devices.discovery import discover_openhab
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.plugins.base import BasePlugin, PluginContext
from cat.plugins.openhab.automations import (
    describe,
    filter_by_query,
    normalize_state,
    parse_rules,
)

log = logging.getLogger("cat.plugins.openhab")

_QUANTITY = re.compile(r"^(-?\d+(?:\.\d+)?)\s+(\S.*)$")
_COLOR = re.compile(r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,(-?\d+(?:\.\d+)?)$")
_NO_STATE = {"NULL", "UNDEF", ""}

# Standardübersetzung kanonischer Befehle. Für Schlösser, Türen und Garagen gibt es bewusst
# keine Vorgabe: Die Allowlist muss sie über command_map ausdrücklich festlegen.
_DEFAULT_COMMANDS = {"on": "ON", "off": "OFF", "up": "UP", "down": "DOWN", "stop": "STOP"}
_NEEDS_MAP = {"lock", "door", "garage"}


def parse_state(value: object) -> RawState:
    """Zerlegt einen openHAB-Zustand in Wert und Einheit."""
    text = "" if value is None else str(value).strip()
    if text.upper() in _NO_STATE:
        return RawState(None)
    color = _COLOR.match(text)
    if color:  # Color-Item: "Farbton,Sättigung,Helligkeit", für Cat zählt die Helligkeit
        return RawState(f"{float(color.group(1)):g}", "%")
    match = _QUANTITY.match(text)
    if match:
        return RawState(match.group(1), match.group(2))
    return RawState(text)


def translate_command(spec: DeviceSpec, command: str) -> str:
    if command in spec.command_map:
        return spec.command_map[command]
    if spec.type in _NEEDS_MAP:
        raise DeviceError(
            f"Für '{spec.name}' ist in devices.yaml kein command_map-Eintrag für '{command}' "
            "hinterlegt. Ohne ihn sende ich keinen Befehl an Schlösser, Türen oder Garagen."
        )
    return _DEFAULT_COMMANDS.get(command, command)


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """Liest "data:"-Zeilen eines SSE-Stroms und gibt die JSON-Objekte zurück."""
    async for line in lines:
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def state_change(event: dict[str, Any]) -> tuple[str, RawState] | None:
    """(Item, neuer Zustand) aus einem ItemStateChangedEvent, sonst None."""
    topic = event.get("topic")
    if event.get("type") != "ItemStateChangedEvent" or not isinstance(topic, str):
        return None
    parts = topic.split("/")
    if len(parts) != 4 or parts[:2] != ["openhab", "items"]:
        return None
    try:
        payload = json.loads(event["payload"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return parts[2], parse_state(payload.get("value"))


class OpenHabPlugin(BasePlugin):
    name = "openhab"

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
        devices.register_backend("openhab", self)

    async def start(self, ctx: PluginContext) -> None:
        if self._client is None:
            token = ctx.settings.openhab_token
            self._client = httpx.AsyncClient(
                base_url=ctx.settings.openhab_url,
                # Kurze Verbindungszeit: Ist openHAB nicht erreichbar, antwortet Cat sofort.
                timeout=httpx.Timeout(5.0, connect=2.0, read=40.0),
                auth=(token.get_secret_value(), "") if token else None,
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
            resp = await self._client.get(
                f"/rest/items/{quote(spec.item, safe='')}", params={"metadata": "none"}
            )
        except httpx.HTTPError as exc:
            raise DeviceError("openHAB ist nicht erreichbar.") from exc
        if resp.status_code == 404:
            raise DeviceError(f"Das Item '{spec.item}' gibt es in openHAB nicht.")
        if resp.status_code in (401, 403):
            raise DeviceError("openHAB verweigert den Zugriff (API-Token prüfen).")
        if resp.status_code != 200:
            raise DeviceError(f"openHAB antwortet mit Fehler {resp.status_code}.")
        try:
            raw = parse_state(resp.json().get("state"))
        except (ValueError, AttributeError) as exc:
            raise DeviceError("Unerwartete Antwort von openHAB.") from exc
        if raw.state is None:  # Zwilling mit Wert fragen
            for twin in spec.twins:
                try:
                    other = await self._client.get(
                        f"/rest/items/{quote(twin, safe='')}", params={"metadata": "none"}
                    )
                    found = (
                        parse_state(other.json().get("state")) if other.status_code == 200 else raw
                    )
                except (httpx.HTTPError, ValueError, AttributeError):
                    continue
                if found.state is not None:
                    return found
        return raw

    async def send(self, spec: DeviceSpec, command: str) -> None:
        assert self._client is not None
        payload = translate_command(spec, command)
        failure: DeviceError | None = None
        sent = 0
        for item in (*spec.twins, spec.item):
            try:
                await self._post(item, payload)
                sent += 1
            except DeviceError as exc:
                failure = exc
        if sent == 0 and failure is not None:
            raise failure

    async def _post(self, item: str, payload: str) -> None:
        assert self._client is not None
        try:
            resp = await self._client.post(
                f"/rest/items/{quote(item, safe='')}",
                content=payload.encode(),
                headers={"Content-Type": "text/plain"},
            )
        except httpx.HTTPError as exc:
            raise DeviceError("openHAB ist nicht erreichbar, nichts gesendet.") from exc
        if resp.status_code == 404:
            raise DeviceError(f"Das Item '{item}' gibt es in openHAB nicht.")
        if resp.status_code in (401, 403):
            raise DeviceError("openHAB verweigert den Zugriff (API-Token prüfen).")
        if resp.status_code >= 400:
            raise DeviceError(f"openHAB hat den Befehl abgelehnt (Fehler {resp.status_code}).")

    async def rules(self) -> list[Any]:
        """Alle Regeln (nur lesen)."""
        assert self._client is not None
        try:
            resp = await self._client.get("/rest/rules", params={"summary": "true"})
        except httpx.HTTPError as exc:
            raise ToolError("openHAB ist nicht erreichbar.") from exc
        if resp.status_code != 200:
            raise ToolError(f"openHAB liefert die Automationen nicht (Fehler {resp.status_code}).")
        try:
            return list(resp.json())
        except (ValueError, TypeError) as exc:
            raise ToolError("Unerwartete Antwort von openHAB.") from exc

    def tools(self) -> list[Tool]:
        async def list_automations(args: dict[str, Any], ctx: ToolContext) -> str:
            query = args.get("query")
            query = query.strip() if isinstance(query, str) else ""
            state = normalize_state(args.get("state"))
            items = filter_by_query(parse_rules(await self.rules()), query)
            text = describe(items, state, query)
            ctx.final_replies.append(text)
            return text

        return [
            Tool(
                name="list_automations",
                description=(
                    "Listet die Automationen (openHAB-Regeln) mit Status aktiv oder deaktiviert. "
                    "Nur lesen."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Stichwort (optional)."},
                        "state": {
                            "type": "string",
                            "enum": ["aktiv", "aus"],
                            "description": "Nur aktive oder nur deaktivierte (optional).",
                        },
                    },
                },
                handler=list_automations,
            )
        ]

    async def discover(self) -> int:
        """Liest alle Items auf einmal und macht daraus Geräte (devices/discovery.py).
        Ohne `discover: openhab: enabled: true` in devices.yaml passiert nichts."""
        config = self._devices.discover_config("openhab")
        if config is None:
            return 0
        assert self._client is not None
        try:
            resp = await self._client.get(
                "/rest/items",
                params={
                    "recursive": "false",
                    "metadata": "none",
                    "fields": "name,label,type,tags,groupNames,category,state",
                },
            )
        except httpx.HTTPError as exc:
            raise DeviceError("openHAB ist nicht erreichbar.") from exc
        if resp.status_code in (401, 403):
            raise DeviceError("openHAB verweigert den Zugriff (API-Token prüfen).")
        if resp.status_code != 200:
            raise DeviceError(f"openHAB antwortet mit Fehler {resp.status_code}.")
        try:
            items = resp.json()
        except ValueError as exc:
            raise DeviceError("Unerwartete Antwort von openHAB.") from exc
        if not isinstance(items, list):
            raise DeviceError("Unerwartete Antwort von openHAB.")
        found = discover_openhab(items, config, self._devices.explicit_items("openhab"))
        self._devices.set_discovered([d.spec for d in found])
        self._devices.seed_states(
            "openhab",
            {str(i["name"]): parse_state(i.get("state")) for i in items if "name" in i},
        )
        log.info("openHAB: %d Geräte erkannt (%d Items)", len(found), len(items))
        return len(found)

    # --- Hintergrund: Zustände und Änderungen ---

    async def _run(self) -> None:
        attempt = 0

        def connected() -> None:
            nonlocal attempt
            attempt = 0

        while True:
            try:
                await self.discover()
                await self._devices.refresh_all("openhab", skip_known=True)
                await self.listen_once(on_connected=connected)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("openHAB-Verbindung unterbrochen: %s", type(exc).__name__)
                # Nur bei einem Fehler gelten die Geräte als offline; ein sauber beendeter
                # Ereignisstrom führt nur zu einer neuen Verbindung.
                await self._devices.set_offline("openhab")
            await asyncio.sleep(self._backoff(attempt))
            attempt = min(attempt + 1, 10)

    async def listen_once(self, on_connected: Callable[[], None] | None = None) -> None:
        """Hält eine SSE-Verbindung, bis sie endet oder fehlschlägt."""
        assert self._client is not None
        if not self._devices.specs_for("openhab"):
            await asyncio.sleep(3600)  # keine Geräte freigegeben: nichts zu beobachten
            return
        config = self._devices.discover_config("openhab")
        last_discovery = time.monotonic()
        async with self._client.stream(
            "GET", "/rest/events", params={"topics": "openhab/items/*/statechanged"}
        ) as resp:
            if resp.status_code != 200:
                raise DeviceError(f"openHAB-Ereignisstrom: Fehler {resp.status_code}")
            if on_connected:
                on_connected()
            async for event in iter_sse(resp.aiter_lines()):
                change = state_change(event)
                if change and self._devices.has_item("openhab", change[0]):
                    await self._devices.on_state_change("openhab", change[0], change[1])
                # Neue oder entfernte Items in openHAB: Erkennung regelmäßig wiederholen (der
                # "alive"-Takt des Ereignisstroms dient als Uhr).
                if config and time.monotonic() - last_discovery > config.refresh_s:
                    last_discovery = time.monotonic()
                    await self.discover()
