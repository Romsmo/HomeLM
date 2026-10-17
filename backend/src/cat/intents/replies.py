"""Kurze deutsche Antworttexte für Gerätebefehle und Zustände (ohne LLM)."""

from cat.devices.models import DeviceInfo, DeviceSpec


def _num(value: str) -> str:
    return value.replace(".", ",")


def confirm_text(spec: DeviceSpec, command: str) -> str:
    n = spec.name
    texts = {
        "on": f"Okay, {n} ist an.",
        "off": f"Okay, {n} ist aus.",
        "up": f"Okay, {n} fährt hoch.",
        "down": f"Okay, {n} fährt runter.",
        "stop": f"Okay, {n} hält an.",
        "lock": f"Okay, {n} ist verriegelt.",
        "unlock": f"Okay, {n} ist entriegelt.",
        "open": f"Okay, {n} wird geöffnet.",
        "close": f"Okay, {n} wird geschlossen.",
    }
    if command in texts:
        return texts[command]
    if spec.type == "thermostat":
        return f"Okay, {n} ist auf {_num(command)} Grad gestellt."
    if spec.type == "shutter":
        return f"Okay, {n} ist auf {_num(command)} Prozent zu."
    return f"Okay, {n} steht auf {_num(command)} Prozent."


def state_line(spec: DeviceSpec, info: DeviceInfo) -> str:
    n = spec.name
    if not info.online:
        return f"{n} ist gerade nicht erreichbar."
    if info.state is None:
        return f"Den Zustand von {n} kenne ich nicht."
    state = info.state
    unit = info.unit or ""
    if state.upper() in ("ON", "OFF"):
        return f"{n} ist {'an' if state.upper() == 'ON' else 'aus'}."
    if spec.type == "shutter" and state.replace(".", "", 1).isdigit():
        pos = float(state)
        if pos <= 0:
            return f"{n} ist offen."
        if pos >= 100:
            return f"{n} ist zu."
        return f"{n} ist zu {_num(state)} Prozent geschlossen."
    words = {
        "locked": "verriegelt",
        "unlocked": "entriegelt",
        "open": "offen",
        "closed": "geschlossen",
    }
    shown = words.get(state.lower())
    if shown:
        return f"{n}: {shown}."
    return f"{n}: {_num(state)} {unit}".strip() + "."
