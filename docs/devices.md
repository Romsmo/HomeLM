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

### Kontext der letzten Anfragen und der Nutzer (seit 2026-11-21)

Cat merkt sich die **letzte Schaltung** kurz (`CAT_CONTEXT_TTL_S`, Standard 600 Sekunden, danach wird sie vergessen) und versteht damit Folgeanfragen ohne Modell (`intents/teach.py`, Handler `_followup`):

| Du sagst (nach "Schließe die Markisen") | Cat tut |
|---|---|
| "Mach sie doch wieder auf", "Mach alle auf", "Ich meinte mach alle auf" | die Geräte der letzten Schaltung (alle drei Markisen) bekommen den neuen Befehl |
| "Mach sie wieder" (ohne Richtung) | das Gegenteil des letzten Befehls |
| nach "Markise West auf": "Ost und Nord auch!", "Markise Ost und Markise Nord auch" | derselbe Befehl (`up`) an die genannten Geräte; "Ost" findet "Markise Ost" unter den Geräten derselben Sorte im Raum |
| nach "Markise Nord zu": "Mach alle auf" | "alle" meint alle Geräte gleicher Sorte im Raum (alle Markisen, nicht die Rollos) |

Nie geraten: Ist ein Name nicht eindeutig oder nennt ein Satz ein anderes Gerät, entscheidet wie bisher das Modell. Türen, Schlösser und Tore laufen nie so (dort immer ein vollständiger Befehl). Verneinungen und Rückblicke ("Ich hab nie gesagt ...") gehen an die Entschuldigung. Nach Ablauf der Zeit gibt es keinen Kontext mehr, "Mach sie wieder auf" geht dann an das Modell.

**Der Nutzer:** Mit erkanntem Sprecher (Stimme oder Vorstellung, `docs/people.md`) meint "mein Rollo" das Gerät dieser Person: Cat probiert zuerst "Rollo Roman" (Name statt "mein") und dann das Wort unverändert. Ohne bekannten Sprecher fragt Cat nach, welches Rollo gemeint ist.

### Tun oder nur lesen? (seit 2026-11-21)

Cat entscheidet bei jeder Nachricht zuerst, **was zu tun ist**, und handelt danach (`intent_kind` in `intents/text.py`, erzwungen im Backend in `agent/loop.py`, nicht nur im Prompt):

| Art | Beispiele | Was Cat tut |
|---|---|---|
| **tun** (`act`) | "Schließe die Markisen", "Licht an", "Rollo runter", "Kannst du das Rollo bitte schließen?", "Mach das Licht an und sag mir Bescheid" | schaltet; Cat meldet erst "erledigt", wenn `set_state` wirklich lief |
| **nur lesen** (`read`) | "Ist das Rollo zu?", "Welche Rollos sind offen?", "Sag mir, ob das Licht an ist", "Zeig mir die offenen Rollos" | schaltet **nie**; liest den Zustand und antwortet damit |
| **Sonstiges** (`none`) | "Das Rollo ist zu" (Feststellung), "Ich hab nie gesagt, dass du das Licht anmachen sollst", ein bloßer Name | schaltet nie; **sieht nach** (`get_state`, `list_devices`, `memory_search`), antwortet mit dem Gefundenen und sagt sonst **ehrlich**, dass es das nicht klären kann |

**Sonstiges, Schritt für Schritt:** (1) Cat schaltet nichts. (2) Das Modell bekommt den Hinweis, die Aussage oder Frage mit den Lese-Werkzeugen zu prüfen (Geräte, Notizen); eine Antwort ohne Nachsehen, die etwas über Geräte behauptet ("Okay, das Rollo ist jetzt zu"), wird nicht gezeigt. (3) Bringt das nichts, sagt Cat ehrlich, dass es nichts gefunden hat und nichts geschaltet wurde, und bittet um einen Befehl. Bei Nachrichten ohne Geräte läuft wie bisher die Kette lokales Modell, Wissens-Cache, **Claude** (Absage des lokalen Modells oder `ask_claude`), und ohne Claude oder bei erreichtem Limit kommt die ehrliche Antwort "Dazu fällt mir lokal keine verlässliche Antwort ein" bzw. der Grund. Eine Websuche gibt es nicht: Claude läuft ohne Web-Werkzeuge (`docs/claude.md`), "Recherche" heißt hier Geräte, Notizen und Claudes Wissen.

Wichtig dabei: Schaltwörter wie "zu", "auf", "an" stehen auch in Fragen und Feststellungen. Früher konnte das Modell bei "Ist das Rollo zu?" trotzdem `set_state` aufrufen. Jetzt wird so ein Aufruf bei einer Frage **nicht ausgeführt**, sondern durch das Lesen des Zustands ersetzt (im Audit-Log als "Nur gelesen, nichts geschaltet"). Eine höfliche Bitte als Frage ("Kannst du ... schließen?") zählt als Auftrag, "Kannst du mir sagen, ob ..." als Frage. Ein vom Spracherkenner angehängtes Fragezeichen ändert einen Befehl mit Befehlsverb ("Mach das Licht an?") nicht. Bestätigungen und Risikostufen gelten unverändert.

### Wie Cat ein Gerät zu einem Namen findet (Befehle)

Bei einem Befehl ("Schließe die Markisen") sucht Cat den Namen in **allen** openHAB-Items und nimmt dabei **steuerbare Geräte vor Sensoren**. Hintergrund (21.11.2026): Zur Anfrage passte der Sensor "Markise Nord Position Manuell" fast so gut wie die Markise selbst, und Cat antwortete "nur als Sensor vorhanden", obwohl es drei steuerbare Markisen gibt.

- **Sammelwörter für Rollläden:** "die Markisen", "alle Markisen", "Terrassenmarkisen", "Rollos Wohnzimmer" meinen alle steuerbaren Rollläden dieses Namens, **wenn sie im selben Raum stehen**. Über mehrere Räume ("die Rollos") wird nicht geraten, Cat fragt nach. Markisen und Rollos werden nicht vermischt.
- **Passender Befehl:** Schickt das Modell zu einem Rollladen "on" oder "off", obwohl der Nutzer eindeutig "schließen" oder "öffnen" gesagt hat, nimmt Cat `down` bzw. `up`. Ohne eindeutiges Wort ("Mach die Markise aus") passiert nichts.
- **Neue Geräte sofort:** Findet Cat einen Namen nicht (oder nur einen Sensor), liest es die Item-Liste von openHAB **sofort** neu und sucht noch einmal (höchstens alle 15 Sekunden; die regelmäßige Erkennung alle 10 Minuten bleibt). Ein gerade in openHAB angelegtes Item ist so gleich ansprechbar. Das gilt für Befehle und Zustandsfragen.
- Was Cat nie steuert, bleibt wie oben beschrieben nur lesbar (Schlösser, Tore, Alarm, Technik).

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
