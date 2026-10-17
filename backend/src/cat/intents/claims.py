"""Erkennt Antworten, die einen Gerätezustand oder eine erledigte Schaltung behaupten.

Das kleine lokale Modell antwortet gelegentlich "Okay, das Licht ist aus", ohne das Werkzeug
aufgerufen zu haben. Der Agent prüft darum jede solche Behauptung gegen die Werkzeugaufrufe des
Zuges (siehe agent/loop.py). Das ist eine Sicherung gegen falsche Erfolgsmeldungen, kein
Befehlsparser.
"""

import re

_STATE = r"(an|aus|ein|offen|zu|auf|geschlossen|geöffnet|eingeschaltet|ausgeschaltet|angeschaltet)"
# Nach dem Zustandswort muss der Satz (Teilsatz) enden: "ist an." ja, "ist an der Decke" nein.
_END = r"(?=\s*(?:[.,!?;:\n]|$)|\s+(?:und|oder|aber)\b)"
_CLAIM = re.compile(
    rf"\b(ist|sind|bleibt|steht|stehen)\s+(jetzt\s+|nun\s+|wieder\s+|schon\s+|bereits\s+)?{_STATE}\b{_END}"
    r"|\b(habe|hab|wurde|wurden)\b[^.!?\n]{0,50}"
    r"\b(eingeschaltet|ausgeschaltet|angeschaltet|angemacht|ausgemacht|geöffnet|geschlossen|"
    r"hochgefahren|runtergefahren|heruntergefahren|gedimmt|verriegelt|entriegelt)\b"
    r"|\b(ist|wurde|alles)\s+erledigt\b|^\W*erledigt\b"
    r"|\bfährt\s+(jetzt\s+)?(hoch|runter|herunter)\b",
    re.IGNORECASE,
)


def claims_action(text: str) -> bool:
    """Behauptet der Text, ein Gerät sei in einem Zustand oder eine Schaltung sei erledigt?"""
    return bool(_CLAIM.search(text))
