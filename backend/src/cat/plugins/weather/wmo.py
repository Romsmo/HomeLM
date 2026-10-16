"""WMO-Wettercodes (wie von Open-Meteo geliefert) als deutscher Kurztext."""

_LABELS: dict[int, str] = {
    0: "Klar",
    1: "Überwiegend klar",
    2: "Teils bewölkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Reifnebel",
    51: "Leichter Nieselregen",
    53: "Nieselregen",
    55: "Starker Nieselregen",
    56: "Gefrierender Nieselregen",
    57: "Starker gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Regen",
    65: "Starker Regen",
    66: "Gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Regenschauer",
    82: "Heftige Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit Hagel",
    99: "Schweres Gewitter mit Hagel",
}


def wmo_label(code: object) -> str:
    if isinstance(code, int) and code in _LABELS:
        return _LABELS[code]
    return "Unbekannt"
