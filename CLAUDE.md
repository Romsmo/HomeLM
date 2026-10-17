# CLAUDE.md: Projekt HomeLM (Assistent "Cat")

Das Repo heißt **HomeLM**, der Assistent darin heißt **Cat**. Cat ist ein eigener Home-Assistent mit Weboberfläche (Chat, Stage für KI-Grafiken, Widgets), Plugins für openHAB und Home Assistant und einem eigenen Sprachassistenten für Satelliten. Er läuft auf dem Heimserver des Nutzers per Docker Compose. Ausführlicher Plan: `docs/cat-plan.md`. Phasen-Prompts: `docs/phase-prompts.md`.

Bei Widersprüchen gilt diese Datei vor `cat-plan.md` und `phase-prompts.md`. Abweichungen zum Plan:

- **openHAB zuerst.** Home Assistant läuft laut Nutzer (Stand) nicht auf dem Server. Das HA-Plugin wird gegen Mocks gebaut und erst aktiviert, wenn der Nutzer bestätigt, dass HA existiert.
- **Deployment** nach `/srv/homelm` als eigener Compose-Stack, nicht in die bestehenden Stacks hinein (siehe unten).
- **Lokal zuerst** (ausdrückliche Anweisung des Nutzers, 2026-10-17): Das lokale Modell (Ollama, `qwen3:4b-instruct-2507-q4_K_M`) ist Priorität 1 und beantwortet alles, was es kann. **Claude wird nur für das gefragt, was das lokale Modell nicht kann**, und zwar über das Claude-Abo des Nutzers (Claude Code CLI in einem eigenen Container, kein bezahlter API-Schlüssel). Details und Grenzen: `docs/claude.md`. Der frühere Plan (Cloud-API primär, Ollama als Fallback) gilt nur noch, wenn `CAT_LOCAL_MODEL` leer ist.

## 1. Arbeitsmodus: autonom, mit gezielten Rückfragen

Du führst die Phasen 0 bis 9 selbstständig nacheinander durch. Du fragst nicht bei Routine, aber du fragst (gebündelt, mit dem Fragetool, mit Empfehlung als erste Option), wenn:

- Zugang oder Information fehlt (SSH, Repo, Tokens, Hardware, Hostname).
- eine Entscheidung laufende Dienste berührt (siehe Abschnitt 3).
- es mehrere sinnvolle Wege mit spürbar unterschiedlichen Kosten, Risiken oder Aufwand gibt.
- ein Schritt nur der Nutzer tun kann (Hardware, Router, Secrets eintragen, physisches Gerät).
- du dir bei einer API oder einem Verhalten nicht sicher bist und es nicht per Doku oder Test klären kannst.

Regeln dazu:

1. **Secrets nie im Chat anfordern oder ausgeben.** Der Nutzer trägt sie selbst in die `.env` auf dem Server ein. Du nennst die genaue Zeile (Variablenname) und prüfst nur, ob sie gesetzt ist, ohne den Wert zu zeigen.
2. **Fortschritt dokumentieren** in `docs/PROGRESS.md`: pro Phase Was gebaut, Abnahme (bestanden/nicht), Entscheidungen, offene Punkte, Rollback-Hinweise.
3. **Commit pro Teilschritt**, eine Phase pro Branch oder klar getrennte Commit-Folge, klare Nachrichten.
4. **Abnahme jeder Phase selbst prüfen** (Tests, Messung, echter Aufruf auf dem Server) und das Ergebnis ehrlich berichten, auch wenn es nicht bestanden ist.
5. **Bei Blockade**: Phase parken, im PROGRESS.md vermerken, an einer unabhängigen Aufgabe weiterarbeiten oder fragen. Nicht raten, nicht umgehen.
6. **Echte Geräte** (Türen, Heizung, Rollläden, Licht im Haus) erst steuern, nachdem der Nutzer das ausdrücklich freigegeben hat. Bis dahin nur Testgeräte oder Lesen.

## 2. Zielumgebung (Stand laut Nutzer, nicht neu geprüft)

**Vor jeder Änderung den echten Zustand verifizieren** und die Ergebnisse in `docs/server-inventory.md` festhalten (ohne Secrets).

- Intel-Server mit Debian 13, feste IP `192.168.0.10` (`eno1`). RAM und CPU sind zu ermitteln (`free -h`, `lscpu`); ursprünglich war von 8 GB die Rede, ein Upgrade war geplant.
- USB-SSD unter `/mnt/intensodrive` (`nofail`). Enthält die Nextcloud-Daten (ca. 223 GB), **es gibt nur diese eine Kopie**. Ein Backup-Job fehlt noch.
- USB-WLAN `wlan0` (192.168.1.78) als IoT-Umgehung an der Haupt-Firewall vorbei, mit eigener nftables-Tabelle `ohtunnel`. Ob es noch läuft, ist unbekannt.
- Docker-Verbund in `/srv/docker` (Zusammenstellung über `COMPOSE_FILE` in der `.env`):
  - **Caddy**: automatisches TLS. `catscastlecloud.de` geht an Nextcloud, `trafficnetwork.link` an `trafficnetwork-server:3000`, `portainer.catscastlecloud.de` ist auf das LAN 192.168.0.x beschränkt, liefert aber vom LAN aus 403 (bekannt). Das zeigt: Die LAN-Beschränkung über die Client-IP hinter Docker ist unzuverlässig. Prüfen, welche Quell-IP Caddy tatsächlich sieht, bevor du dich darauf verlässt.
  - **Nextcloud 33** (App- und Cron-Container), MariaDB 11.4, Redis.
  - **openHAB 4.2.2** im Host-Netzwerk mit seriellem Adapter (Prolific).
  - Cloudflare-DDNS für `trafficnetwork.link`, Portainer.
- Trafficnetwork in `/srv/trafficnetwork`:
  - `server/` ist ein Git-Klon von Romsmo/Trafficnetwork mit `docker-compose.yml`, `.env`, `compose.override.yaml`. Container `trafficnetwork-server-server-1` und `trafficnetwork-server-postgres-1` (PostGIS 16, ca. 12,1 Mio. Tempo-Segmente, 1,55 Mio. Schilder, 45.000 Kameras).
  - `ingestion/` ist ein eigener Container mit eigenem Zustand. **Der Zustand `europe-data` (461 MB) darf nie gelöscht werden.**

## 3. Rote Linien (nie ohne ausdrückliche Freigabe im Chat)

Diese Dinge gehören dem Nutzer und anderen Projekten. Du berührst sie nicht, außer er stimmt der konkreten Änderung zu:

- Container, Volumes, Netzwerke und Konfigurationen von Nextcloud, MariaDB, Redis, Trafficnetwork, ingestion, Portainer, DDNS, openHAB. Lesen ist erlaubt, ändern nicht.
- `/mnt/intensodrive`, Nextcloud-Daten, jegliche Datenträger- und Mount-Änderung.
- Firewall, nftables (`ohtunnel` und alle anderen Tabellen), `wlan0`, Netzwerkkonfiguration, SSH-Konfiguration, sudoers, Benutzer und Gruppen.
- Löschbefehle auf dem Server: `rm -rf`, `docker system prune`, `docker volume rm/prune`, `docker compose down -v`, `docker rm` fremder Container, `git push --force`, `git reset --hard` auf nicht eigenem Stand.
- Neustart des Servers, Neustart fremder Container, Paketupdates des Systems (`apt upgrade`).
- Alles, was Daten aus dem Haus an neue Ziele sendet (neue Cloud-Dienste, Telemetrie). Ausnahme mit ausdrücklicher Freigabe des Nutzers: Fragen an Claude über das Abo (Chatverlauf der Frage und Gedächtnis-Notizen, lesend), begrenzt durch Tageslimit und Audit-Log, siehe `docs/claude.md`.

**Erlaubt ohne Rückfrage:**

- Read-only-Inspektion des Servers: `docker ps`, `docker compose config`, `docker stats --no-stream`, `docker network ls/inspect`, `free`, `df`, `lscpu`, `ss -ltnp`, `journalctl` lesen, Konfigdateien lesen (Secrets nicht ausgeben).
- Alles in `/srv/homelm` und im eigenen Compose-Stack `homelm` (bauen, starten, stoppen, eigene Volumes).
- Git im HomeLM-Repo.

## 4. Eingriffe in bestehende Dienste (Caddy-Route und Ähnliches)

Ein Eingriff in Caddy (neue Route für Cat) ist wahrscheinlich nötig. Vorgehen immer so:

1. Ist-Zustand lesen und kurz beschreiben.
2. Datei mit Zeitstempel sichern (`cp -a datei datei.bak-YYYYMMDD-HHMM`).
3. **Minimalen Diff zeigen und Freigabe holen.**
4. Konfiguration validieren (`caddy validate`) und per Reload (nicht Restart) anwenden.
5. Funktion prüfen, auch dass `catscastlecloud.de`, `trafficnetwork.link` und Portainer weiter wie vorher antworten.
6. Rollback-Schritte in `docs/PROGRESS.md` notieren.

Cat-Netzwerk: Cat läuft in `/srv/homelm` als eigener Compose-Stack. Für die Caddy-Anbindung tritt der Cat-Container einem existierenden Docker-Netzwerk als `external` bei (Namen per `docker network ls` ermitteln, Alias z. B. `cat-server`). Cat darf **nicht** aus dem Internet erreichbar sein: Der Server ist über Caddy öffentlich (80/443), daher muss die Cat-Oberfläche eine eigene Authentifizierung haben, und die Erreichbarkeit nur im LAN muss **getestet** werden (von innen und, soweit möglich, von außen), nicht angenommen. Schlage dem Nutzer die einfachste sichere Variante vor (z. B. Port nur an `192.168.0.10` binden, plus HTTPS im LAN für das Browser-Mikrofon per `tls internal` und LAN-Hostname) und frage vor der Umsetzung.

openHAB läuft im Host-Netzwerk: aus dem Cat-Container erreichbar über `extra_hosts: host.docker.internal:host-gateway` oder `192.168.0.10`. Port und Token prüfen, nichts an openHAB ändern. Lesen zuerst, Steuern erst nach Freigabe.

## 5. Ressourcen schonen

Auf dem Server laufen Postgres/PostGIS mit Millionen Datensätzen, Nextcloud, MariaDB und openHAB. Bevor du Modellgrößen festlegst:

- RAM, CPU-Last und `docker stats` messen und im Inventar festhalten.
- Für alle Cat-Container `mem_limit` und `cpus` setzen, damit ein Fehler in Cat nie Nextcloud oder Trafficnetwork verdrängt.
- STT-Modell (faster-whisper `base` oder `small`, int8) nach Messung wählen und die Wahl begründen. Rechenintensive Schritte laufen mit niedriger Priorität (`nice`).
- Kein Ollama-Fallback aktivieren, wenn der freie RAM dafür nicht reicht. Stattdessen im Bericht darauf hinweisen.

## 6. Stack

- Backend: Python 3.12, FastAPI, asyncio, Pydantic v2, `uv`, `pytest`, `ruff`.
- Frontend: Vite, React, TypeScript (strict), Tailwind, `vitest`.
- Voice: faster-whisper (STT), Piper (TTS), Silero VAD, openWakeWord (Satellit).
- LLM: eigene Schnittstelle in `backend/src/cat/llm/` mit `OllamaProvider` (lokal, native API) und `LiteLLMProvider` (alter Cloud-Modus); Claude über `backend/src/cat/claude/` und den Container `claude-bridge/`.
- Daten: SQLite und Markdown in `data/` (gitignored, auf dem Server in `/srv/homelm/data`).
- Deployment: Docker Compose in `/srv/homelm`.

## 7. Struktur

```
backend/src/cat/{main.py, config.py, ws/, llm/, agent/, intents/, plugins/, voice/, memory/, stage/}
backend/tests/
frontend/
satellite/
data/            # nicht committen
docs/            # cat-plan.md, phase-prompts.md, PROGRESS.md, server-inventory.md, protocol.md, ...
```

## 8. Befehle (bei Abweichung aktualisieren)

- Backend starten: `cd backend && uv run uvicorn cat.main:app --reload` (lokal auf diesem PC: `python -m uv ...`, siehe `docs/PROGRESS.md`)
- Tests: `cd backend && uv run pytest`; Lint: `uv run ruff check . && uv run ruff format --check .`
- Frontend: `cd frontend && npm run dev` / `npm test` / `npm run build`
- Satellit: `cd satellite && uv run pytest` (Pi-Software, `docs/satellite.md`); Token anlegen: `scripts/satellite_token.py`
- Gesamtsystem: `docker compose up --build` (Port standardmäßig nur `127.0.0.1:8090`, siehe `.env.example`)

## 9. Sicherheitsregeln für Cat selbst (verbindlich)

- **Keine Secrets im Code oder Repo.** Nur `.env` (gitignored) plus `.env.example` ohne echte Werte. Secrets nie loggen.
- **Gerätesteuerung** nur über Allowlist. Risikostufen `low`, `medium`, `high`. Bei `high` (Türen, Schlösser, Garage) ist eine ausdrückliche Bestätigung Pflicht (UI oder Sprache), **im Backend erzwungen**, nicht nur im Prompt.
- **Audit-Log** für jeden Tool-Aufruf (Zeit, Tool, Parameter, Ergebnis).
- **KI-generiertes HTML** nur in Sandbox-iframe: `sandbox="allow-scripts"`, ohne `allow-same-origin`, strikte CSP, kein Netzwerk, kein Zugriff auf Token oder Cookies, Kommunikation über feste `postMessage`-Schnittstelle.
- **Code-Ausführung** nur in einem Docker-Container ohne Netzwerk, mit Ressourcenlimits. KI-erzeugte Plugins werden nicht automatisch aktiv, sondern landen in `pending/` und brauchen die Freigabe des Nutzers.
- Weboberfläche mit Authentifizierung. Keine offenen Endpunkte außer `/health`.

## 10. Plugin- und Voice-Konvention

- Jedes Plugin liegt in `backend/src/cat/plugins/<name>/` und implementiert `plugins/base.py` (`start`, `stop`, `tools`, `widgets`, `intents`). Tools haben ein JSON-Schema, eine kurze deutsche Beschreibung und eine Risikostufe. openHAB und Home Assistant liefern Geräte im gemeinsamen Format (Name, Raum, Typ, Zustand, Risikostufe).
- Satellit sendet 16 kHz, 16 Bit, mono PCM per WebSocket, der Server antwortet mit TTS-Chunks. Sprachantworten: 1-2 Sätze, kein Markdown.
- Fast-Path-Intents laufen vor dem LLM und müssen ohne Internet funktionieren.

## 11. Stil

- Code und Bezeichner Englisch, Nutzertexte und Docs Deutsch.
- Type Hints überall, `ruff` sauber, TypeScript strict.
- Asynchron arbeiten, nichts Blockierendes im Event-Loop.
- Nichts erfinden: bei unklaren APIs (openHAB, HA, openWakeWord, Piper, Caddy) die Doku prüfen. Neue Abhängigkeiten kurz begründen.
