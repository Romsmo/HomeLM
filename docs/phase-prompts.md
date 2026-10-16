> Hinweis: Dies ist die Phasen-Sammlung für Claude Code. Bei Widersprüchen gilt `CLAUDE.md` (z. B. openHAB zuerst, Home Assistant nur gegen Mocks, Deployment nach `/srv/cat`, rote Linien, Rückfrageregeln). Der Gesamtauftrag steht in `START.md`.

# Claude-Code-Prompts für "Cat"

Vorgehen: `CLAUDE.md` in die Repo-Wurzel legen, `cat-plan.md` nach `docs/cat-plan.md` kopieren, Claude Code im Repo starten und pro Phase einen Prompt einfügen. Nach jeder Phase das Abnahmekriterium selbst prüfen und committen.

---

## Phase 0: Fundament

```
Lies CLAUDE.md und docs/cat-plan.md. Setze Phase 0 um:
- Projektstruktur laut CLAUDE.md anlegen (backend, frontend, satellite, data, docs).
- Backend: FastAPI-Skelett mit /health, Konfiguration über Pydantic Settings aus .env, pytest und ruff eingerichtet, uv als Paketverwaltung.
- Frontend: Vite + React + TypeScript (strict) + Tailwind, leere Seite.
- docker-compose.yml mit Services backend und frontend (Frontend wird vom Backend oder einem Caddy-Container ausgeliefert, schlage die einfachste Variante vor).
- .env.example ohne echte Werte, .gitignore (data/, .env).
Zeige erst einen kurzen Plan, setze dann um. Abnahme: `docker compose up --build` startet alles, /health antwortet, Tests laufen.
```

## Phase 1: UI-Layout und WebSocket

```
Setze Phase 1 um: das Dashboard-Layout.
- Dunkles, futuristisches Design: Header (Name "Cat", Online-Status, Uhr/Datum, Wetter-Platzhalter), linke Spalte mit Widget-Karten (System, Wetter, Uptime), große Stage in der Mitte mit animiertem Cat-Orb (Zustände: idle, listening, thinking, speaking), rechts ein Chat-Panel mit Eingabefeld, Clear-Button und Export-Button.
- Das Layout soll zu diesem Aufbau passen: Chat rechts, großer Overview in der Mitte, Widgets links. Responsive für Tablets.
- WebSocket-Verbindung Browser <-> Backend mit typisierten JSON-Events (chat.message, chat.delta, stage.show, stage.clear, widget.update, voice.state). Event-Typen einmal im Backend (Pydantic) und im Frontend (TypeScript) definieren und in docs/protocol.md dokumentieren.
- Automatische Wiederverbindung bei Verbindungsabbruch.
- Noch kein LLM: das Backend antwortet auf Chat-Nachrichten mit einem Echo.
Abnahme: Nachricht senden, Echo erscheint live im Chat; Verbindungsabbruch wird erkannt und behoben.
```

## Phase 2: LLM, Tool-Calling und Stage

```
Setze Phase 2 um:
- LLM-Schicht in backend/src/cat/llm/: eigene Schnittstelle, LiteLLM als Implementierung, Provider und Modell per Konfiguration (Standard: Claude Haiku in der aktuellen Version; prüfe den gültigen Modellnamen in der Anthropic-Dokumentation und lege ihn in .env.example ab). Streaming der Antwort an den Chat (chat.delta).
- Agent-Loop in agent/: System-Prompt auf Deutsch (kurze, natürliche Antworten, für Sprache 1-2 Sätze), Tool-Registry, Tool-Calling-Schleife mit Abbruchlimit.
- Stage-Tools: show_html(html, title), show_chart(spec, title), show_markdown(text, title), clear_stage().
- Frontend: Stage rendert html in einer Sandbox-iframe (sandbox="allow-scripts", ohne allow-same-origin, strikte CSP, kein Netzwerk), Charts mit einer Chart-Bibliothek deiner Wahl (begründe sie), Markdown formatiert. Kleine Historie der Stage-Inhalte zum Zurückblättern.
- Tests: Agent-Loop mit gemocktem LLM, Stage-Events, Sanitizing.
Abnahme: "Zeig mir eine analoge Uhr als HTML-Grafik" rendert in der Stage; "Zeig mir ein Balkendiagramm mit diesen Zahlen: ..." erzeugt ein Chart.
```

## Phase 3: Live-Widgets

```
Setze Phase 3 um: Widgets mit Live-Daten.
- Plugin "system": CPU, RAM, Disk, Uptime (psutil), Push per WebSocket alle paar Sekunden.
- Plugin "weather": Open-Meteo (ohne API-Key), Standort per Konfiguration, Caching, Refresh-Button.
- Uhr/Datum im Header.
- Gemeinsame Widget-Spezifikation (WidgetSpec) in plugins/base.py, damit spätere Plugins eigene Widgets liefern können.
Abnahme: Werte aktualisieren sich ohne Reload, Wetter-Fehler (kein Internet) werden sauber im Widget angezeigt.
```

## Phase 4: Home Assistant und openHAB

```
Setze Phase 4 um: Smart-Home-Plugins.
- Gemeinsames Gerätemodell (Name, Raum, Typ, Zustand, Risikostufe low/medium/high) und eine Allowlist in einer YAML-Datei in data/config/ (nur dort aufgeführte Geräte sind für Cat sichtbar und steuerbar).
- Plugin homeassistant: REST + WebSocket-API, Langzeit-Token aus .env. Entitäten lesen, Services aufrufen, State-Changes abonnieren und per WebSocket ans Frontend pushen.
- Plugin openhab: REST-API (Items lesen, Befehle senden), SSE für Änderungen, API-Token aus .env.
- Tools für das LLM: list_devices, get_state, set_state/call_service. Risikostufe wird im Backend erzwungen: bei "high" muss der Nutzer über confirm.request/confirm.response bestätigen.
- Audit-Log für jeden Tool-Aufruf.
- Stage-Panel "devices" mit Live-Zuständen und Schaltern.
- Tests mit gemockten HA- und openHAB-Servern. Teste zuerst nur Lesen, dann Steuern.
Abnahme: Gerätezustände sind sichtbar und live; eine Test-Lampe lässt sich per Chat schalten; "high"-Geräte verlangen Bestätigung; alles steht im Audit-Log.
```

## Phase 5: Fast-Path-Intents

```
Setze Phase 5 um: lokale Intent-Erkennung ohne LLM.
- Regeln für deutsche Sätze: An/Aus, Helligkeit, Temperatur lesen, Zustand abfragen, Rollladen auf/zu, Raumbezug ("im Wohnzimmer"). Fuzzy-Matching auf Geräte- und Raumnamen mit rapidfuzz, Synonyme in einer YAML-Datei.
- Reihenfolge: Fast-Path zuerst; nur bei fehlendem Treffer geht der Text an den Agenten.
- Dieselbe Risikostufen- und Bestätigungslogik wie bei den Tools.
- Antworttexte kurz und natürlich.
- Viele Testsätze (inkl. Füllwörter wie "ähm", Umgangssprache) als pytest-Parametrisierung.
Abnahme: "Mach das Licht im Wohnzimmer an" läuft ohne LLM-Aufruf, Verarbeitung unter 100 ms (messen und berichten).
```

## Phase 6: Voice-Pipeline auf dem Server

```
Setze Phase 6 um: Sprachpipeline auf dem Server, noch ohne Satellit.
- voice/vad.py (Silero VAD, Pause bis Sprachende konfigurierbar, Standard 1,5 s), voice/stt.py (faster-whisper, Modell und compute_type per Konfiguration, int8), voice/tts.py (Piper, deutsche Stimme, satzweises Streaming), voice/pipeline.py (Audio rein -> VAD -> STT -> Dialog -> TTS-Chunks raus).
- Modelle werden beim Start geladen und warm gehalten; Download in data/models/.
- Testwerkzeuge: ein Skript, das eine WAV-Datei durch die Pipeline schickt und die Antwort als WAV speichert; im Frontend ein Mikrofon-Button (nur über HTTPS/localhost), der Audio per WebSocket sendet.
- Latenzmessung pro Stufe (VAD-Ende, STT, erster LLM-Token, erstes TTS-Audio) im Log und optional im UI.
Abnahme: gesprochene Frage rein, gesprochene Antwort raus; Latenzwerte werden berichtet. Falls STT zu langsam ist, Vorschlag für kleineres Modell oder Alternativen.
```

## Phase 7: Satellit

```
Setze Phase 7 um: den Satelliten.
- satellite/: Python-Client für Raspberry Pi (läuft als systemd-Dienst). Mikrofon-Aufnahme (sounddevice), Wake-Word-Erkennung lokal mit openWakeWord, Audio-Streaming per WebSocket an den Server, Wiedergabe der TTS-Chunks, "Continue conversation" (Mikro nach Rückfrage wieder öffnen), LED/Signalton als Statusanzeige optional.
- Konfiguration: Server-URL, Token, Raumname, Geräte-ID, Mikrofon/Lautsprecher.
- Server: ws/satellite.py mit Registrierung, Authentifizierung, Raumzuordnung (der Raum fließt in die Intent-Auflösung ein: "Licht an" meint den Raum des Satelliten).
- Wake-Word: starte mit einem vorhandenen openWakeWord-Modell zum Testen; dokumentiere in docs/ Schritt für Schritt, wie ich ein eigenes "Hey Cat"-Modell trainiere.
- Anleitung für Pi-Setup (OS, Audio-Treiber, Dienst) in docs/satellite.md.
Abnahme: "Hey Cat, schalte das Licht an" im Raum funktioniert Ende zu Ende; mehrere Satelliten können gleichzeitig verbunden sein.
```

## Phase 8: Second Brain

```
Setze Phase 8 um: Gedächtnis außerhalb des Modells.
- Markdown-Dateien in data/memory/ als Quelle der Wahrheit (Unterordner nach Thema), Frontmatter mit Datum und Tags.
- SQLite-Index mit FTS5; Neuindizierung bei Dateiänderung. Vektor-Suche zunächst nur als vorbereitete Schnittstelle (sqlite-vec optional).
- Tools: memory_search, memory_write, memory_list. Der Agent liest relevante Erinnerungen vor der Antwort und schreibt neue nur auf Aufforderung oder bei klar dauerhaften Fakten (z. B. Vorlieben).
- Gesprächsverlauf pro Sitzung speichern, Zusammenfassung alter Gespräche in Notizen.
- Tests, die zeigen, dass ein Wechsel von Provider/Modell das Gedächtnis nicht beeinflusst.
Abnahme: "Merk dir, dass ich Kaffee ohne Zucker trinke" wird gespeichert und nach Neustart und Modellwechsel korrekt abgerufen.
```

## Phase 9: Offline-Fallback, Sandbox, eigene Integrationen

```
Setze Phase 9 um:
- Offline-Fallback: Ollama-Container (Qwen3 4B, Q4_K_M) als zweiter Provider; automatischer Wechsel, wenn die Cloud-API nicht erreichbar ist; im UI sichtbar, welcher Provider gerade antwortet. Hinweis in docs/ zu RAM-Bedarf.
- Code-Sandbox: Docker-Container ohne Netzwerk, mit CPU-/RAM-/Zeitlimit, Tool run_python(code), Ergebnisse (Text, Bilder, Diagramme) an die Stage.
- Eigene Integrationen: Mechanismus, mit dem Cat neue Plugins als Code-Vorschlag erzeugt, die **nicht** automatisch aktiv werden. Sie landen in einem Ordner "pending/", ich prüfe sie und aktiviere sie manuell. Dokumentiere den Review-Ablauf.
Abnahme: Internet getrennt -> Fast-Path und Fallback-Modell antworten; Python-Code läuft nur in der Sandbox; ein erzeugtes Plugin ist ohne meine Freigabe inaktiv.
```

---

## Allgemeine Hilfs-Prompts

**Review vor dem Commit**
```
Prüfe die Änderungen dieser Phase kritisch: Sicherheitsregeln aus CLAUDE.md, fehlende Tests, blockierende Aufrufe im Event-Loop, Secrets im Code, unbehandelte Fehler bei Netzwerkausfall. Liste Probleme auf und behebe sie.
```

**Fehlersuche**
```
Folgender Fehler tritt auf: <Fehlermeldung/Log>. Finde die Ursache, bevor du etwas änderst. Erkläre sie kurz, schlage die kleinste Korrektur vor und ergänze einen Test, der den Fehler abdeckt.
```

**Dokumentation nachziehen**
```
Aktualisiere docs/ und CLAUDE.md passend zum aktuellen Stand (Befehle, Konfiguration, Protokoll, Plugins). Nenne die Änderungen kurz.
```
