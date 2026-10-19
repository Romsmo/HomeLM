"""Werkzeuge für das Modell: list_devices, get_state, set_state, show_devices."""

from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.devices.commands import DeviceError
from cat.devices.models import DeviceInfo
from cat.devices.service import DeviceService
from cat.intents.replies import confirm_text, state_line
from cat.intents.text import tokenize
from cat.ws.protocol import StageShow

LIST_LIMIT = 25
FULL_ROWS = 6  # bis dahin die vollständige Zeile (mit id), darüber kurz

_TYPE_DE = {
    "light": "Licht",
    "switch": "Schalter",
    "dimmer": "Dimmer",
    "shutter": "Rollladen",
    "thermostat": "Thermostat",
    "sensor": "Sensor",
    "lock": "Schloss",
    "door": "Tür",
    "garage": "Garage",
}


_STATE_WORDS = {
    "an": "an", "ein": "an", "on": "an", "eingeschaltet": "an",
    "aus": "aus", "off": "aus", "ausgeschaltet": "aus",
    "offen": "offen", "auf": "offen", "open": "offen", "oben": "offen",
    "zu": "zu", "geschlossen": "zu", "closed": "zu", "unten": "zu",
}  # fmt: skip
# Wortanfänge für Rollläden, Rollos, Jalousien und Markisen: Fragt der Nutzer nur danach, kommen
# alle Geräte dieses Typs (Markisen heißen nicht "Rollo").
_SHUTTER_STEMS = frozenset({"rollo", "rolla", "rolll", "jalou", "marki"})
_STATE_TITLE = {"an": "An", "aus": "Aus", "offen": "Offen", "zu": "Zu"}


def _has_state(info: DeviceInfo, wanted: str) -> bool:
    """Passt der Zustand zu "an", "aus", "offen" oder "zu"? (Rollladen: 0 = offen, 100 = zu.)"""
    if not info.online or info.state is None:
        return False
    raw = info.state.upper()
    number = float(raw) if raw.replace(".", "", 1).isdigit() else None
    if info.type == "shutter" and number is not None:
        return number <= 0 if wanted == "offen" else number >= 100 and wanted == "zu"
    if info.type == "dimmer" and number is not None:
        return number > 0 if wanted == "an" else number <= 0 and wanted == "aus"
    return raw == {"an": "ON", "aus": "OFF", "offen": "OPEN", "zu": "CLOSED"}[wanted]


def _short_state(info: DeviceInfo) -> str:
    if not info.online:
        return "offline"
    if info.state is None:
        return "unbekannt"
    if info.type == "shutter" and info.state.replace(".", "", 1).isdigit():
        pos = float(info.state)
        return "offen" if pos <= 0 else "zu" if pos >= 100 else f"{info.state} % zu"
    return f"{info.state} {info.unit}".strip() if info.unit else info.state


def format_device(info: DeviceInfo) -> str:
    if not info.online:
        state = "offline"
    elif info.state is None:
        state = "unbekannt (kein Wert gemeldet)"
    else:
        state = _short_state(info)
    steuerbar = "steuerbar" if info.controllable else "nur lesbar"
    return (
        f"{info.id} | {info.name} | {info.room} | {_TYPE_DE[info.type]} | {state} | "
        f"Risiko {info.risk} | {steuerbar}"
    )


def build_device_tools(service: DeviceService) -> list[Tool]:
    async def list_devices(args: dict[str, Any], ctx: ToolContext) -> str:
        room = args.get("room")
        room = room.strip() if isinstance(room, str) else ""
        query = args.get("query")
        query = query.strip() if isinstance(query, str) else ""
        wanted = args.get("state")
        if isinstance(wanted, str) and wanted.strip():
            wanted = _STATE_WORDS.get(wanted.strip().lower())
            if wanted is None:
                raise ToolError("state: an, aus, offen oder zu.")
        else:
            wanted = None
        words = [t for t in tokenize(query) if len(t) >= 4]
        if words and all(t[:5] in _SHUTTER_STEMS for t in words):
            infos = [i for i in service.snapshot(room or None) if i.type == "shutter"]
        elif query:
            infos = service.search(query, 60)
            if room:
                infos = [i for i in infos if i.room.lower() == room.lower()]
        else:
            infos = service.snapshot(room or None)
        if wanted:
            infos = [i for i in infos if _has_state(i, wanted)]
            if not infos:
                text = f"Kein passendes Gerät ist {wanted}."
                ctx.final_replies.append(text)
                return text
            names = [f"{i.name} ({i.room})" for i in infos[:LIST_LIMIT]]
            more = len(infos) - len(names)
            text = f"{_STATE_TITLE[wanted]} sind: " + ", ".join(names)
            text += f" und {more} weitere." if more > 0 else "."
            ctx.final_replies.append(text)
            return text
        if not infos:
            if query:
                return f"Zu '{query}' gibt es kein Gerät."
            if room:
                return f"Im Raum '{room}' gibt es keine Geräte."
            return "Es sind keine Geräte freigegeben (Allowlist leer)."
        shown = infos[:LIST_LIMIT]
        if len(infos) <= FULL_ROWS:
            lines = ["id | Name | Raum | Typ | Zustand | Risiko | Steuerung"]
            lines += [format_device(i) for i in shown]
        else:
            # Lange Listen kurz halten: jede Zeile kostet auf der CPU Prompt-Zeit. Namen genügen,
            # get_state und set_state finden das Gerät damit selbst (id nur bei gleichen Namen).
            names = [i.name.lower() for i in shown]
            lines = [
                f"{i.name} ({i.room}): {_short_state(i)}"
                + ("" if i.controllable else " [nur lesbar]")
                + ("" if i.risk == "low" else f" [Risiko {i.risk}]")
                + (f" [id {i.id}]" if names.count(i.name.lower()) > 1 else "")
                for i in shown
            ]
        if len(infos) > len(shown):
            lines.append(
                f"... und {len(infos) - len(shown)} weitere. Mit room oder query eingrenzen."
            )
        if not query and not room:
            rooms: dict[str, int] = {}
            for info in infos:
                rooms[info.room] = rooms.get(info.room, 0) + 1
            lines.append("Räume: " + ", ".join(f"{r} ({n})" for r, n in sorted(rooms.items())))
            extra = len(service.specs) - len(service.listed_specs)
            if extra > 0:
                lines.append(
                    f"Dazu {extra} technische Geräte (Status, Anlagen), die nur über query "
                    "gefunden werden."
                )
        return "\n".join(lines)

    async def get_state(args: dict[str, Any], ctx: ToolContext) -> str:
        ref = args.get("device")
        if not isinstance(ref, str) or not ref:
            raise ToolError("Parameter 'device' fehlt.")
        try:
            info = await service.get_state(ref)
        except DeviceError as exc:
            raise ToolError(str(exc)) from exc
        final = state_line(service.resolve(info.id), info)
        lines = [format_device(info)]
        similar = service.similar_with_state(info)
        if similar:
            lines.append(
                "Hinweis: Für dieses Gerät meldet openHAB keinen Wert. Ähnliche Geräte mit Wert "
                "(ob sie dasselbe Gerät sind, ist unklar):"
            )
            lines += [format_device(i) for i in similar]
            first = similar[0]
            final += f" Ähnliches Gerät: {state_line(service.resolve(first.id), first)}"
        ctx.final_replies.append(final)
        return "\n".join(lines)

    async def set_state(args: dict[str, Any], ctx: ToolContext) -> str:
        ref, command = args.get("device"), args.get("command")
        if not isinstance(ref, str) or not isinstance(command, str):
            raise ToolError("Parameter 'device' und 'command' werden benötigt.")
        try:
            result = await service.command_detailed(ref, command, source="agent")
        except DeviceError as exc:
            raise ToolError(str(exc)) from exc
        ctx.final_replies.append(confirm_text(result.spec, result.command))
        return result.text

    async def show_devices(args: dict[str, Any], ctx: ToolContext) -> str:
        room = args.get("room")
        room = room.strip() if isinstance(room, str) else ""
        title = f"Geräte: {room}" if room else "Geräte"
        item = ctx.stage.add("devices", title, content=room)
        await ctx.emit(StageShow(item=item))
        return "Das Geräte-Panel mit Live-Zuständen wird auf der Stage angezeigt."

    room_param = {"type": "string", "description": "Raumname, z. B. Wohnzimmer (optional)."}
    return [
        Tool(
            name="list_devices",
            description=(
                "Listet Smart-Home-Geräte mit Raum, Typ, Zustand und Risiko, oder sucht sie: "
                "mit query (Name, Raum oder Stichwort, z. B. 'Rollo Roman') findest du jedes "
                "Gerät, auch technische. Nur diese Geräte existieren für dich."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "room": room_param,
                    "query": {"type": "string", "description": "Suchbegriff (optional)."},
                    "state": {
                        "type": "string",
                        "enum": ["an", "aus", "offen", "zu"],
                        "description": "Nur Geräte in diesem Zustand (optional).",
                    },
                },
            },
            handler=list_devices,
        ),
        Tool(
            name="get_state",
            description="Liest den aktuellen Zustand eines Geräts (id oder Name).",
            parameters={
                "type": "object",
                "properties": {"device": {"type": "string", "description": "id oder Name."}},
                "required": ["device"],
            },
            handler=get_state,
        ),
        Tool(
            name="set_state",
            description=(
                "Steuert ein Gerät. Befehle: on/off (Licht, Schalter, Dimmer), Zahl 0-100 "
                "(Dimmer: Helligkeit; Rollladen: Prozent geschlossen, 0 = ganz offen, "
                "100 = ganz zu), up/down/stop (Rollladen), Zahl 5-30 (Thermostat), "
                "lock/unlock (Schloss), open/close (Tür, Garage). Bei Risiko high fragt das "
                "System den Nutzer selbst um Bestätigung; behaupte nie, etwas sei erledigt, "
                "solange das Werkzeug keinen Erfolg meldet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "id oder Name."},
                    "command": {"type": "string", "description": "Befehl, siehe Beschreibung."},
                },
                "required": ["device", "command"],
            },
            handler=set_state,
            risk="medium",
        ),
        Tool(
            name="show_devices",
            description="Zeigt ein Live-Panel der Geräte (mit Schaltern) auf der Stage.",
            parameters={"type": "object", "properties": {"room": room_param}},
            handler=show_devices,
        ),
    ]
