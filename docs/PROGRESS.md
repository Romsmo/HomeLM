# Fortschritt

## Entscheidungen vorab (Schritt 1, geklärt mit dem Nutzer)

- Arbeit zunächst **lokal auf dem PC**, noch kein Server-Zugriff (Schritt 2/3 ausstehend).
- Remote: `https://github.com/Romsmo/HomeLM` (privat), Push über das lokal eingerichtete Git-Login.
- Erreichbarkeit im LAN: **zuerst nur ein Port an 192.168.0.10**, HTTPS/Caddy erst in Phase 6.
- Home Assistant existiert nicht: HA-Plugin nur gegen Mocks, deaktiviert.
- Wetter-Standort: **offen**, wird vor Phase 3 benötigt.

## Phase 0: Fundament

**Gebaut**
- `backend/`: FastAPI-Skelett mit `/health`, Pydantic Settings (Prefix `CAT_`, `.env`), `uv`, `pytest`, `ruff`. Der Backend-Prozess liefert zusätzlich das gebaute Frontend aus (`CAT_STATIC_DIR`), API-Routen haben Vorrang.
- `frontend/`: Vite, React 19, TypeScript strict, Tailwind 4, `vitest`; leere Seite.
- `Dockerfile` (Multi-Stage: Frontend bauen, Backend-Abhängigkeiten, schlanke Laufzeit, Nicht-Root-Benutzer, Healthcheck) und `docker-compose.yml` mit **einem** Service `backend` (`mem_limit 512m`, `cpus 1.0`, Volume `./data`). Ein eigener Frontend-Container wäre nur zusätzlicher RAM-Verbrauch ohne Nutzen, daher die einfachste Variante.
- Port-Bindung: `${CAT_BIND_ADDR:-127.0.0.1}:${CAT_HOST_PORT:-8080}`. Standard ist nur lokal; auf dem Server `CAT_BIND_ADDR=192.168.0.10` setzen, nie `0.0.0.0`.
- `.env.example`, `.gitignore` (u. a. `.env`, `data/`, `.local/`), `.gitattributes` (LF).

**Abnahme: bestanden (lokal)**
- `docker compose up --build`: Container `healthy`, `GET /health` liefert `{"status":"ok","version":"0.1.0"}`, `GET /` liefert die Frontend-Seite (HTTP 200), Laufzeit-Benutzer `cat`, ca. 43 MiB RAM im Leerlauf.
- Backend: `uv run pytest` 3 Tests grün, `ruff check` und `ruff format` sauber.
- Frontend: `npm run build` und `npm test` (1 Test) grün.

**Entscheidungen / Hinweise**
- Lokal ist `uv` nur als Python-Modul vorhanden: `python -m uv ...` statt `uv ...` (Installation per `pip install --user uv`).
- Der PC hat einen TLS-Scan durch Norton (eigenes Root-Zertifikat). Deshalb scheitern `uv`/`npm`/Docker-Builds ohne Zusatz. Lokal gesetzt: `UV_SYSTEM_CERTS=1`, `NODE_OPTIONS=--use-system-ca`. Für Docker-Builds gibt es das optionale Build-Secret `extra_ca` im Dockerfile; die lokale Datei `.local/extra-ca.pem` (nur das öffentliche Norton-Root-Zertifikat) und `docker-compose.override.yml` sind gitignored und gehören nur auf diesen PC. Auf dem Server ist beides nicht nötig.
- `docs/phase-prompts.md` nennt als Deployment-Ziel `/srv/cat`; maßgeblich ist `CLAUDE.md` (`/srv/homelm`).

**Offene Punkte**
- Weboberfläche hat noch **keine Authentifizierung** (kommt mit Phase 1, bevor ein anderer Bind als `127.0.0.1` verwendet wird).
- Host-Port: 8080 gehört auf dem Server openHAB, Cat nutzt deshalb 8090 (Inventar vom 2026-10-17).
- `fastapi.testclient` meldet eine Deprecation-Warnung zu `httpx`; später beobachten.

**Rollback**
- Lokal: `docker compose down` und Ordner löschen. Auf dem Server wurde noch nichts verändert.

## Phase 1: UI-Layout und WebSocket

**Gebaut**
- Login: `POST /api/login` (Passwort aus `CAT_PASSWORD`, Vergleich zeitkonstant), signiertes Sitzungs-Cookie (HttpOnly, SameSite=Strict, 7 Tage), Sperre nach 5 Fehlversuchen für 60 s, `GET /api/me`, `POST /api/logout`. Ohne Passwort kein Login (503). Das Cookie hat kein `Secure`-Flag, weil Cat im LAN per HTTP läuft; das ändert sich mit HTTPS (Phase 6).
- WebSocket `/ws`: nur mit Sitzung und passendem `Origin`; typisierte Events als Pydantic-Modelle (`backend/src/cat/ws/protocol.py`), TypeScript-Spiegel in `frontend/src/protocol.ts`, Beschreibung in `docs/protocol.md` (ein Test hält alle drei synchron). Beim Verbinden wird Chatverlauf, Stage und Widget-Stand erneut gesendet.
- Antwort vorerst Echo (wortweise gestreamt). Verlauf liegt im Speicher (Persistenz: Phase 8).
- Frontend: Dashboard mit Header (Status, Uhr/Datum, Wetter-Platzhalter, Abmelden), Widget-Spalte links (Platzhalter), Stage mit animiertem Cat-Orb in der Mitte (idle/listening/thinking/speaking), Chat rechts (Markdown, Leeren, Export als Markdown-Datei). Layout: breit drei Spalten, Tablet Widgets oben und darunter Stage/Chat, schmal untereinander.
- Wiederverbindung mit exponentiellem Backoff (1 s bis 15 s). Ist der Server nur weg, bleibt das Dashboard stehen; nur bei 401 geht es zur Anmeldung.

**Abnahme: bestanden (lokal, im Browser geprüft)**
- Anmelden, Nachricht senden, Echo erscheint live im Chat.
- Backend beendet: Anzeige wechselt auf "Getrennt, verbinde neu"; Backend gestartet: nach wenigen Sekunden wieder "Online" ohne Reload.
- Tests: Backend 19, Frontend 24 (u. a. Reconnect, Reducer, Login-Fehler, Ausfall bleibt im Dashboard).
- Beim Browser-Test gefunden und behoben: Ein Serverausfall warf zunächst fälschlich auf die Anmeldeseite zurück (jetzt nur bei 401; Test ergänzt).

**Offene Punkte**
- Nicht auf dem Server getestet (kein Zugriff): Verhalten des Cookies/Origin-Checks hinter echtem LAN-Hostnamen.
- `CAT_PASSWORD` und `CAT_SESSION_SECRET` müssen vor dem ersten Server-Start in die `.env` eingetragen werden.

## Phase 2: LLM, Tool-Calling und Stage

**Gebaut**
- `backend/src/cat/llm/`: eigene Schnittstelle (`LLMProvider`, `TextDelta`, `ToolCall`, `LLMError`), Implementierung mit LiteLLM (Streaming, Tool-Calls aus Teilstücken zusammengesetzt, Fehler in verständliche deutsche Meldungen übersetzt, ohne Schlüssel oder Interna). Standardmodell `anthropic/claude-haiku-5-5` (LiteLLM kennt es mit Tool-Unterstützung; gegen die Live-API nicht geprüft, siehe offene Punkte). LiteLLM nutzt die mitgelieferte Preisliste (`LITELLM_LOCAL_MODEL_COST_MAP`) und Telemetrie ist aus: kein Abruf von GitHub beim Start, offline lauffähig.
- `agent/`: Tool-Registry (Risikostufe pro Werkzeug schon vorgesehen), Agent-Schleife mit Schrittlimit (`CAT_AGENT_MAX_STEPS`, Standard 6), deutscher Systemprompt (kurz, 1-2 Sätze für Sprache, Stage-Regeln, aktuelle Zeit), Chatverlauf wird auf die letzten 30 Nachrichten begrenzt und normalisiert.
- Stage-Werkzeuge `show_html`, `show_chart`, `show_markdown`, `clear_stage`; Vorfilter (`stage/sanitize.py`: Größenlimits, entfernt iframe/object/embed/base/link/meta-http-equiv/externe Skripte). Die eigentliche Grenze ist die Sandbox im Browser.
- Frontend: HTML in `<iframe sandbox="allow-scripts">` ohne `allow-same-origin`, strikte CSP im Dokument (kein Netzwerk, Bilder nur `data:`), feste postMessage-Schnittstelle (nur `{"type":"cat.ready"}`, nur von diesem Frame). Diagramme mit Chart.js (nur benötigte Teile registriert, wird erst bei Bedarf nachgeladen; gewählt, weil klein, Canvas-basiert und für Balken/Linie/Torte/Ring ausreichend). Markdown mit `react-markdown` + GFM-Tabellen, ohne rohes HTML. Stage-Historie (bis 20) mit Blättern und Leeren; die Historie überlebt ein Neuladen.
- Ohne API-Schlüssel antwortet Cat im Chat mit einer klaren Anleitung statt mit einem Fehler.

**Abnahme (lokal)**
- Mit geskriptetem Pseudo-LLM im Browser geprüft: "Zeig mir eine analoge Uhr als HTML-Grafik" rendert eine laufende Uhr in der Sandbox; ein Balkendiagramm und eine Markdown-Tabelle erscheinen; Blättern (n / m) und Neuladen funktionieren.
- CSP praktisch geprüft: Ein `fetch()` aus dem Uhr-HTML an den eigenen Server wird blockiert (keine Anfrage im Netzwerkprotokoll).
- Tests: Backend 51 (Agent-Schleife mit gemocktem LLM, Stage-Events, Sanitizing, LiteLLM-Teilstücke, End-to-End über WebSocket), Frontend 42.
- **Nicht bestanden / offen: echter Modellaufruf.** Es gibt lokal keinen API-Schlüssel (und er gehört nicht in den Chat), deshalb ist weder die Qualität des erzeugten HTML noch der Modellname gegen die Live-API geprüft. Erster Test nach Eintragen von `ANTHROPIC_API_KEY`: "Zeig mir eine analoge Uhr als HTML-Grafik".

**Offene Punkte**
- Datenschutz: Mit dem Agenten gehen Chatinhalte an Anthropic (so im Plan vorgesehen).
- Docker-Image wächst durch LiteLLM deutlich; `mem_limit` wurde auf 768 MB angehoben (Messung folgt).
- LiteLLM ist eine große Abhängigkeit; die Version ist per `uv.lock` festgenagelt, Updates bewusst und einzeln einspielen.

## Phase 3: Live-Widgets

**Gebaut**
- Plugin-System nach `CLAUDE.md` Abschnitt 10: `plugins/base.py` (`Plugin`-Protokoll mit `start/stop/tools/widgets/intents/refresh`, `WidgetSpec`, `PluginContext`, `BasePlugin`), `PluginManager` (Start/Stopp, ein kaputtes Plugin legt weder Cat noch andere Plugins lahm, Refresh-Routing), Auswahl per `CAT_PLUGINS` (Standard `system,weather`). Plugin-Werkzeuge landen automatisch in der Tool-Registry des Agenten.
- Plugin `system` (psutil): CPU, RAM, Datenträger, Last und Uptime, Push per `widget.update` alle `CAT_SYSTEM_INTERVAL_S` Sekunden (Standard 3). Plattenzugriff im Thread, nichts blockiert den Event-Loop. Fehler erscheinen im Widget. Werkzeug `get_system_status`.
- Plugin `weather` (Open-Meteo, kein Schlüssel): Standort per `CAT_WEATHER_LAT/LON/NAME`, Cache (`CAT_WEATHER_TTL_S`, Standard 600 s), Refresh-Knopf mit Drossel (min. 5 s), deutsche Wettertexte aus WMO-Codes, Fehler sauber im Widget ("Wetterdaten nicht erreichbar (kein Internet?)"), bei Ausfall bleibt der letzte gute Stand sichtbar. Ohne Standort kein Netzwerkzugriff, stattdessen ein Hinweis. Werkzeug `get_weather`.
- Frontend: Widget-Darstellung nach `kind` (System mit Balken ab 85 % gelb/ab 95 % rot, Wetter mit 3-Tage-Vorhersage und Refresh, Uptime), Uhr/Datum im Header (clientseitig), Header zeigt das Wetter kurz an.
- Container: Datenträger-Widget misst die Partition von `/data` (`CAT_DISK_PATH`).

**Abnahme: bestanden (lokal, im Browser geprüft)**
- Werte aktualisieren sich ohne Reload (Cat-Uptime lief im Browser von 12 s auf 16 s; CPU/RAM laufen live).
- Wetter live gegen Open-Meteo abgerufen (mit lokalem CA-Bündel), Refresh-Knopf funktioniert.
- Ausfall getestet: Ohne das CA-Bündel blockiert Norton den Abruf, das Widget zeigt "Wetterdaten nicht erreichbar (kein Internet?)", Header "Wetter: nicht verfügbar", der Rest des Dashboards läuft normal.
- Docker-Stack lokal gebaut und gestartet: `healthy`, Login per API, Chat ohne Schlüssel liefert die Anleitung, Leerlauf ca. 50 MiB RAM.
- Tests: Backend 67, Frontend 53 (Plugins mit gemocktem Netzwerk, Cache und Drossel, Fehlerpfade, Manager-Isolation, Live-Push über WebSocket).
- Beim Testen gefundenen Fehler behoben: Der Refresh-Befehl über WebSocket fragte noch einen nicht vorhandenen Hook ab (Test hat es gezeigt).

**Hinweise**
- Im Container zeigen CPU, RAM, Last und Uptime die Werte des Hosts (bei Docker Desktop die der Linux-VM, daher lokal z. B. 7,7 GB statt 15,9 GB). Auf dem Debian-Server sind es die echten Serverwerte.
- Der Datenträger zeigt nur die Partition des Datenordners, nicht die USB-SSD mit der Nextcloud (rote Linie, wird nicht gemountet).
- Die Last wird unter Windows von psutil nur emuliert (auf dem Server korrekt).
- Der Wetter-Standort fehlt noch (`CAT_WEATHER_LAT/LON` in der `.env`).

**Offene Punkte**
- `.env` auf dem Server anlegen: `CAT_PASSWORD`, `CAT_SESSION_SECRET`, `ANTHROPIC_API_KEY`, Wetter-Koordinaten.
- Noch nicht umgesetzt (brauchen Server bzw. Freigaben): Server-Inventar (Schritt 2), Umsetzungsplan mit Freigabe (Schritt 3), Deployment nach `/srv/homelm`, Caddy-Route, Phase 4 (openHAB, braucht Adresse und Token) ff.

## Deployment Phase 0-3 auf dem Server (2026-10-17)

**Gemacht**
- Der Nutzer hat `catscastle` selbst zur Gruppe `docker` hinzugefügt und `/srv/homelm` angelegt. Inventar mit Docker-Daten: `docs/server-inventory.md`.
- Repo-Stand per `git archive | tar` nach `/srv/homelm` kopiert (ohne `.git`, ohne lokale Dateien). Image **auf dem Server** gebaut (`nice -n 19 ionice -c3`, ca. 2 Minuten, Image 630 MB), weil Docker Desktop auf dem PC die Engine nicht startete. Stack `homelm` mit einem Container `homelm-backend`, `mem_limit 768m`, `cpus 1.0`, Container-Benutzer 1000:1000 (Besitzer von `./data`).
- `/srv/homelm/.env` (Rechte 600) mit Bindung `192.168.0.10:8090`, zufällig erzeugtem `CAT_SESSION_SECRET` (nie angezeigt), Plugins `system,weather`.

**Abnahme: bestanden, mit Einschränkung**
- `/health` vom PC (LAN) erreichbar, `/api/me` ohne Login 401, Login ohne konfiguriertes Passwort 503, `ss` zeigt nur `192.168.0.10:8090`, Docker-Mapping `8000/tcp -> 192.168.0.10:8090`. Cat hat keine Caddy-Route und ist damit nicht über 80/443 erreichbar.
- Andere Dienste unverändert: gleiche Container wie vorher plus `homelm-backend`; Nextcloud (302), Trafficnetwork (200), Portainer aus dem LAN (200), openHAB (200). Cat im Leerlauf ca. 50 MiB; Server frei 5,0 GB, Last ca. 0,9 direkt nach dem Start.
- **Nicht geprüft:** Erreichbarkeit "von außen". Dafür fehlt ein Standpunkt außerhalb des Hauses. Cat lauscht nur auf der LAN-Adresse und hat keine Caddy-Route; ob der Router Port 8090 weiterleitet, sollte der Nutzer kurz in der Router-Oberfläche prüfen (keine Weiterleitung nötig und keine eingerichtet, soweit bekannt).
- **Noch offen für Login/Chat:** `CAT_PASSWORD` und `ANTHROPIC_API_KEY` in `/srv/homelm/.env` (als Kommentarzeilen vorbereitet), Wetter-Koordinaten, danach `docker compose up -d --no-build`.

**Rollback**
- `cd /srv/homelm && docker compose down` (ohne `-v`) stoppt Cat, nichts anderes ist betroffen. Image entfernen: `docker image rm homelm-backend`. Dateien in `/srv/homelm` löschen ist optional.

## Phase 4: Geräte (openHAB, Home Assistant gegen Mocks)

**Gebaut**
- Gemeinsames Gerätemodell und **Allowlist** `data/config/devices.yaml` (nur dort aufgeführte Geräte existieren für Cat; fehlerhafte Datei = keine Geräte). Risikostufen mit festen Untergrenzen je Typ (Schlösser, Türen, Garagen immer `high`, nicht absenkbar). Dokumentation: `docs/devices.md`, Beispiel `docs/devices.example.yaml`.
- **Steuerungsmodus** `CAT_DEVICE_CONTROL`: `readonly` (Standard), `test`, `full`. Prüfreihenfolge im Backend für Chat, Sprache und Panel gleich: Allowlist, Modus, Befehl, Bestätigung (nur `high`), erst dann das Backend.
- **Bestätigung im Backend erzwungen** (`confirm.request`/`confirm.response`/`confirm.resolved`): einmalige IDs, Ablehnung, Timeout (60 s) und fehlende Oberfläche ergeben "nicht ausgeführt".
- **Audit-Log** `data/audit.jsonl` für jeden Tool-Aufruf (auch Fehler und unbekannte Werkzeuge) und jeden Panel-Befehl, mit Maskierung und Kürzung.
- Plugin `openhab` (REST lesen/senden, SSE für Änderungen, Wiederverbindung, offline-Markierung) und Plugin `homeassistant` (REST + WebSocket nach der aktuellen HA-Dokumentation, nur Mocks, nicht aktiv). Werkzeuge `list_devices`, `get_state`, `set_state`, `show_devices`.
- Frontend: Geräte-Panel auf der Stage (Schalter, Dimmer-Regler, Rollladen, Thermostat, Schloss/Tür/Garage) mit Live-Zuständen, Geräte-Karte in der Widget-Spalte, Bestätigungsdialog (Fokus auf "Abbrechen", Escape lehnt ab, Ablauf lehnt ab).

**Abnahme**
- **Lesen gegen das echte openHAB: bestanden.** Lokal gestartetes Cat las die Zustände von 6 Test-Items vom Server (Licht, Dimmer, Rollo, Temperatur, Leistung), Leistungswerte änderten sich live per SSE (351,7 W, 352 W, 352,4 W).
- **Steuern gesperrt: bestanden.** Ein am Panel vorbei per WebSocket gesendeter Befehl wurde im Modus `readonly` abgelehnt, das echte Licht blieb aus (per REST gegengeprüft), der Versuch steht im Audit-Log.
- **"high" verlangt Bestätigung: bestanden (Tests).** Backend-Tests prüfen Zustimmung, Ablehnung, Timeout, fehlende Oberfläche, gefälschte und doppelte IDs; kein Pfad erreicht das Backend ohne Zustimmung.
- **Nicht geprüft: Schalten einer Test-Lampe per Chat gegen echtes openHAB.** Das braucht Ihre Freigabe (Modus `test` und ein als `test: true` markiertes Gerät, siehe offene Punkte). Gegen den Fake-Server ist es getestet.
- Tests: Backend 163, Frontend 71.

**Gefundene und behobene Fehler**
- Plugin markierte Geräte als offline, sobald ein SSE-Strom sauber endete (Flackern); jetzt nur noch bei Fehlern.
- Rollladen-Skala: openHAB 0 % = offen, Home Assistant 0 % = zu. Cat meldet überall "Prozent geschlossen" und rechnet bei HA um.
- openHAB-`Color`-Items liefern "H,S,B": Cat zeigt die Helligkeit.

**Offene Punkte**
- Entscheiden, welche Geräte Cat sehen darf (Vorschlag in `docs/devices.example.yaml`; auf dem Server liegt zunächst diese Auswahl harmloser Items, Modus `readonly`).
- Für Phase-4-Abnahme "Test-Lampe per Chat": Testgerät nennen, Modus `test` freigeben.
- Eine offene Rückfrage geht bei einem Verbindungsabbruch des Browsers verloren (der Server lehnt nach 60 s selbst ab, sicher).

## Phase 5: Fast-Path-Intents

**Gebaut**
- `backend/src/cat/intents/`: Textaufbereitung (Umlaute/ß, Füllwörter, Zahlwörter bis 100), Regel-Parser für An/Aus, Helligkeit, Rollläden, Heizung, Temperatur lesen, Zustand abfragen, Türen/Garage; Wortschatz in `synonyms.yaml` (plus Nutzerdatei `data/config/synonyms.yaml`); Raum- und Namenszuordnung mit rapidfuzz. Doku und Beispiele: `docs/intents.md`.
- Läuft **vor** dem Agenten (`dialog.py`) und über dieselben Prüfungen wie die Tools (Modus, Allowlist, Bestätigung bei `high`, Audit mit Quelle `fastpath`). Kein Raten: bei Mehrdeutigkeit, unbekanntem Raum oder Nicht-Gerätebefehl übernimmt der Agent. Standardraum (für Satelliten, Phase 7) vorbereitet.
- Antworten kurz und natürlich ("Okay, Küchenlicht ist an.").

**Abnahme: bestanden (Tests und Messung)**
- "Mach das Licht im Wohnzimmer an" bzw. "Mach das Licht in der Küche an" läuft ohne LLM-Aufruf (Ende-zu-Ende-Test mit einem LLM-Fake, der bei einem Aufruf fehlschlagen würde; ein unklarer Satz geht danach an den LLM).
- **Verarbeitungszeit** (Parser und Zuordnung): Median **0,11 ms** (13 Geräte), 0,9 ms (301 Geräte), Maximum 15,9 ms, also weit unter 100 ms. Der Backend-Aufruf kommt dazu.
- 37 Befehls- und Abfragesätze (inkl. Füllwörter, Umgangssprache, Zahlwörter) und 11 Abgabefälle parametrisiert getestet; Backend jetzt 242 Tests.
- **Nicht geprüft:** Erkennungsqualität mit echter Sprache (kommt erst mit Phase 6/7); Satzmuster gegen Ihre echten Gerätenamen (die Allowlist ist noch vorläufig).

**Gefundene und behobene Fehler**
- YAML liest die Schlüssel `on`/`off` als Wahrheitswerte: An/Aus-Wörter waren leer (Test hat es sofort gezeigt). Datei quotiert, Loader fängt es auch bei Nutzerdateien ab.
- Zusammengesetzte Raumwörter ("Terrassenlampen") verdeckten die Geräteklasse.

## Phase 8: Second Brain

**Gebaut**
- `memory/notes.py`: Markdown-Notizen mit Frontmatter unter `data/memory/<thema>/<titel>.md` (Quelle der Wahrheit, Pfadschutz, Größen- und Mengenlimits, gleiche Titel ergänzen). `memory/index.py`: SQLite-FTS5-Index als Wegwerf-Cache, gleicht sich bei jeder Suche mit den Dateien ab; Wortanfangs-Suche statt Stemmer; `VectorIndex`-Schnittstelle vorbereitet. `memory/service.py`: Werkzeuge `memory_search`, `memory_write`, `memory_list`, Kontext für den Prompt, Ablehnung von Geheimnissen. `memory/sessions.py`: Sitzungsverlauf als JSONL und Zusammenfassung alter Sitzungen in Notizen. Doku: `docs/memory.md`.
- Agent: relevante Erinnerungen werden vor der Antwort lokal gesucht und in den Systemprompt gegeben (`system_extra`); der Prompt erklärt, wann geschrieben wird.

**Abnahme: bestanden (Tests)**
- "Merk dir, dass ich Kaffee ohne Zucker trinke" wird als Datei `vorlieben/kaffee.md` gespeichert; in einer **neuen App-Instanz** (Neustart) mit **anderem Modell** (anderer Fake-Anbieter) landet die Erinnerung beim Satz "Wie trinke ich meinen Kaffee?" im Prompt, bei einer unabhängigen Frage nicht. Ein Test löscht außerdem die Index-Datei, danach wird aus den Dateien neu aufgebaut.
- Backend 265 Tests.
- **Nicht geprüft:** Verhalten mit dem echten Modell (kein API-Schlüssel), Trefferqualität bei vielen Notizen, Zusammenfassung gegen die Live-API.

**Gefundene und behobene Fehler**
- SQLite-Verbindungen wurden nach `with` nicht geschlossen (Datei blieb offen; unter Windows ein Fehler, unter Linux ein Handle-Leck). Jetzt immer geschlossen.
- Mein Muster gegen Geheimnisse enthielt durch einen Patch-Fehler ein Backspace-Zeichen statt `\b`; der Test hat es sofort gezeigt.

**Offene Punkte**
- Notizen und Sitzungsverläufe liegen im Klartext in `data/`: in die Sicherung aufnehmen.

## Phase 9: Offline-Fallback, Sandbox, eigene Integrationen

**Gebaut**
- **Offline-Fallback** (`llm/fallback.py`, Doku `docs/offline.md`): `FallbackProvider` schaltet auf ein lokales Modell (Ollama, Standardvorschlag `ollama/qwen3:4b`), wenn der Cloud-Anbieter **nicht erreichbar** ist (nicht bei falschem Schlüssel oder Modellnamen, nie mitten in einer Antwort), mit 60 s Abkühlzeit, damit nicht jede Nachricht in den Timeout läuft. Qwen3-Denkblöcke werden entfernt (`ThinkFilter`, `/no_think`). Neues Ereignis `provider.state`; der Kopf zeigt "Modell: ..." bzw. gelb **"Offline-Modell: ..."**. Der Ollama-Container (`mem_limit 3,5 GB`, Modell entlädt nach 2 Minuten) liegt hinter dem Compose-Profil `offline`.
- **Code-Sandbox** (`sandbox/`, `cat/sandbox/`, Doku `docs/sandbox.md`): Tool `run_python` in eigenem Container ohne Netzwerk, schreibgeschützt, ohne Capabilities, 512 MB, 64 Prozesse; Datei-Austausch statt Docker-Socket; Text und PNG-Diagramme gehen an Modell bzw. Stage.
- **Eigene Integrationen** (`plugins/pending.py`, `plugins/external.py`, Doku `docs/plugins-pending.md`): `propose_plugin` legt Vorschläge nur in `data/plugins/pending/` ab; geladen wird nur von Hand Freigegebenes aus `active/`, und nur wenn es in `CAT_PLUGINS` steht.

**Entscheidung zum RAM (wie vom Nutzer vorgegeben):** Der Server hat 7,5 GB RAM (kein Upgrade), davon verfügbar rund 5 GB inklusive Datenbank-Cache, bei bereits belegtem Swap. Ein geladenes Qwen3-4B braucht 3 bis 3,5 GB. Der Fallback ist daher **vorerst deaktiviert** (`CAT_FALLBACK_MODEL` leer, Ollama-Container nicht gestartet). Die Umschaltlogik ist vollständig gebaut und getestet, sie wird mit einem RAM-Upgrade nur noch eingeschaltet (Schritte in `docs/offline.md`). Fast-Path und Geräteanzeige laufen auch ohne Internet.

**Abnahme (lokal, Tests): bestanden**
- Cloud nicht erreichbar -> Fallback antwortet, Anzeige wechselt auf "Offline-Modell", nach der Abkühlzeit zurück; Konfigurationsfehler werden nicht verdeckt (Backend-Tests, inkl. WebSocket-Ende-zu-Ende).
- Python-Code nur über den Sandbox-Client, nie im Cat-Prozess; Ergebnis, Fehler, Zeitlimit, Bilder, tote Sandbox getestet. Ein erzeugtes Plugin ist ohne Freigabe inaktiv (auch bei Eintrag in `CAT_PLUGINS`), Vorschläge werden nie ausgeführt.
- Backend 309 Tests (1 übersprungen: der echte Worker braucht POSIX, wird auf dem Server in Docker geprüft).
- **Nicht geprüft:** Ollama/Qwen3 mit echtem Modell (bewusst nicht aktiviert, siehe RAM-Entscheidung; Antwortzeit und Qualität bleiben unbekannt), "Internet getrennt" am echten Server.

**Gefundene und behobene Fehler**
- `ThinkFilter` gab einen zurückgehaltenen Tag-Anfang am Ende nie frei (Antwort "x <th" verlor Text): `flush()` ergänzt.

## Deployment Phase 4-9 auf dem Server (2026-10-17)

**Gemacht**
- Repo-Stand nach `/srv/homelm`, Images auf dem Server gebaut (`nice -n 19 ionice -c3`): `homelm-backend` (646 MB) und `homelm-sandbox` (416 MB). Stack `homelm` besteht jetzt aus `homelm-backend` und `homelm-sandbox`; Ollama bleibt hinter dem Profil `offline` und läuft **nicht**.
- Cat hat ein festes Subnetz (`172.28.250.0/24`); die Container-Liste der übrigen Dienste ist vor und nach jedem Deployment unverändert geblieben. Cat im Leerlauf ca. 52 MiB, Sandbox ca. 7 MiB; Server-Last 0,2 bis 0,5, frei ca. 5 GB.
- Auf dem Server liegt eine vorläufige Allowlist `data/config/devices.yaml` (6 harmlose Items, Kopie von `docs/devices.example.yaml`), Modus `CAT_DEVICE_CONTROL=readonly`.

**Sandbox auf dem Server geprüft (über den Cat-Client): bestanden**
- Rechnen, Fehlerausgabe und ein matplotlib-Diagramm (1 Bild, ca. 1 s) funktionieren.
- Kein Netzwerk (`socket` scheitert mit OSError), kein DNS (gaierror), Dateisystem schreibgeschützt, Umgebung ohne Secrets, 900-MB-Allokation endet mit MemoryError, Endlosschleife wird nach dem Zeitlimit beendet (SIGKILL), Fork-Bombe stoppt beim Prozesslimit (61 Kinder), danach nur 5 Prozesse im Container.
- Gefundener Fehler: Verwaiste Kindprozesse blieben als Zombies stehen (der Worker war PID 1 ohne Reaper) und füllten das Prozesslimit dauerhaft; `docker exec` und neue Aufträge scheiterten. Behoben mit `init: true` und `killpg` nach jedem Auftrag, erneut geprüft.
- Im Container sind `/srv` und `/mnt` leere Basisordner, keine Hausdaten.

**Noch offen (braucht den Nutzer)**
1. **ufw-Regel** für den Weg Cat -> openHAB (sonst bleiben alle Geräte "offline"): `sudo ufw allow from 172.28.250.0/24 to any port 8080 proto tcp comment 'HomeLM zu openHAB'`. Cat zeigt bis dahin im Log "openHAB ist nicht erreichbar".
2. In `/srv/homelm/.env` eintragen (Variablennamen, nie im Chat): `CAT_PASSWORD`, `ANTHROPIC_API_KEY`; Wetter: `CAT_WEATHER_LAT`, `CAT_WEATHER_LON`, `CAT_WEATHER_NAME`. Danach `cd /srv/homelm && docker compose up -d --no-build`.
3. Entscheidungen: welche Geräte Cat sehen darf (Allowlist), Test-Lampe für die Abnahme "per Chat schalten", Modus `test`/`full`.
4. RAM-Upgrade (16 GB) für den Offline-Fallback.

**Rollback**
- Phase 4 bis 9 zurücknehmen: ältere Image-Stände gibt es nicht als Tag; Rollback = Repo auf einen früheren Commit zurücksetzen (z. B. `06ae227` = Phase 0-3), neu kopieren und `docker compose build && docker compose up -d --no-build`. Cat stoppen: `cd /srv/homelm && docker compose down` (ohne `-v`), das beendet beide Container und berührt nichts anderes.

## Phase 6: Sprachpipeline

**Gebaut**
- `backend/src/cat/voice/`: `vad.py` (Silero-VAD v6 als ONNX direkt mit onnxruntime, ohne torch; Segmentierung mit Hysterese, Vorlauf, Mindestlänge, einstellbarer Pause, Zeitlimit), `stt.py` (faster-whisper, int8, eigener Thread mit `nice`, Warmlauf, Filter gegen erfundene Standardsätze), `tts.py` (Piper, deutsche Stimme, satzweise), `sentences.py` (Satzteiler für den Strom des LLM), `pipeline.py` (`VoiceEngine`, `VoiceSession`: Halbduplex, STT -> Dialog -> TTS, Latenzmessung je Stufe), `setup.py` (Modelle laden, Hinweistext mit Raum- und Gerätenamen).
- `ws/voice.py`: WebSocket `/ws/voice` und `GET /api/voice` (Protokoll: `docs/voice-protocol.md`). Der Dialog liefert jetzt ein `Reply` (Antworttext, Zeit bis zum ersten Wort) und streamt Textteile an die Sprachausgabe; Antworten für Sprache bekommen die Vorgabe "1 bis 2 Sätze, kein Markdown".
- Frontend: Mikrofon-Knopf im Chat (AudioWorklet auf 16 kHz PCM16, Wiedergabe der Antwort, Latenzanzeige). Bei `http://<IP>` ist der Knopf gesperrt und erklärt es (Browser verlangen HTTPS oder localhost).
- Testwerkzeug `scripts/voice_roundtrip.py` (WAV oder `--say` durch die ganze Pipeline, Antwort als WAV, Latenzen), Vorladen der Modelle mit `scripts/download_models.py`. Doku: `docs/voice.md`.

**Abnahme (lokal, echte Modelle): bestanden**
- Gesprochen "Wie warm ist es draußen" (von Piper erzeugt) -> Silero erkennt Beginn und Ende -> Whisper base erkennt den Satz -> der Fast-Path liest den **echten** Außentemperatur-Wert aus Ihrem openHAB (12,21 °C) -> Piper spricht die Antwort in 4,1 s. Latenz ab Ende der Äußerung: Erkennung 394 ms, erstes Wort 413 ms, **erstes Audio 525 ms** (plus die eingestellte Pause von 1,5 s bis zum Sprachende).
- Tests: Backend 335 (davon 1 mit echten Modellen: Sprache -> VAD -> STT, und Stille ergibt keinen Text), Frontend 90.

**Gefundene und behobene Fehler**
- Der Satzteiler trennte "z. B." (Ausnahme saß an der falschen Stelle des Regex).
- Whisper base hört "Küche" als "Kiche"; der Hinweistext mit Raumnamen ist dafür da (auf dem Server gegen `small` zu messen).
- Windows-Eigenheit in Tests: Timer unter 15 ms feuern sofort, daher scheinbare Null-Zeiten; Tests nutzen jetzt 50 ms.

## Phase 7: Satellit

**Gebaut**
- **Server:** `satellites.py` (Register in `data/config/satellites.yaml`: je Satellit ID, Raum, **SHA-256-Hash** des Tokens, nie Klartext; kaputte Datei = niemand kommt herein; Sperre nach 10 Fehlversuchen), Anmeldung am `/ws/voice` per `Authorization: Bearer` (Browser weiter per Cookie), **Raum aus der Registrierung** (der Satellit kann ihn nicht selbst festlegen), `GET /api/satellites`, mehrere Satelliten gleichzeitig (Anfragen werden nacheinander bedient, Sprache wartet bis zu 30 s auf ein laufendes Gespräch). `scripts/satellite_token.py` legt Satelliten an und zeigt das Token genau einmal.
- **Satellit** (`satellite/`, eigenes Paket, Python 3.11, systemd-Dienst): `config.py` (Validierung, `ws://` nur im lokalen Netz), `audio.py` (Mikrofon/Lautsprecher über sounddevice, Signalton), `wakeword.py` (openWakeWord mit ONNX; mitgelieferte Modelle zum Testen, eigenes Modell möglich), `client.py` (Zustandsmaschine WAKE -> BEEP -> STREAM -> THINK -> PLAY; vor dem Wake-Word verlässt kein Audio das Gerät; "Continue conversation" nach Rückfragen; Sperrzeit gegen Selbstauslösung; Watchdog; Wiederverbindung mit wachsender Wartezeit 2 bis 30 s), `__main__.py` (`--list-devices`, `--test-speaker`, `--test-mic`).
- Anleitungen: `docs/satellite.md` (Pi einrichten, Schritt für Schritt), `docs/wakeword.md` (eigenes "Hey Cat" trainieren nach der openWakeWord-Dokumentation), Protokoll `docs/voice-protocol.md`.

**Abnahme**
- **Bestanden (Tests, echter Server + echter Satelliten-Code mit simuliertem Audio):** Anmeldung per Token, Wake-Word -> Streaming -> gesprochene Antwort -> zurück in den Wartezustand; der Raum des Tokens bestimmt "Licht an" (ein Satellit, der sich als "Flur" ausgibt, schaltet trotzdem die Küche); zwei Satelliten gleichzeitig, jeder bekommt seine Antwort; falsches Token abgewiesen, Sperre nach Fehlversuchen; Token-Skript und Server-Register passen zusammen.
- Tests: Backend 351, Satellit 28.
- **Nicht abgenommen:** "Hey Cat, schalte das Licht an" im Raum. Es fehlt echte Hardware (Pi, Mikrofon, Lautsprecher) und ein trainiertes "Hey Cat"-Modell. Ungeprüft sind echtes Audio über `sounddevice`, openWakeWord auf einem echten Pi, die systemd-Einheit und die Hörqualität im Raum.

**Gefundene und behobene Fehler**
- Die Sperrzeit gegen Selbstauslösung wurde schon beim Verbinden gesetzt (hätte mit unbewegter Uhr jede Auslösung geschluckt); gilt jetzt nur nach einem beendeten Gespräch.

**Offene Punkte**
- Raspberry Pi, USB-Konferenzlautsprecher, `docs/satellite.md` durchgehen; "Hey Cat" trainieren (`docs/wakeword.md`).

**Messung und Abnahme auf dem Server (2026-10-17)**
- Modelle werden beim ersten Start automatisch geladen (Whisper von huggingface.co, Stimme von huggingface.co/rhasspy/piper-voices; reine Downloads, 666 MB in `data/models` bei `small`). Bereit nach 5 s (Modelle vorhanden) bzw. 21 s (mit Download).
- **STT-Wahl nach Messung:** `small` (siehe Tabelle in `docs/voice.md`): 2,4 bis 2,6 s Erkennung, 3 von 4 Testsätzen wortgetreu; `base` 1,2 bis 1,6 s, aber 2 von 4 falsch. Preis: ca. 950 MiB RAM für Cat statt 430 MiB.
- **Gesprochene Frage rein, gesprochene Antwort raus: bestanden.** Erst mit `scripts/voice_roundtrip.py` im Container, dann mit dem **echten Satelliten-Code von diesem PC über das LAN zum Server** (Token, Wake-Word simuliert, Frage von Piper gesprochen, Whisper small erkennt "Wie warm ist es draußen?", Fast-Path, Piper-Antwort mit 2,4 s Audio zurück). Latenz dieses Laufs ab Ende der Äußerung: Erkennung 1,9 s, erstes Audio 4,1 s (davon 2 s Warten auf das nicht erreichbare openHAB), dazu 1,5 s Pause bis zum Sprachende.
- Die Antwort lautete "Außentemperatur ist gerade nicht erreichbar.", weil die ufw-Regel für den Weg zu openHAB noch aussteht (Fehler wird sauber gesprochen statt zu hängen; Verbindungsversuch gibt nach 2 s auf).
- Der Test-Satellit wurde danach wieder aus `satellites.yaml` entfernt; ein anderes Token wird vom Server abgewiesen.

**Endzustand Server:** Container `homelm-backend` (ca. 950 MiB) und `homelm-sandbox` (ca. 4 MiB), die zwölf übrigen Container unverändert (Up 3 bis 6 Tage). RAM verfügbar ca. 3,9 GB, Swap 690 MB, Last 0,6, Platte 41 % (128 GB frei, Cat-Daten 666 MB, Docker-Images 7 GB gesamt).


## Phase 10: Lokal zuerst, Claude nur für den Rest (2026-10-17)

Auftrag des Nutzers (ausdrücklich): Claude über das Abo einbinden (keinen API-Schlüssel kaufen), das lokale Modell aktivieren und testen, das lokale Modell hat Priorität 1, Claude nur für das, was es nicht kann, Second Brain einrichten (falls noch nicht) und Claude lesenden Zugriff geben. Diese Anweisung ersetzt meine frühere Empfehlung gegen den Abo-Weg. Grundlage sind Hilfecenter und CLI-Doku (Stand 07.10.2026: `claude -p` zählt gegen das Abo-Limit, nur persönlicher Gebrauch, kein Auslesen von Anmeldedaten).

**Gebaut**
- `llm/ollama.py`: eigener Client für Ollamas native API (`/api/chat`): `think:false`, `num_ctx`, `num_thread`, `keep_alive`, Werkzeugaufrufe mit Argumenten als Objekt, ThinkFilter, Fehler als `LLMError(unavailable)`. Bewusst ohne LiteLLM (Optionen je Anfrage, weniger Abhängigkeiten im Pfad).
- `agent/router.py` (`RoutedResponder`), `agent/prompt.py` (kompakter lokaler Prompt, Kontext vor der Nutzernachricht), `agent/loop.py` (`escalate_tool`, `extra_in_user`), `agent/tools.py` (`Escalation`, `ToolRegistry.only`): lokal zuerst; Weitergabe an Claude bei `ask_claude`, ausdrücklicher Bitte, Ausfall, zu vielen Schritten oder leerer Antwort. Der Fast-Path läuft davor und fragt nie Claude.
- `claude/` (`bridge.py`, `budget.py`, `text.py`): Brücken-Client, Tageslimit (`data/claude-usage.json`) mit Pausen nach Limit- oder Anmeldefehler, Prompt-Bau (Gespräch plus Gedächtnis-Treffer), ```html-Blöcke gehen auf die Stage, Fußzeile "Antwort von Claude".
- `claude-bridge/` (Node, ohne Abhängigkeiten) und Compose-Dienst `claude-bridge` (Profil `claude`): Claude-Code-CLI 2.1.302 festgenagelt, `--restricted`, nur `Read/Grep/Glob` auf das schreibgeschützt eingehängte Gedächtnis, `dontAsk`, ohne MCP und Sitzungsspeicher, ein API-Schlüssel wird nie weitergereicht, Token nur in `claude.env`. Container: read_only, cap_drop ALL, 768 MB, 1 CPU, kein veröffentlichter Port.
- Anzeige: Kopf zeigt "Claude antwortet: sonnet" während einer Weitergabe; Audit-Eintrag `claude_escalation` je Frage.
- `scripts/local_eval.py` (Prüfung mit echten Fragen auf einer Datenkopie), Doku `docs/claude.md`, `docs/offline.md` neu (Messwerte, Korrektur `ollama_chat/` und Modellwahl), `CLAUDE.md` angepasst.

**Second Brain:** war bereits eingerichtet (Phase 8, `docs/memory.md`). Neu: lesender Zugriff für Claude auf zwei Wegen (Treffer im Prompt plus schreibgeschützter Ordner in der Brücke). Schreiben bleibt beim lokalen Agenten.

**Messung lokales Modell (Server, 2026-10-17)** (Tabelle in `docs/offline.md`)
- `qwen3:4b` (der aktuelle Tag ist das Thinking-Modell) war unbrauchbar: 440 s für "Hallo, wer bist du?", `think:false` wird ignoriert. `qwen3:4b-instruct-2507-q4_K_M`: 10 Token/s, einfache Frage 4 bis 5 s, mit Werkzeug 30 bis 50 s, Kaltstart bis 75 s.
- 6 Threads auf `cpus: 3` drosselten auf 2,4 Token/s; mit 3 Threads sind es 10 Token/s.
- RAM: Ollama 3,06 GiB, danach ca. 1,2 GB verfügbar, kein Speicherdruck (PSI 0), kein Swap-Verkehr, Nextcloud `status.php` unverändert 15 ms. Knapp: das RAM-Upgrade bleibt die wichtigste Verbesserung.
- Qualität (7 Testfragen): Rechnen, Geräteliste und Gedächtnis schreiben/lesen korrekt. Gedicht und lange Geschichte mäßig (Deutsch im Detail schwach), "animierte Uhr" ohne Claude nicht lösbar: genau die Fälle für Claude. Gefundene Schwäche: Antwort in der Ich-Form statt "du" (Prompt nachgebessert, nicht erneut gemessen).

**Abnahme**
- **Bestanden:** Backend 396 Tests (davon 45 neu: Ollama-Client, Router, Claude-Texthilfen, Budget, Brücken-Client), Frontend 91, Brücke 15 (Node, mit Attrappe der CLI). Lokales Modell auf dem Server mit echten Fragen (s. o.). Brücken-Container läuft; die echte CLI nimmt alle Flags an und meldet ohne Token sauber `auth`; das Gedächtnis ist dort schreibgeschützt.
- **Nicht abgenommen:** ein echter Aufruf an Claude. Dafür fehlt das Token des Nutzers (`claude setup-token`, Schritte in `docs/claude.md`). Ob die Flagkombination mit echtem Token wie erwartet antwortet (insbesondere `--restricted` zusammen mit OAuth-Token und `Read/Grep/Glob`), ist **ungeprüft**; bei Problemen ist `CLAUDE_RESTRICTED=0` der erste Schalter.
- openHAB-Verbindung vom Container: seit der ufw-Regel des Nutzers in Ordnung (REST 496 Items, SSE-Strom läuft). Der Wetter-Abruf lieferte einmal 503 von Open-Meteo (vorübergehend).

**Entscheidungen**
- Modell `qwen3:4b-instruct-2507-q4_K_M`, Kontext 4096, 3 Threads, `keep_alive` 10 min (Kompromiss zwischen Wartezeit und RAM).
- Kleine Werkzeugauswahl für das lokale Modell (ohne `show_html`, `propose_plugin`): spart Prompt-Token, die auf der CPU Sekunden kosten; solche Aufgaben gehen an Claude.
- Die Antwort von Claude wird als Ganzes geholt und im Chat in Stücken gezeigt (kein Live-Strom), weil Zwischentexte bei Werkzeugschritten sonst im Chat landen würden.

**Offene Punkte (brauchen den Nutzer)**
1. `claude setup-token` ausführen, Token in `/srv/homelm/claude.env` eintragen, `CAT_CLAUDE_URL=http://claude-bridge:8099` in `.env`, Brücke und Cat neu starten (`docs/claude.md`, Abschnitt "Einrichten").
2. Entscheidung, ob die Notizen für Claude lesbar sein sollen (`CAT_CLAUDE_MEMORY`, Standard an).
3. RAM-Upgrade; Allowlist-Auswahl, Test-Lampe, Modus `test`/`full` (Phase 4); HTTPS für das Browser-Mikrofon; Raspberry Pi.

**Rollback**
- Lokal zuerst aus: `CAT_LOCAL_MODEL` in `.env` leeren, `docker compose up -d --no-build backend` (alter Cloud-Modus). Claude aus: `CAT_CLAUDE_URL` leeren und `docker compose --profile claude stop claude-bridge`. Ollama stoppen: `docker compose --profile offline stop ollama`. Die Modelle liegen in `data/ollama` (eigener Ordner). Code: Stand vor Phase 10 ist Commit `840b15e`.
