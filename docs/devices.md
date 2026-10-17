# Geräte: Allowlist, Steuerung, Bestätigung, Audit

## Überblick

Cat sieht und steuert nur Geräte aus der **Allowlist** `data/config/devices.yaml` (auf dem Server `/srv/homelm/data/config/devices.yaml`). openHAB hat auf diesem Server rund 500 Items. Davon kennt Cat nur die, die Sie dort eintragen. Die Datei wird beim Start gelesen: nach einer Änderung `docker compose restart` im Ordner `/srv/homelm`.

Ist die Datei fehlerhaft, sieht Cat **keine** Geräte (fail closed), und das Geräte-Panel zeigt die Fehlermeldung.

## Eintrag

```yaml
devices:
  - id: wohnzimmer_licht        # a-z, 0-9, _ ; eindeutig
    backend: openhab            # openhab oder homeassistant
    item: Wohnzimmer_Licht      # openHAB: Item-Name; Home Assistant: entity_id (light.xyz)
    name: Wohnzimmer Licht      # so spricht Cat das Gerät an
    room: Wohnzimmer
    type: light                 # light, switch, dimmer, shutter, thermostat, sensor, lock, door, garage
    risk: low                   # optional, nur anheben möglich
    test: false                 # true = Testgerät (im Modus "test" steuerbar)
    synonyms: [Stehlampe]       # optional
    command_map: {}             # optional, siehe unten
```

Ein Beispiel liegt in `docs/devices.example.yaml`.

## Typen, Befehle, Risiko

| Typ | Befehle | Mindest-Risiko |
|---|---|---|
| `light`, `switch` | on, off | low |
| `dimmer` | on, off, 0 bis 100 (Helligkeit) | low |
| `shutter` | up, down, stop, 0 bis 100 (**Prozent geschlossen**: 0 = offen, 100 = zu) | medium |
| `thermostat` | Zahl 5 bis 30 (Solltemperatur) | medium |
| `sensor` | nur lesen | low |
| `lock` | lock, unlock | **high** |
| `door`, `garage` | open, close (garage auch stop) | **high** |

Die Allowlist kann das Risiko nur anheben, nie unter den Mindestwert senken: Schlösser, Türen und Garagen sind immer `high`. Bei `high` fragt **das Backend** den Nutzer (Dialog in der Oberfläche) und führt den Befehl nur nach ausdrücklichem "Ja" aus. Ohne verbundene Oberfläche, bei Ablehnung und nach 60 Sekunden ohne Antwort passiert nichts. Das gilt für Chat, Sprache und Panel gleichermaßen und lässt sich nicht über den Prompt umgehen.

Hinweise:
- openHAB-`Color`-Items nimmt Cat als `dimmer` (Helligkeit); Farben steuert es nicht.
- Für `lock`, `door` und `garage` sendet Cat an openHAB nur Befehle, die Sie unter `command_map` ausdrücklich zugeordnet haben, z. B. `command_map: {unlock: "OFF", lock: "ON"}`. Ohne Zuordnung wird nichts gesendet. Home Assistant hat feste Dienste und braucht das nicht.

## Steuerungsmodus (`CAT_DEVICE_CONTROL` in der `.env`)

| Wert | Wirkung |
|---|---|
| `readonly` (Standard) | Cat liest nur. Jeder Steuerbefehl wird abgelehnt und im Audit-Log vermerkt. |
| `test` | Nur Geräte mit `test: true` sind steuerbar. |
| `full` | Alle freigegebenen Geräte sind steuerbar (Risikostufen und Bestätigung gelten weiter). |

Auf `full` wird erst nach Ihrer ausdrücklichen Freigabe gestellt, nachdem ein Testgerät geprüft wurde. Nach dem Ändern: `docker compose up -d --no-build`.

## Audit-Log

Jeder Tool-Aufruf von Cat (auch Stage- und Wetter-Werkzeuge, auch Fehlschläge und unbekannte Werkzeuge) und jeder Befehl aus dem Geräte-Panel wird als eine JSON-Zeile in `data/audit.jsonl` geschrieben: Zeit, Quelle (`agent`/`ui`/`confirm`), Werkzeug, Parameter, Ergebnis. Texte werden auf 300 Zeichen gekürzt, Felder mit Namen wie `token`, `password`, `key` werden maskiert.

```bash
tail -n 20 /srv/homelm/data/audit.jsonl
```

## openHAB

- Adresse `CAT_OPENHAB_URL` (Standard `http://host.docker.internal:8080`, im Container über `extra_hosts` erreichbar, openHAB läuft im Host-Netzwerk). Cat ändert an openHAB nichts, es liest Items und sendet nur Befehle für Allowlist-Geräte.
- Token `CAT_OPENHAB_TOKEN` ist optional. Die lokale REST-API dieses Servers antwortet ohne Anmeldung. Falls Sie später einen API-Token (Profil, API-Tokens) einführen, hier eintragen.
- Änderungen kommen live per Server-Sent-Events (`/rest/events`). Bricht die Verbindung ab, markiert Cat die Geräte als offline und verbindet sich mit Wartezeit neu.

## Home Assistant

Das Plugin ist gebaut und gegen Mocks getestet, aber **nicht aktiv**, solange es keinen Home Assistant gibt. Aktivieren: `homeassistant` in `CAT_PLUGINS` aufnehmen und `CAT_HA_URL` sowie `CAT_HA_TOKEN` (Langzeit-Token) setzen. Geräte tragen Sie mit `backend: homeassistant` und `item: <entity_id>` ein.
