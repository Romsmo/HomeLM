# Offline-Betrieb und Fallback-Modell

## Was ohne Internet immer funktioniert

- **Fast-Path** (`docs/intents.md`): Licht, Rollläden, Heizung, Temperatur und Zustände über openHAB im LAN, ohne LLM.
- Dashboard, Widgets (Wetter zeigt dann einen Hinweis), Gedächtnis (Notizen und Suche), Geräte-Panel, Audit-Log.

Alles andere (freie Fragen, Grafiken, Gespräche) braucht das Cloud-Modell **oder** das lokale Fallback-Modell.

## Wie der Fallback arbeitet

Ist `CAT_FALLBACK_MODEL` gesetzt (z. B. `ollama/qwen3:4b`), versucht Cat zuerst das Cloud-Modell (Wartezeit `CAT_LLM_TIMEOUT_S`, Standard 20 s). Ist es **nicht erreichbar** (Internet weg, Ausfall, Limit), antwortet das lokale Modell, und der Kopf der Oberfläche zeigt in Gelb **"Offline-Modell: qwen3:4b"**. Danach geht es 60 Sekunden direkt zum lokalen Modell (kein Warten pro Nachricht), dann wird die Cloud wieder versucht und die Anzeige springt zurück.

Nicht umgeschaltet wird bei Konfigurationsfehlern (falscher API-Schlüssel, falscher Modellname): Die erreichen Sie als Meldung. Mitten in einer Antwort wird nie gewechselt.

Das Fallback-Modell ist deutlich schwächer (kleines Modell auf der CPU, grob 4 bis 8 Wörter pro Sekunde, Werkzeugaufrufe weniger zuverlässig). Es ist ein Notnagel, kein Ersatz.

## RAM-Bedarf und Entscheidung für diesen Server

Qwen3 4B (Q4_K_M) belegt geladen etwa **2,6 GB Gewicht plus Kontext, zusammen rund 3 bis 3,5 GB**. Der Ollama-Container ist deshalb auf 3,5 GB begrenzt und entlädt das Modell nach 2 Minuten Leerlauf (`OLLAMA_KEEP_ALIVE`).

Der Server hat **7,5 GB RAM**, davon laufen bereits openHAB (1,1 GB), PostgreSQL (1,7 GB), Nextcloud, MariaDB und weitere Dienste; verfügbar sind rund 5 GB (zum Teil Cache der Datenbanken), und es wird schon ausgelagert. Ein zusätzlich geladenes 3-GB-Modell würde Nextcloud und Trafficnetwork spürbar bremsen. **Darum ist der Fallback hier vorerst nicht aktiv** (Container hinter dem Compose-Profil `offline`, `CAT_FALLBACK_MODEL` leer). Mit einem RAM-Upgrade auf 16 GB ist er unproblematisch.

## Aktivieren (nach Upgrade oder bewusst auf eigenes Risiko)

```bash
cd /srv/homelm
# 1. in .env eintragen:  CAT_FALLBACK_MODEL=ollama/qwen3:4b
docker compose --profile offline up -d ollama
docker compose exec ollama ollama pull qwen3:4b     # lädt ca. 2,5 GB von registry.ollama.ai
docker compose up -d --no-build                      # Cat mit Fallback neu starten
```

Das Herunterladen des Modells ist ein Zugriff auf einen neuen Server (Ollama-Registry). Es gehen keine Hausdaten dorthin. Deaktivieren: `CAT_FALLBACK_MODEL` leeren, `docker compose --profile offline stop ollama`.

## Testen

Internet trennen (oder in der `.env` einen falschen `ANTHROPIC_BASE_URL`-Weg nutzen) und eine freie Frage stellen: Der Kopf zeigt "Offline-Modell", ein Gerätebefehl ("Mach das Licht in der Küche an") läuft unabhängig davon über den Fast-Path.
