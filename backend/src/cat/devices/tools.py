"""Werkzeuge für das Modell: list_devices, get_state, set_state, show_devices."""

from typing import Any

from cat.agent.tools import Tool, ToolContext, ToolError
from cat.devices.commands import DeviceError
from cat.devices.models import DeviceInfo
from cat.devices.service import DeviceService
from cat.ws.protocol import StageShow

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


def format_device(info: DeviceInfo) -> str:
    if not info.online:
        state = "offline"
    elif info.state is None:
        state = "unbekannt"
    else:
        state = f"{info.state} {info.unit}".strip() if info.unit else info.state
    steuerbar = "steuerbar" if info.controllable else "nur lesbar"
    return (
        f"{info.id} | {info.name} | {info.room} | {_TYPE_DE[info.type]} | {state} | "
        f"Risiko {info.risk} | {steuerbar}"
    )


def build_device_tools(service: DeviceService) -> list[Tool]:
    async def list_devices(args: dict[str, Any], _: ToolContext) -> str:
        room = args.get("room")
        infos = service.snapshot(room if isinstance(room, str) and room else None)
        if not infos:
            if room:
                return f"Im Raum '{room}' gibt es keine freigegebenen Geräte."
            return "Es sind keine Geräte freigegeben (Allowlist leer)."
        header = "id | Name | Raum | Typ | Zustand | Risiko | Steuerung"
        return "\n".join([header, *(format_device(i) for i in infos)])

    async def get_state(args: dict[str, Any], _: ToolContext) -> str:
        ref = args.get("device")
        if not isinstance(ref, str) or not ref:
            raise ToolError("Parameter 'device' fehlt.")
        try:
            return format_device(await service.get_state(ref))
        except DeviceError as exc:
            raise ToolError(str(exc)) from exc

    async def set_state(args: dict[str, Any], _: ToolContext) -> str:
        ref, command = args.get("device"), args.get("command")
        if not isinstance(ref, str) or not isinstance(command, str):
            raise ToolError("Parameter 'device' und 'command' werden benötigt.")
        try:
            return await service.command(ref, command, source="agent")
        except DeviceError as exc:
            raise ToolError(str(exc)) from exc

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
                "Listet die freigegebenen Smart-Home-Geräte mit Raum, Typ, Zustand und Risiko. "
                "Nur diese Geräte existieren für dich."
            ),
            parameters={"type": "object", "properties": {"room": room_param}},
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
