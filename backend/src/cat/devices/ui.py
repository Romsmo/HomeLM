import logging

from cat.devices.commands import DeviceError
from cat.state import AppState
from cat.ws.protocol import ErrorEvent

log = logging.getLogger("cat.devices")


async def handle_ui_command(state: AppState, device_id: str, command: str) -> None:
    """Befehl aus dem Geräte-Panel. Läuft durch dieselben Prüfungen wie ein Tool-Aufruf."""
    params = {"device": device_id, "command": command}
    try:
        message = await state.devices.command(device_id, command, source="ui")
    except DeviceError as exc:
        await state.audit.record("set_state", params, str(exc), ok=False, source="ui")
        await state.emit(ErrorEvent(message=str(exc)))
        return
    except Exception:
        log.exception("Befehl aus der Oberfläche fehlgeschlagen")
        await state.audit.record("set_state", params, "interner Fehler", ok=False, source="ui")
        await state.emit(ErrorEvent(message="Der Befehl ist fehlgeschlagen. Details im Log."))
        return
    await state.audit.record("set_state", params, message, ok=True, source="ui")
