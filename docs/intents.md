# Fast-Path: Gerätebefehle ohne LLM

Einfache deutsche Gerätebefehle erledigt Cat **vor** dem LLM, lokal und ohne Internet. Erst wenn kein eindeutiger Treffer zustande kommt, geht der Text an den Agenten. Der Fast-Path läuft durch dieselben Prüfungen wie ein Werkzeugaufruf (Allowlist, Steuerungsmodus, Bestätigung bei Risiko `high`, Audit-Log, siehe `docs/devices.md`).

## Was verstanden wird (Beispiele)

| Absicht | Beispiele |
|---|---|
| An/Aus | "Mach das Licht in der Küche an", "Küchenlicht aus", "ähm schalte mal bitte die Lampe im Schlafzimmer ein" |
| Helligkeit | "Mach die Leselampe auf 40 Prozent", "Dimme die Terrassenlampen auf fünfzig Prozent" |
| Rollläden | "Rollladen im Wohnzimmer hoch", "Rollo Schlafzimmer zu", "Rollo im Schlafzimmer auf 30 Prozent" (Prozent geschlossen), "Stopp den Rollladen" |
| Heizung | "Stelle die Heizung im Wohnzimmer auf einundzwanzig Grad", "Heizung Wohnzimmer auf 22,5 Grad" |
| Temperatur lesen | "Wie warm ist es im Wohnzimmer", "Wie warm ist es draußen", "Temperatur in der Küche" |
| Zustand abfragen | "Ist das Licht in der Küche an", "Ist die Garage offen", "Wie ist der Zustand der Haustür" |
| Türen, Garage | "Mach die Garage zu", "Haustür verriegeln" (fragt vorher um Bestätigung) |

Füllwörter ("ähm", "also", "bitte", "kannst du"), Artikel, Umlaute/ß und Zahlwörter ("einundzwanzig") werden toleriert. Räume und Gerätenamen werden unscharf zugeordnet (rapidfuzz), auch in Zusammensetzungen ("Wohnzimmerlicht").

## Wann der Agent übernimmt

Der Fast-Path rät nie. Er gibt den Satz an den Agenten ab, wenn
- kein Gerät oder mehrere gleich gute Geräte passen ("Mach das Licht an" bei mehreren Lichtern ohne Raum, "Licht im Wohnzimmer" bei zwei Lichtern dort),
- der Raum nicht freigegeben ist,
- der Befehl widersprüchlich ist ("an" und "aus") oder kein Gerätebefehl ("Erzähl mir einen Witz").

Mit einem Satelliten (Phase 7) gilt dessen Raum als Standardraum: "Licht an" meint dann das Licht im Raum des Satelliten. Ein ausdrücklich genannter Raum hat Vorrang.

## Eigene Synonyme

Standardwörter stehen in `backend/src/cat/intents/synonyms.yaml`. Eigene Ergänzungen in `data/config/synonyms.yaml` (gleiche Struktur, wird dazugemischt, Neustart nötig):

```yaml
classes:
  light: [funzel]            # "Mach den Funzel an"
rooms:
  kueche: [kochnische]       # Schlüssel = Raum aus der Allowlist in Kleinschreibung, ohne Umlaute
```

Hinweis: In YAML müssen die Schlüssel `"on"` und `"off"` in Anführungszeichen stehen (sonst liest YAML sie als Wahrheitswerte; Cat fängt das ab).

## Messung

Parser und Gerätezuordnung (ohne Backend-Aufruf), 37 Beispielsätze, 20 Durchläufe:
- Allowlist mit 13 Geräten: Median 0,11 ms, 95. Perzentil 0,14 ms.
- Allowlist mit 301 Geräten: Median 0,9 ms, 95. Perzentil 2,9 ms, Maximum 15,9 ms.

Dazu kommt der Backend-Aufruf (openHAB-REST im LAN) und bei Sprache die Spracherkennung. Abschaltbar mit `CAT_FASTPATH=false`.
