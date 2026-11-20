# Oberfläche: Arbeitsraum, Anpassen und Dateien

## Aufbau

Ein Vollbild-Arbeitsraum: in der Mitte der Cat-Kern (zeigt wartet, hört, denkt, spricht), ringsum Widgets (Datum, Uhr, System, Uptime, Wetter, Geräte, Dateien). Die Kopfzeile bleibt. Ein **Klick auf den Kern** (oder auf die letzten Worte darunter) öffnet den Chat als Fläche über dem Arbeitsraum (Esc schließt). Das **Mikrofon** hört von selbst zu, sobald die Sprache auf dem Server bereit ist (`https://`-Adresse nötig, siehe `docs/https.md`); der Knopf unter dem Kern schaltet es aus, der Browser merkt sich das. Zeigt Cat etwas auf der **Stage** (Grafik, Diagramm, Text, Bild, Geräte-Panel), liegt sie über dem Kern: "Ausblenden" bringt den Kern zurück, "Leeren" löscht den Inhalt.

## Elemente wie Fenster bedienen (Bildschirme ab 1024 px Breite)

Es gibt keinen Bearbeiten-Knopf: Jedes Widget lässt sich immer anfassen. **Cat sitzt fest in der Mitte** und lässt sich nicht verschieben (Anordnung und Größe der Mitte bleiben, damit Cat immer an derselben Stelle ist).

| Aktion | So geht es |
|---|---|
| Verschieben | am schmalen Balken am oberen Rand des Widgets greifen und ziehen (Maus oder Finger) |
| Skalieren | an der Ecke **unten rechts** ziehen, die linke obere Ecke bleibt stehen (Mindestgröße 7 %) |
| Tastatur | den Balken fokussieren (Tab), Pfeiltasten verschieben, Umschalt plus Pfeiltasten skalieren |
| Nach vorn | Anklicken oder Ziehen holt ein Widget über die anderen |
| Ausblenden | kleines x am Balken (erscheint beim Darüberfahren); unten links erscheint dann "+ Name" zum Zurückholen |
| Zurücksetzen | "Layout zurücksetzen" unten links stellt alle Widgets an ihren Standardplatz |

Der Inhalt der Widgets bleibt voll bedienbar (Schaltflächen, Listen). Positionen und Größen sind Anteile der Fläche, die Anordnung skaliert also mit dem Fenster. Sie wird im Browser gespeichert (pro Gerät, nichts davon geht an den Server). Unter 1024 px (Handy, schmales Fenster) stapeln sich die Elemente, dort gibt es kein freies Anordnen.

## Dateien ablegen

Dateien aus dem Explorer **irgendwo ins Fenster ziehen** (oder im Widget "Dateien" auf "Datei wählen"). Cat legt sie in `data/inbox` ab (höchstens 25 MB je Datei, 500 MB insgesamt; Namen werden bereinigt, nichts wird ausgeführt) und meldet es im Chat.

- **Bilder** (png, jpg, gif, webp, svg) und **Textdateien** (txt, md, csv, json, log, yaml, py, ...) erscheinen sofort auf der Stage. Im Widget "Dateien" lassen sie sich erneut zeigen, herunterladen und löschen (zweimal klicken).
- **Das lokale Modell** kann abgelegte Dateien auflisten (`list_files`) und Textdateien lesen (`read_file`): "Fasse die Datei zusammen, die ich gerade abgelegt habe."
- **Claude** (bei Weitergabe, `docs/claude.md`) sieht den Ordner schreibgeschützt unter `/inbox` und kann auch **Bilder und PDFs** ansehen: "Frag Claude, was in der PDF steht." Dafür muss die Brücke den Ordner eingehängt haben (Compose-Änderung, Brücke neu erzeugen). Was Claude liest, geht an Anthropic.
- Dateien werden mit `nosniff` und einer Sandbox-CSP ausgeliefert, ein direkt geöffnetes SVG oder HTML führt nichts aus. Upload und Löschen stehen im Audit-Log (`file_upload`, `file_delete`). Hochladen verlangt das Login und einen passenden Origin.

## Handy-Ansicht (nur Chat)

Auf Handys (schmaler Bildschirm, bis 700 px, oder Touch bis 900 px) zeigt Cat keinen Arbeitsraum, sondern **nur den Chat**: Verlauf, Eingabefeld, Mikrofonknopf und ein Leuchtpunkt, der zeigt, ob Cat wartet, zuhört, denkt oder spricht.

- **Mikrofon:** startet von selbst, sobald die Seite offen ist, außer man hat es ausgeschaltet (der Browser merkt sich das). Beim Zurückkehren in die App (anderer Tab, Bildschirm war aus) startet es wieder. Die Aktivierungsphrase gilt wie überall: "Hey Cat ..." und danach 20 s Folgefenster, unadressierte Sprache wird verworfen (`docs/voice.md`). Das Mikrofon geht nur über HTTPS (`https://ai.catscastlecloud.de` oder `https://192.168.0.10:8490` mit installierter CA, `docs/https.md`); der Browser fragt beim ersten Mal nach der Erlaubnis.
- **Bildschirm anlassen:** Solange das Mikrofon an ist, hält die Seite den Bildschirm wach (Wake Lock, im Menü abschaltbar, Standard an). Das kostet Akku; ohne läuft das Mikrofon nur, solange der Bildschirm an ist.
- **Tastatur:** Die Ansicht folgt der sichtbaren Höhe (`visualViewport`), das Eingabefeld bleibt über der Tastatur. Eingabe 16 px (kein Zoom auf iOS), Tippflächen mindestens 44 px, Ränder berücksichtigen Notch und Home-Balken.
- **Grafiken:** Zeigt Cat etwas auf der Stage, erscheint "Grafik oder Anzeige ansehen" über der Eingabe (auch im Menü); sie öffnet die Stage im Vollbild.
- **Bestätigungen** für Türen und Schlösser kommen als Dialog, im Backend erzwungen wie auf dem Desktop.
- **Menü** (drei Punkte): Chat exportieren, Chat leeren, Bildschirm anlassen, Desktop-Ansicht, Abmelden.
- **Ansicht wählen:** `?ui=mobile` oder `?ui=desktop` an die Adresse hängen (wird gemerkt), `?ui=auto` oder "Handy-Ansicht" in der Kopfzeile des Desktops bzw. "Desktop-Ansicht" im Menü schaltet um.
- **Als App installieren:** Im Browser "Zum Startbildschirm hinzufügen" (Android: "App installieren"). Es gibt Manifest und Symbole (`frontend/public`), die App startet mit `/?ui=mobile`, im Hochformat ohne Browserleiste. Hinter der Caddy-Anmeldung wird das Manifest mit Cookies geladen (`crossorigin="use-credentials"`).
- **Grenzen:** Nicht auf einem echten Handy getestet (nur Browser-Emulation 375x812 und Tests). Safari/iOS startet Audio erst nach einer Berührung (der erste Tipp aktiviert es), und iOS beendet das Mikrofon im Hintergrund; ein ausgeschalteter Bildschirm hört nicht mehr zu.
