# Projekt "Cat": eigener Home-Assistent auf dem EliteDesk

## 1. Zielbild

Ein eigenes System auf dem HP EliteDesk 800 G4 DM, ohne Home Assistant Assist und ohne Alexa:

- **Weboberfläche** im Stil des JARVIS-Beispielbilds: links Widgets (System, Wetter, Uhrzeit, Uptime), in der Mitte eine große **Stage** für Visualisierungen, rechts der Chat.
- **Stage**: Die KI kann HTML-Grafiken, Diagramme, Karten und Geräte-Panels in der Mitte anzeigen (wie Artifacts bei Claude).
- **Plugins** für Home Assistant und openHAB: Infos auslesen und Geräte steuern.
- **Eigener Sprachassistent "Cat"** für Satelliten (Raspberry Pi o. Ä.), gebaut mit Open-Source-Bibliotheken, aber als eigene Funktion in Cat, nicht über HA Assist.
- **Second Brain**: Gedächtnis liegt außerhalb des Modells und überlebt jeden Modellwechsel.

## 2. Annahmen und Entscheidungen (bitte prüfen)

| Thema | Entscheidung | Begründung |
|---|---|---|
| Hardware | Nur der EliteDesk (i5-8500, keine GPU) | deine Vorgabe |
| RAM | Upgrade auf **16 GB, besser 32 GB** (Dual-Channel) | 8 GB reichen nicht für HA + openHAB + Whisper + Cat + lokales LLM |
| LLM (Hauptgehirn) | **Cloud-API (Claude Haiku)**, austauschbar über eine Provider-Schicht | Ein lokales 4B-Modell schafft auf der CPU nur ca. 4-8 Tok/s und ist im Gespräch deutlich schwächer |
| LLM (Offline) | Optional Qwen3 4B über Ollama als Notfall-Fallback | Cat läuft ohne Internet weiter, mit eingeschränkter Qualität |
| Einfache Befehle | **Lokale Intent-Erkennung ohne LLM** ("Licht an") | Millisekunden statt Sekunden, funktioniert offline |
| Sprachen | Deutsch zuerst | |
| Home Assistant / openHAB | Laufen separat (Docker), Cat spricht nur per API mit ihnen | Cat ersetzt nur Assist, nicht die Smart-Home-Zentrale |
| Weboberfläche | Python (FastAPI) im Backend, React + TypeScript im Frontend | gutes Zusammenspiel mit Claude Code, WebSockets für Live-Daten |

Konsequenz der Cloud-Entscheidung: Gesprächsinhalte gehen an die API, und ohne Internet gilt nur Fast-Path plus lokales Fallback-Modell. Wenn du später eine GPU nachrüstest, ist das nur ein Konfigurationswechsel in der Provider-Schicht.

## 3. Architektur

```
 Satellit (Pi + Mikro/Lautsprecher)          Browser (Chat + Stage + Widgets)
   Wake-Word "Hey Cat" (openWakeWord)                   |
   Audio-Stream per WebSocket                           | WebSocket (JSON-Events)
            |                                           |
            v                                           v
 +------------------------------ Cat-Server (FastAPI, Docker) ------------------------------+
 |  Voice:   VAD (Silero) -> STT (faster-whisper) -> Dialog -> TTS (Piper) -> Audio zurück    |
 |  Dialog:  Fast-Path-Intents  --nein-->  Agent (LLM + Tool-Calling)                         |
 |  Stage:   show_html / show_chart / show_markdown / show_devices                            |
 |  Memory:  Markdown-Notizen + SQLite (FTS5, später Vektoren)                                |
 |  Plugins: homeassistant | openhab | system | weather | websearch | (eigene)               |
 +--------------------------------------------------------------------------------------------+
        |                    |                      |
   Home Assistant        openHAB            LLM-Provider (Cloud / Ollama)
   (REST + WebSocket)    (REST + SSE)
```

### Tech-Stack

| Baustein | Wahl |
|---|---|
| Backend | Python 3.12, FastAPI, asyncio, Pydantic |
| Frontend | Vite, React, TypeScript, Tailwind |
| LLM-Schicht | LiteLLM als Bibliothek (Claude, OpenAI, Ollama hinter einer Schnittstelle) |
| STT | faster-whisper (Modell `small`, int8; `base` falls zu langsam) |
| TTS | Piper (deutsche Stimme, z. B. thorsten) |
| VAD | Silero VAD |
| Wake-Word | openWakeWord (läuft auf dem Satelliten) |
| Datenhaltung | SQLite (Verlauf, Memory-Index), Markdown-Dateien (Notizen) |
| Deployment | Docker Compose auf Debian/Ubuntu Server |
| Reverse Proxy | Caddy (HTTPS im LAN, nötig für Mikrofon im Browser) |

### Projektstruktur

```
HomeLM/
  CLAUDE.md
  docker-compose.yml
  .env.example
  backend/
    pyproject.toml
    src/cat/
      main.py  config.py
      ws/            # WebSocket-Endpunkte Browser + Satellit
      llm/           # Provider-Schicht, Streaming
      agent/         # Agent-Loop, Tool-Registry, System-Prompt
      intents/       # Fast-Path (ohne LLM)
      plugins/       # base.py, homeassistant/, openhab/, system/, weather/, websearch/
      voice/         # vad.py, stt.py, tts.py, pipeline.py, satellite_ws.py
      memory/        # notes.py, index.py
      stage/         # Stage-Objekte, HTML-Sanitizing
    tests/
  frontend/          # Vite + React + TS
  satellite/         # Python-Client für den Pi
  data/              # gitignored: DB, Notizen, Modelle
  docs/
```

## 4. Weboberfläche und Stage

**Layout** (wie dein Bild): Header mit Name, Status, Uhr, Wetter; links Widget-Spalte; Mitte Stage mit Cat-Orb (Zustand: wartet, hört, denkt, spricht); rechts Chat mit Eingabefeld.

**Stage-Objekte** (die KI erzeugt sie über Tools):

| Typ | Inhalt |
|---|---|
| `html` | Beliebiges HTML/CSS/JS, gerendert in einer **Sandbox-iframe** |
| `chart` | Strukturierte Daten (Linie, Balken usw.), gerendert mit Chart-Bibliothek |
| `markdown` | Formatierter Text, Tabellen |
| `devices` | Live-Panel mit Geräten aus HA/openHAB (Schalter, Werte) |
| `image` | Bild oder Kamerabild |

Die Stage hält eine kleine Historie (zurückblättern) und kann per Sprache oder Chat geleert werden.

**Sicherheit für KI-HTML**: `<iframe sandbox="allow-scripts" srcdoc=...>` ohne `allow-same-origin`, strikte CSP im iframe (kein Netzwerk, keine externen Skripte), keine Verbindung zum Cat-API-Token. Die Seite darf nur über `postMessage` mit Cat sprechen, und nur über eine kleine, feste Schnittstelle.

**WebSocket-Events** (Beispiele): `chat.message`, `chat.delta` (Streaming), `stage.show`, `stage.clear`, `widget.update`, `voice.state`, `device.state`, `confirm.request` / `confirm.response`.

## 5. Plugin-System

Jedes Plugin ist ein Python-Paket mit einer festen Schnittstelle:

```python
class Plugin(Protocol):
    name: str
    async def start(self, ctx: PluginContext) -> None: ...
    async def stop(self) -> None: ...
    def tools(self) -> list[Tool]: ...          # für das LLM (Funktionsaufrufe)
    def widgets(self) -> list[WidgetSpec]: ...  # optional, fürs Dashboard
    def intents(self) -> list[IntentSpec]: ...  # optional, Fast-Path
```

- **Home Assistant**: REST + WebSocket-API, Langzeit-Token. Entitäten lesen, Services aufrufen, State-Changes abonnieren.
- **openHAB**: REST-API (Items lesen, Befehle senden), Server-Sent-Events für Änderungen, API-Token.
- **Gemeinsame Geräteschicht**: Beide Plugins liefern Geräte in einem einheitlichen Format (Name, Raum, Typ, Zustand, Risikostufe). Dadurch funktionieren Fast-Path und LLM-Tools unabhängig vom Backend.
- **Allowlist**: Nur ausdrücklich freigegebene Geräte sind für Cat sichtbar (hält den Prompt kurz und begrenzt Schäden).
- **Risikostufen**: `low` (Licht), `medium` (Heizung, Rollläden), `high` (Türen, Schlösser, Garage). Bei `high` immer Rückfrage ("Soll ich die Haustür wirklich öffnen?").

## 6. Sprachassistent "Cat"

### Ablauf

1. Satellit erkennt "Hey Cat" lokal (openWakeWord). Der Name "Cat" allein ist als Wake-Word sehr kurz und fehleranfällig. "Hey Cat" oder "Okay Cat" ist zuverlässiger. Ein eigenes Modell trainierst du mit dem Trainings-Notebook von openWakeWord.
2. Satellit streamt Audio (16 kHz, 16 Bit, mono) per WebSocket an den Server.
3. Server: Silero VAD erkennt das Sprachende (Pause ca. 1,5 s einstellbar).
4. faster-whisper wandelt in Text um.
5. Dialog: erst Fast-Path-Intents (rapidfuzz gegen Geräte- und Raumnamen). Nur wenn nichts passt, geht es zum LLM-Agent.
6. Antwort wird satzweise an Piper gegeben; die Audio-Chunks laufen sofort zurück zum Satelliten ("Streaming-TTS").
7. "Continue conversation": Der Satellit öffnet das Mikro nach der Antwort erneut, wenn eine Rückfrage kam.

### Satellit

- **Empfehlung**: eigener Python-Client (`satellite/`) auf einem Raspberry Pi (Zero 2 W reicht für Wake-Word + Audio) mit USB-Konferenzlautsprecher oder ReSpeaker-2-Mics-HAT plus kleinem Lautsprecher.
- Läuft als systemd-Dienst, verbindet sich per WebSocket, meldet Raum und Gerätename.
- ESP32-Geräte (z. B. ESP32-S3-BOX-3) würden eigene Firmware brauchen; das ist ein späteres Zusatzprojekt.
- Alternative, falls du fertige Satelliten wiederverwenden willst: Wyoming-Protokoll (Python-Paket `wyoming`). Das ist mehr Fremdprotokoll, dafür gibt es fertige Software für Pi-Satelliten.

### Latenz (Schätzung, am Ende messen)

| Pfad | Erwartung |
|---|---|
| Fast-Path ("Licht an") | ca. 2-3 s, großteils die Sprechpause |
| LLM-Antwort (Cloud) | ca. 3-5 s bis zum Beginn der Antwort |

Maßnahmen: Whisper `base`/`small` int8 testen, Pause anpassen, Modell warm halten, Antworten auf 1-2 Sätze begrenzen.

## 7. Second Brain

- Quelle der Wahrheit sind **Markdown-Dateien** in `data/memory/` (lesbar, versionierbar, modellunabhängig).
- Index in SQLite (FTS5-Volltext). Optional später Vektor-Suche (`sqlite-vec` plus kleines Embedding-Modell), damit es auf 16 GB RAM leicht bleibt.
- Tools für den Agenten: `memory_search`, `memory_write`, `memory_list`.
- Beim Modellwechsel ändert sich nichts: neues Modell, gleiche Notizen.
- Du kannst alles in Obsidian o. Ä. selbst lesen und bearbeiten.

## 8. Sicherheit (Pflichtteil)

- Zugriff nur im LAN, Login für die Weboberfläche (mindestens Passwort/Token), kein Port-Forwarding.
- Secrets nur in `.env`, nie im Repo und nie im Prompt.
- Gerätesteuerung nur über Allowlist und Risikostufen (siehe oben).
- KI-erzeugter Code und KI-erzeugte Integrationen laufen **nicht** direkt produktiv: erst Review durch dich, dann Aktivierung. Code-Ausführung nur in einer Docker-Sandbox ohne Netzwerk.
- Alle Aktionen (Tool-Aufrufe) werden mit Zeitstempel geloggt.
- Backups: `data/` täglich sichern.

## 9. Phasen mit Abnahmekriterien

| Phase | Inhalt | Fertig, wenn |
|---|---|---|
| 0 | Repo, Docker, FastAPI-Skelett, Frontend-Skelett | `docker compose up` zeigt eine leere Seite, `/health` antwortet |
| 1 | UI-Layout (Widgets, Stage, Chat), WebSocket | Chat-Nachricht erscheint live, Layout entspricht dem Bild |
| 2 | LLM-Streaming, Tool-Calling, Stage-Tools | "Zeig mir eine Uhr als HTML-Grafik" rendert in der Stage |
| 3 | Live-Widgets (System, Wetter, Uhr, Uptime) | Werte aktualisieren sich ohne Reload |
| 4 | Plugin HA + openHAB (erst lesen, dann steuern) | Gerätezustand sichtbar, Schalten mit Risikostufen und Rückfrage |
| 5 | Fast-Path-Intents | "Schalte das Licht im Wohnzimmer an" ohne LLM, unter 100 ms Verarbeitung |
| 6 | Voice-Pipeline mit Test-Eingabe (Audiodatei, später Browser-Mikro) | Audio rein, Text, Antwort, Audio raus |
| 7 | Satellit (Pi-Client, Wake-Word, Streaming-TTS) | "Hey Cat, ..." im Raum funktioniert Ende zu Ende |
| 8 | Second Brain | Cat merkt sich Dinge, und nach Modellwechsel sind sie noch da |
| 9 | Offline-Fallback (Ollama), Code-Sandbox, eigene Integrationen | Ohne Internet bleiben Fast-Path und Fallback-Modell nutzbar |

Empfehlung: Phase 0-4 zuerst. Danach hast du schon ein nutzbares Dashboard, bevor die Sprache dazukommt.

## 10. Anleitung: Was du selbst tun musst

### A. Vorbereitung (einmalig)

1. **RAM** auf 16 GB (besser 32 GB) aufrüsten: zwei gleiche DDR4-SODIMM-Module, damit Dual-Channel läuft.
2. **Betriebssystem**: Debian 12 oder Ubuntu Server 24.04 installieren, feste IP im Router vergeben, SSH aktivieren.
3. **Docker** und Docker Compose installieren.
4. **Home Assistant** und/oder **openHAB** per Docker starten (falls noch nicht vorhanden). Eigene Compose-Dateien, getrennt von Cat.
5. **Tokens erzeugen**:
   - Home Assistant: Profil, Sicherheit, "Langlebige Zugriffstokens".
   - openHAB: Profil, "API-Tokens".
6. **API-Schlüssel** für den LLM-Anbieter (Anthropic) holen und ein Ausgabenlimit setzen.
7. **Git-Repo** `HomeLM` anlegen (privat).
8. **Claude Code** installieren und im Repo-Ordner starten. Die Dateien `CLAUDE.md` in die Repo-Wurzel legen, `claude-code-prompts.md` zum Kopieren bereithalten.

### B. Arbeitsweise mit Claude Code

- Entwickle am besten auf deinem PC und deploye auf den Server (Git + `docker compose`), oder arbeite direkt per SSH auf dem Server.
- Eine Phase pro Sitzung. Vorgehen: Prompt aus der Sammlung einfügen, Plan ansehen, umsetzen lassen, Abnahmekriterium prüfen, committen.
- Lass Claude Code zu jeder Phase Tests schreiben und `docs/` aktuell halten.
- Prüfe jede Änderung an Plugins und Gerätesteuerung selbst, bevor sie auf echte Geräte losgelassen wird. Teste zuerst gegen eine Test-Entität (z. B. eine virtuelle Lampe).

### C. Satelliten-Hardware (zu Phase 7)

- Raspberry Pi Zero 2 W (oder Pi 3/4), microSD, Netzteil.
- Mikrofon: ReSpeaker 2-Mics Pi HAT oder ein USB-Konferenzlautsprecher (Mikro und Lautsprecher in einem, einfachste Lösung).
- Gehäuse nach Wunsch. Ein Satellit pro Raum, mit Raumname in der Konfiguration.

## 11. Risiken und offene Punkte

- **RAM**: ohne Upgrade wird es eng. Whisper `small` plus HA plus openHAB plus Cat brauchen realistisch 5-6 GB.
- **CPU-STT-Tempo**: Whisper `small` auf dem i5-8500 ist brauchbar, aber nicht blitzschnell. Früh messen, notfalls `base` verwenden.
- **Wake-Word "Cat"**: kurz und anfällig für Fehlauslösungen. "Hey Cat" einplanen und mit echten Aufnahmen testen.
- **Cloud-Abhängigkeit**: Gesprächsinhalte gehen an den Anbieter; Kosten beobachten.
- **Browser-Mikro** braucht HTTPS (Caddy mit interner CA) oder `localhost`. Für Satelliten ist das nicht nötig.
- **Offen**: Welche Modelle genau, und ob du die Vektor-Suche überhaupt brauchst, entscheidest du nach Phase 8 anhand der Praxis.
