# Geräte: Allowlist, Steuerung, Bestätigung, Audit

## Überblick

Cat sieht und steuert nur Geräte aus der **Allowlist** `data/config/devices.yaml` (auf dem Server `/srv/homelm/data/config/devices.yaml`) und, wenn eingeschaltet, die automatisch erkannten openHAB-Items (nächster Abschnitt). openHAB hat auf diesem Server rund 500 Items. Die Datei wird beim Start gelesen: nach einer Änderung `docker compose restart` im Ordner `/srv/homelm`.

Ist die Datei fehlerhaft, sieht Cat **keine** Geräte (fail closed), und das Geräte-Panel zeigt die Fehlermeldung.

## Alle openHAB-Items automatisch (empfohlen)

Statt jedes Gerät einzutragen, erkennt Cat alle Items von openHAB selbst. In `devices.yaml`:

```yaml
discover:
  openhab:
    enabled: true
    readonly_patterns: []   # zusätzliche Regex (ohne Groß-/Kleinschreibung), nur lesen
    unlisted_patterns: []   # zusätzliche Regex, nur auf Nachfrage, nicht in Listen
    exclude_patterns: []    # zusätzliche Regex, ganz ausblenden
devices: []                 # von Hand eingetragene Geräte gelten vor den erkannten
```

So wird erkannt (alles aus der Item-Liste von openHAB, mit **einer** Abfrage, danach kommen Änderungen per Ereignisstrom; alle 10 Minuten wird neu erkannt):

| openHAB-Item | Cat-Gerät | Raum |
|---|---|---|
| `Switch` (mit Tag `Light`) | `light` / `switch`, steuerbar | der nächste `Location`-Gruppen-Vorfahre des semantischen Modells (z. B. "Romans Zimmer"), sonst "Haus" |
| `Dimmer`, `Color` | `dimmer` (Helligkeit), steuerbar | wie oben |
| `Rollershutter` | `shutter`, steuerbar (0 = offen, 100 = zu) | wie oben |
| `Number`, `String`, `DateTime` | `sensor`, nur lesbar | wie oben |
| `Group`, `Image`, `Player` | übersprungen | |

Name ist das Etikett des Items (bei gleichen Namen im Raum der lesbare Item-Name), der Item-Name ist als Synonym ansprechbar.

**Vorsichtsregeln (nur lesbar, kein Steuern):** Schlösser, Türöffner, Garagentore, Alarm und Sirenen; Technik wie Statusanzeigen der Automatisierung (`Stat...`, Status, Maintenance, Script, Automation), Wärmepumpe/Luxtronik, Lüftungsanlage (ComfoAir), Heizung, Trigger, Reboot und Test. Cat kann sie lesen und darüber Auskunft geben, aber nie verstellen. Will man ein Schloss oder Tor doch steuern, trägt man es von Hand mit `command_map` ein (dann gilt die Bestätigungspflicht).

**Listen:** Im Dashboard und in `list_devices` erscheinen nur Geräte, die man im Alltag meint (steuerbare Geräte und Messwerte wie Temperatur oder Leistung). Szenen, Farbtemperaturen, RSSI, Rohtexte, Zeiten und Technik sind nur über die Suche zu finden (`list_devices` mit `query`, `get_state`), z. B. "Wie ist die Außentemperatur?" oder "Ist der Bypass der Lüftung offen?".

**Nichts an openHAB wird verändert:** Cat liest (GET) und sendet Befehle an Items (POST mit einem Befehl wie ON, OFF, UP, 50). Es legt keine Items, Things oder Regeln an, ändert oder löscht keine (im Test geprüft: nie PUT oder DELETE).

**Doppelte Items:** In openHAB gibt es für manche Rollläden zwei Items (eines mit schön benanntem Etikett ohne Wert, eines technisch benannten mit Wert). Hat ein Gerät keinen Wert, nennt Cat ähnliche Geräte mit Wert, ohne zu raten, ob es dasselbe ist. Wer das dauerhaft lösen will, blendet das falsche mit `exclude_patterns` aus oder trägt das richtige von Hand ein.

### Zwillings-Items (Rollläden, Markisen)

openHAB legt für ein Gerät oft **zwei Items** an: ein Item mit schönem Etikett im Raum ("Romans Rollo", `Rollo_Roman_Romans_Zimmer__Control`, meldet nie einen Wert) und ein Technik-Item mit Wert (`Rollo_Roman_Control`). Nur das Technik-Item ist mit dem Gerät verbunden: Ein Befehl an das erste Item bewegt nichts (so kam "mein Rollo ist nicht aufgegangen" zustande). Die Erkennung verbindet beide automatisch, wenn die Technik-Namen eine Teilfolge des Etikett-Namens sind (`Rollo_Roman_Control` in `Rollo_Roman_Romans_Zimmer__Control`), der Typ gleich ist und das eine Item einen Wert hat und das andere nicht. Dann gilt:

- In Listen steht nur das Gerät mit dem schönen Namen ("Romans Rollo"), der Zustand kommt vom Zwilling.
- Befehle gehen an **beide** Items (an das ungenutzte ist das wirkungslos, an das echte kommt er an).
- Ähnliche Lampen (`Hue_Lampe_Terrasse_...` und `Hue_Lampe_Wohnzimmer_...`) werden nicht verwechselt: Dafür müsste ein Name eine Teilfolge des anderen sein.

### Automationen (openHAB-Regeln)

"Automationen" sind in openHAB **Regeln** (`/rest/rules`), nicht Items. Das Werkzeug `list_automations(query, state)` liest sie nur (GET), fasst Varianten ("Treppenhaus Beschattung Ein Ia, Ib, II") zusammen und antwortet ohne Sprachmodell-Lauf ("Aktiv sind 55 Automationen: ..."; `state`: `aktiv` oder `aus`, aus = in openHAB deaktiviert). Regeln werden weder ausgeführt noch geändert. Die Status-Items der Automatisierung (`Status Beschattung ...`) bleiben nur lesbare Messwerte.

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

- Adresse `CAT_OPENHAB_URL` (Standard `http://172.28.250.1:8080`). openHAB läuft im Host-Netzwerk, aus dem Container ist der Host das Gateway des festen Cat-Subnetzes `172.28.250.0/24`. Cat ändert an openHAB nichts, es liest Items und sendet nur Befehle für Allowlist-Geräte.
- **Firewall:** `ufw` ist auf dem Server aktiv und blockiert diesen Weg standardmäßig. Einmalig erlauben (nur dieses Subnetz, nur dieser Port):

  ```bash
  sudo ufw allow from 172.28.250.0/24 to any port 8080 proto tcp comment 'HomeLM zu openHAB'
  ```

  Rückgängig: `sudo ufw status numbered`, dann `sudo ufw delete <Nummer>`.
- Token `CAT_OPENHAB_TOKEN` ist optional. Die lokale REST-API dieses Servers antwortet ohne Anmeldung. Falls Sie später einen API-Token (Profil, API-Tokens) einführen, hier eintragen.
- Änderungen kommen live per Server-Sent-Events (`/rest/events`). Bricht die Verbindung ab, markiert Cat die Geräte als offline und verbindet sich mit Wartezeit neu.

## Home Assistant

Das Plugin ist gebaut und gegen Mocks getestet, aber **nicht aktiv**, solange es keinen Home Assistant gibt. Aktivieren: `homeassistant` in `CAT_PLUGINS` aufnehmen und `CAT_HA_URL` sowie `CAT_HA_TOKEN` (Langzeit-Token) setzen. Geräte tragen Sie mit `backend: homeassistant` und `item: <entity_id>` ein.
