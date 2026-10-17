"""Befehle je Gerätetyp: prüfen und in eine kanonische Form bringen."""

from cat.devices.models import DeviceSpec, DeviceType


class DeviceError(Exception):
    """Fehler mit deutscher Meldung, die der Nutzer oder das Modell sehen darf."""


_WORDS: dict[DeviceType, set[str]] = {
    "light": {"on", "off"},
    "switch": {"on", "off"},
    "dimmer": {"on", "off"},
    "shutter": {"up", "down", "stop"},
    "thermostat": set(),
    "sensor": set(),
    "lock": {"lock", "unlock"},
    "door": {"open", "close"},
    "garage": {"open", "close", "stop"},
}
# Typen, die zusätzlich eine Zahl akzeptieren, und deren erlaubter Bereich.
_NUMERIC: dict[DeviceType, tuple[float, float]] = {
    "dimmer": (0, 100),
    "shutter": (0, 100),
    "thermostat": (5, 30),
}
_ALIASES = {
    "open": "up",
    "close": "down",
    "an": "on",
    "ein": "on",
    "aus": "off",
    "auf": "up",
    "hoch": "up",
    "runter": "down",
    "zu": "down",
}
# Für Türen und Garagen bedeuten auf/zu öffnen/schließen.
_DOOR_ALIASES = {"auf": "open", "zu": "close", "up": "open", "down": "close"}


def allowed_commands(device_type: DeviceType) -> str:
    parts = sorted(_WORDS[device_type])
    if device_type in _NUMERIC:
        low, high = _NUMERIC[device_type]
        parts.append(f"Zahl {low:g} bis {high:g}")
    return ", ".join(parts)


def is_controllable(device_type: DeviceType) -> bool:
    return bool(_WORDS[device_type]) or device_type in _NUMERIC


def normalize_command(spec: DeviceSpec, raw: str) -> str:
    """Gibt den kanonischen Befehl zurück oder wirft DeviceError."""
    if not is_controllable(spec.type):
        raise DeviceError(f"'{spec.name}' ist ein reiner Sensor und kann nicht gesteuert werden.")
    text = raw.strip().lower().replace(",", ".")
    if spec.type in ("door", "garage", "lock"):
        text = _DOOR_ALIASES.get(text, text) if spec.type != "lock" else text
    else:
        text = _ALIASES.get(text, text)
    if text in _WORDS[spec.type]:
        return text
    if spec.type in _NUMERIC:
        try:
            number = float(text.rstrip("%"))
        except ValueError:
            number = None
        if number is not None:
            low, high = _NUMERIC[spec.type]
            if not low <= number <= high:
                raise DeviceError(
                    f"Der Wert {number:g} liegt außerhalb des erlaubten Bereichs "
                    f"({low:g} bis {high:g}) für '{spec.name}'."
                )
            return f"{number:g}"
    raise DeviceError(
        f"Der Befehl '{raw}' passt nicht zu '{spec.name}'. Erlaubt: {allowed_commands(spec.type)}."
    )


def describe_command(spec: DeviceSpec, command: str) -> str:
    """Kurzer deutscher Satzbaustein für Rückfrage und Antwort."""
    labels = {
        "on": "einschalten",
        "off": "ausschalten",
        "up": "hochfahren",
        "down": "herunterfahren",
        "stop": "anhalten",
        "lock": "verriegeln",
        "unlock": "entriegeln",
        "open": "öffnen",
        "close": "schließen",
    }
    if command in labels:
        return f"'{spec.name}' {labels[command]}"
    unit = "°C" if spec.type == "thermostat" else "%"
    return f"'{spec.name}' auf {command} {unit} stellen"
