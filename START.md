# Start: Cat mit Claude Code bauen

## Was du vorher tust (ca. 15 Minuten)

1. **Backup der Nextcloud-Daten** (oder zumindest bewusst entscheiden, es zu lassen). Auf `/mnt/intensodrive` gibt es bisher nur eine Kopie, und Claude Code bekommt Zugriff auf einen Server mit Docker-Rechten.
2. **Privates Git-Repo "HomeLM"** (z. B. auf GitHub) anlegen und den Inhalt dieses Ordners hineinlegen:
   ```
   cd HomeLM
   git init && git add . && git commit -m "Startpaket"
   git remote add origin <URL-von-HomeLM>
   git push -u origin main
   ```
3. **SSH-Zugang** für Claude Code zum Server (`192.168.0.10`) per Schlüssel, kein Passwort im Chat. Am besten ein eigener Benutzer, nur für dieses Projekt. Claude Code fragt dich, wie er sich verbinden soll.
4. **Claude Code starten** im Ordner `HomeLM` ganz normal (`claude`). **Nicht** mit `--dangerously-skip-permissions`: Auf diesem Server liegen Nextcloud-Daten und Trafficnetwork, du willst die Rückfragen. Die mitgelieferte `.claude/settings.json` sperrt die gefährlichsten Befehle zusätzlich, ist aber nur ein Sicherheitsnetz.
5. **Den Prompt unten einfügen.**

## Was du während der Arbeit tun musst

Claude Code fragt dich dann nach genau diesen Dingen, du kannst sie schon bereithalten:

- Anthropic-API-Schlüssel (mit Ausgabenlimit). Du trägst ihn selbst in die `.env` auf dem Server ein.
- openHAB-API-Token (Profil, API-Tokens) und die openHAB-Adresse.
- Ob Home Assistant existiert (sonst wird das HA-Plugin nur gebaut, nicht aktiviert).
- Standort für das Wetter-Widget.
- Freigaben für Eingriffe in Caddy und für das Steuern echter Geräte.
- Für Phase 7: Raspberry Pi (z. B. Zero 2 W), Mikrofon/Lautsprecher, SSH-Zugang zum Pi.

## Der Prompt (einfach kopieren)

```
Du bist der alleinige Entwickler des Projekts "HomeLM" (Repo HomeLM; der Assistent darin heißt "Cat"). Lies zuerst CLAUDE.md, docs/cat-plan.md und docs/phase-prompts.md vollständig und halte dich strikt an CLAUDE.md (Arbeitsmodus, Rote Linien, Rückfrage-Regeln).

AUFTRAG
Baue Cat von Phase 0 bis Phase 9 vollständig und bringe es auf meinem Server (192.168.0.10) zum Laufen. Arbeite selbstständig, ohne mich bei Routine zu fragen. Frage mich nur nach den Regeln in CLAUDE.md, dann aber gebündelt und mit deiner Empfehlung als erste Option.

SCHRITT 1: Klärung (einmal, gebündelt)
Stelle mir in einem Rutsch alle Fragen, die du für den Start brauchst, mindestens:
- Wo läuft Claude Code (auf meinem PC oder direkt auf dem Server), und wie verbindest du dich per SSH (Host, Benutzer, Schlüssel)? Frage nie nach Passwörtern oder Tokens im Chat.
- Owner/URL des privaten Repos "HomeLM" und wie du dorthin pushst (SSH-Key oder Token, nie im Chat).
- Wie soll Cat im LAN erreichbar sein (nur Port auf 192.168.0.10, oder LAN-Hostname mit internem HTTPS über Caddy)? Nenne deine Empfehlung und die Risiken.
- Existiert Home Assistant, und wo?
- Standort für das Wetter-Widget.
Erkläre mir bei jedem Punkt in einem Satz, warum du ihn brauchst.

SCHRITT 2: Bestandsaufnahme des Servers (nur lesen)
Ermittle RAM, CPU, Last, freien Speicher, laufende Container (docker ps, docker stats), Docker-Netzwerke, die Caddy-Konfiguration, den openHAB-Port und ob openHAB erreichbar ist. Schreibe das nach docs/server-inventory.md (ohne Secrets). Weiche ich von der Beschreibung in CLAUDE.md Abschnitt 2 ab, melde es mir. Ändere in diesem Schritt nichts.

SCHRITT 3: Umsetzungsplan
Zeige mir kurz (max. eine Seite), was du aufgrund des Inventars ändern würdest (Modellgrößen, mem_limit, Netzwerk, Caddy-Route, Reihenfolge). Hole dir meine Freigabe.

SCHRITT 4: Phasen 0 bis 9
Arbeite die Phasen aus docs/phase-prompts.md der Reihe nach ab. Pro Phase: kurz planen, umsetzen, Tests schreiben, auf dem Server bereitstellen, Abnahmekriterium selbst prüfen, docs/PROGRESS.md aktualisieren, committen und pushen. Danach ohne Rückfrage in die nächste Phase, außer eine Regel in CLAUDE.md verlangt sie.
Pausen, in denen du auf mich wartest:
- bevor du in bestehende Dienste eingreifst (Caddy-Route) und vor jeder roten Linie aus CLAUDE.md,
- bevor du echte Geräte steuerst (zuerst Testgerät, dann meine Freigabe),
- wenn ich etwas tun muss (Secret eintragen, Hardware, Pi einrichten); sag mir dann genau, was ich tun soll, und arbeite an unabhängigen Aufgaben weiter.

SCHRITT 5: Abschluss
Zeige am Ende: was läuft (mit URL und Zugang), was die Abnahmen ergeben haben, Messwerte (Latenz, RAM), offene Punkte und wie ich Cat starte, stoppe, sichere und zurückrolle.

Beginne jetzt mit Schritt 1.
```
