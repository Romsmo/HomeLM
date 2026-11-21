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
        if command.replace(".0", "") == "0":
            return f"Okay, {n} ist offen."
        if command.replace(".0", "") == "100":
            return f"Okay, {n} ist zu."
        return f"Okay, {n} ist zu {_num(command)} Prozent geschlossen."
    return f"Okay, {n} steht auf {_num(command)} Prozent."


_PLURAL = {
    "on": "sind an",
    "off": "sind aus",
    "up": "fahren hoch",
    "down": "fahren runter",
    "stop": "halten an",
    "lock": "sind verriegelt",
    "unlock": "sind entriegelt",
    "open": "werden geöffnet",
    "close": "werden geschlossen",
}


def join_names(names: list[str]) -> str:
    """ "Markise Nord, Markise Ost und Markise West" -> "Markise Nord, Ost und West": Haben alle
    Namen dasselbe erste Wort, steht es nur einmal. Sonst einfach "A, B und C"."""
    if len(names) <= 1:
        return "".join(names)
    firsts = {n.split(" ", 1)[0] for n in names}
    if len(firsts) == 1 and all(" " in n for n in names):
        names = [names[0]] + [n.split(" ", 1)[1] for n in names[1:]]
    return ", ".join(names[:-1]) + " und " + names[-1]


def _plural_tail(spec: DeviceSpec, command: str) -> str:
    if command in _PLURAL:
        return _PLURAL[command]
    number = command.replace(".0", "")
    if spec.type == "thermostat":
        return f"sind auf {_num(command)} Grad gestellt"
    if spec.type == "shutter":
        if number == "0":
            return "sind offen"
        if number == "100":
            return "sind zu"
        return f"sind zu {_num(command)} Prozent geschlossen"
    return f"stehen auf {_num(command)} Prozent"


def confirm_many(items: list[tuple[DeviceSpec, str]]) -> list[str]:
    """Bestätigungen, bei denen gleiche Befehle zusammengefasst sind: statt dreimal "Okay, Markise
    Nord fährt runter" einmal "Okay, Markise Nord, Ost und West fahren runter." Kurz und natürlich:
    bei Geräte-Befehlen mögen Nutzer knappe Bestätigungen (docs/devices.md)."""
    groups: dict[tuple[str, str], list[DeviceSpec]] = {}
    for spec, command in items:
        key = (command, "" if command in _PLURAL else spec.type)
        groups.setdefault(key, []).append(spec)
    lines: list[str] = []
    for (command, _), specs in groups.items():
        if len(specs) == 1:
            lines.append(confirm_text(specs[0], command))
        else:
            names = join_names([s.name for s in specs])
            lines.append(f"Okay, {names} {_plural_tail(specs[0], command)}.")
    return lines


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
