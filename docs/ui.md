# Oberfläche: Arbeitsraum, Anpassen und Dateien

## Aufbau

Ein Vollbild-Arbeitsraum: in der Mitte der Cat-Kern (zeigt wartet, hört, denkt, spricht), ringsum Widgets (Datum, Uhr, System, Uptime, Wetter, Geräte, Dateien). Die Kopfzeile bleibt. Ein **Klick auf den Kern** (oder auf die letzten Worte darunter) öffnet den Chat als Fläche über dem Arbeitsraum (Esc schließt). Das **Mikrofon** hört von selbst zu, sobald die Sprache auf dem Server bereit ist (`https://`-Adresse nötig, siehe `docs/https.md`); der Knopf unter dem Kern schaltet es aus, der Browser merkt sich das. Zeigt Cat etwas auf der **Stage** (Grafik, Diagramm, Text, Bild, Geräte-Panel), liegt sie über dem Kern: "Ausblenden" bringt den Kern zurück, "Leeren" löscht den Inhalt.

## Layout anpassen (Bildschirme ab 1024 px Breite)

Unten links **"Layout anpassen"**. Dann:

| Aktion | So geht es |
|---|---|
| Verschieben | Element mit der Maus (oder dem Finger) greifen und ziehen |
| Skalieren | an den Ecken oder Kanten ziehen (Mindestgröße 7 %) |
| Tastatur | Element fokussieren (Tab), Pfeiltasten verschieben, Umschalt plus Pfeiltasten skalieren |
| Nach vorn | Anklicken oder Ziehen holt ein Element nach oben |
| Ausblenden | kleines × oben rechts am Element; "+ Name" unten links holt es zurück (Cat, Sprache und Stage lassen sich nicht ausblenden) |
| Zurücksetzen | stellt die Standardanordnung her |

Positionen und Größen sind Anteile der Fläche, die Anordnung skaliert also mit dem Fenster. Sie wird im Browser gespeichert (pro Gerät, nichts davon geht an den Server). Unter 1024 px (Handy, schmales Fenster) stapeln sich die Elemente, dort gibt es kein freies Anordnen.

## Dateien ablegen

Dateien aus dem Explorer **irgendwo ins Fenster ziehen** (oder im Widget "Dateien" auf "Datei wählen"). Cat legt sie in `data/inbox` ab (höchstens 25 MB je Datei, 500 MB insgesamt; Namen werden bereinigt, nichts wird ausgeführt) und meldet es im Chat.

- **Bilder** (png, jpg, gif, webp, svg) und **Textdateien** (txt, md, csv, json, log, yaml, py, ...) erscheinen sofort auf der Stage. Im Widget "Dateien" lassen sie sich erneut zeigen, herunterladen und löschen (zweimal klicken).
- **Das lokale Modell** kann abgelegte Dateien auflisten (`list_files`) und Textdateien lesen (`read_file`): "Fasse die Datei zusammen, die ich gerade abgelegt habe."
- **Claude** (bei Weitergabe, `docs/claude.md`) sieht den Ordner schreibgeschützt unter `/inbox` und kann auch **Bilder und PDFs** ansehen: "Frag Claude, was in der PDF steht." Dafür muss die Brücke den Ordner eingehängt haben (Compose-Änderung, Brücke neu erzeugen). Was Claude liest, geht an Anthropic.
- Dateien werden mit `nosniff` und einer Sandbox-CSP ausgeliefert, ein direkt geöffnetes SVG oder HTML führt nichts aus. Upload und Löschen stehen im Audit-Log (`file_upload`, `file_delete`). Hochladen verlangt das Login und einen passenden Origin.
