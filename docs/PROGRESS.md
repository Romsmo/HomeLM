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
- Host-Port 8080 ist nicht gegen die Belegung auf dem Server geprüft (Schritt 2).
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
