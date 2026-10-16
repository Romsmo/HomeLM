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
