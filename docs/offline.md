# Offline-Betrieb und lokales Modell

Seit dem Umbau "lokal zuerst" (`docs/claude.md`) ist das lokale Modell auf dem Server die **erste Wahl** und nicht mehr nur ein Notnagel. Diese Seite beschreibt, was ohne Internet geht, was das Modell kostet und wie man es betreibt.

## Was ohne Internet immer funktioniert

- **Gelernte Kurzbefehle** (`docs/learning.md`): Was Cat aus wiederholten Anfragen gelernt hat (Licht, Rollläden, Zustände über openHAB im LAN), läuft ohne LLM in Millisekunden.
- **Das lokale Modell** (Ollama): freie Fragen, Gerätesteuerung per Werkzeug, Gedächtnis, Rechnen, einfache Stage-Inhalte.
- Dashboard, Widgets (Wetter zeigt dann einen Hinweis), Gedächtnis (Notizen und Suche), Geräte-Panel, Audit-Log.

Nur Claude (schwere Fragen, HTML-Grafiken, lange Texte) braucht das Internet.

## Modell und Messwerte

Gemessen am 17.10.2026 auf dem Heimserver (i5-8500T, 6 Kerne, Ollama-Container mit `cpus: 3`, Modell `qwen3:4b-instruct-2507-q4_K_M`, Kontext 4096, 3 Threads, übrige Dienste laufen):

| | Messwert |
|---|---|
| Ausgabe | ca. 10 Token pro Sekunde (kurz), ca. 7 bei langem Kontext |
| Verarbeiten des Prompts | ca. 30 Token pro Sekunde (neuer Text), bereits bekannter Anfang ist sofort da |
| Kaltstart (Modell laden + Prompt) | 6 s Laden, der erste Prompt mit Werkzeugen bis zu 75 s |
| Einfache Frage ("Wie viele Minuten hat eine Stunde?") | 3 bis 4 s (vorher 4 bis 5 s, am Anfang der Phase 16,8 s) |
| Frage mit Werkzeug (Phase 22, Stand 2026-10-19) | Befehl 2,6 s, Zustand 2 bis 3 s, Sammelfrage 2,9 s, Automationen 2,0 s (Geräte als Kurzzeile); vorher 5 bis 11 s und in Phase 16 noch 17 bis 50 s. Gelernt: 0,0 s |
| Gedächtnis schreiben / lesen | 27 s / 11 s |
| Lange Geschichte (20 Sätze) | ca. 2 Minuten |
| RAM | Ollama 3,06 GiB (Limit 3,5 GiB), Server danach ca. 1,2 GB verfügbar, kein Speicherdruck (PSI 0), kein Swap-Verkehr während der Antwort |
| Nextcloud (`status.php`) während einer Antwort | 15 ms wie im Leerlauf |

**Wichtig, was die Messung ergeben hat:**

1. **`ollama_chat/qwen3:4b` ist ungeeignet.** Der Tag `qwen3:4b` ist inzwischen das "Thinking"-Modell: Es schreibt hunderte Token lang laut nach, bevor es antwortet (`think:false` und `/no_think` werden ignoriert; 440 s für "Hallo, wer bist du?"). Genommen wird deshalb `qwen3:4b-instruct-2507-q4_K_M` (gleiche Größe, ohne Denkphase, gutes Deutsch, zuverlässige Werkzeugaufrufe).
2. **Threads müssen zu `cpus` passen.** Mit 6 Threads auf einem Container mit 3 CPUs drosselt das CFS-Limit, und die Ausgabe fiel auf 2,4 Token/s. Mit 3 Threads sind es 10. Darum `CAT_LOCAL_THREADS` passend zu `cpus` (Phase 16: 5 Threads bei `cpus: 5.0` und `cpu_shares: 256`, damit bei Last Nextcloud und Trafficnetwork Vorrang haben; gemessen 3 Threads 3,9 Token/s, 5 Threads 4,6 Token/s auf dem Server, später durch den kleineren Prompt 7,3).
3. **Der Prompt muss klein und gleichbleibend sein.** Ollama behält die Verarbeitung eines gleichen Anfangs. Cat schickt dem lokalen Modell darum einen kompakten Systemprompt (ca. 400 Token) mit einer kleinen Werkzeugauswahl, und alles Veränderliche (Uhrzeit, Erinnerungen) hängt vor der Nutzernachricht statt im Systemprompt. Der große Prompt der Cloud-Variante (ca. 3000 Token mit allen Werkzeugen) hätte auf der CPU über 100 s gedauert.
4. **Vorwärmen.** Nach einem Kaltstart (Modell entladen oder Cat neu gestartet) brauchte die erste Antwort 75 bis 95 s. Darum lädt Cat das Modell samt Systemprompt und Werkzeugen beim Start und beim Öffnen der Oberfläche vor (ein Token Ausgabe, höchstens alle 4 Minuten). Gemessen: erste Antwort danach 9 bis 20 s statt 77 s.
5. **Das Modell bleibt `CAT_LOCAL_KEEP_ALIVE` (10 min) im RAM** und wird danach entladen. In dieser Zeit hat der Server nur noch rund 1,2 GB frei. Das ging in der Messung ohne spürbare Folgen, ist aber knapp: ein **RAM-Upgrade auf 16 GB** wäre die wichtigste Verbesserung.

Sprache: Bereits gelernte Befehle antworten in unter 1 s, ungelernte gehen erst an das Modell (4 bis 50 s). Freie gesprochene Fragen brauchen Erkennung (gemessen ca. 2,5 s mit `small`) plus Antwort des Modells (gemessen 4 bis 50 s je nach Werkzeug): brauchbar, aber nicht flüssig. Eine Messung über den ganzen Sprachweg mit dem lokalen Modell steht noch aus.

## Aktivieren, Betrieb, Deaktivieren

```bash
cd /srv/homelm
# in .env:  CAT_LOCAL_MODEL=qwen3:4b-instruct-2507-q4_K_M   (plus CAT_LOCAL_THREADS=3)
docker compose --profile offline up -d ollama
docker compose exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M   # ca. 2,5 GB von registry.ollama.ai
docker compose up -d --no-build                                          # Cat neu starten
```

Das Herunterladen des Modells ist ein Zugriff auf einen neuen Server (Ollama-Registry). Es gehen keine Hausdaten dorthin. Deaktivieren: `CAT_LOCAL_MODEL` leeren (dann gilt wieder der alte Cloud-Modus), `docker compose --profile offline stop ollama`.

Prüfen mit echten Fragen (arbeitet auf einer Kopie von Konfiguration und Gedächtnis):

```bash
docker compose exec -T backend python - < scripts/local_eval.py
docker compose exec -T backend python - "Wie spät ist es?" < scripts/local_eval.py
```

## Alter Cloud-Modus mit Offline-Fallback (nur ohne `CAT_LOCAL_MODEL`)

Ist `CAT_LOCAL_MODEL` leer und `CAT_FALLBACK_MODEL` gesetzt (z. B. `ollama_chat/qwen3:4b-instruct-2507-q4_K_M`, **nicht** `ollama/...` und nicht `qwen3:4b`), versucht Cat zuerst das Cloud-Modell (Wartezeit `CAT_LLM_TIMEOUT_S`, Standard 20 s). Ist es **nicht erreichbar** (Internet weg, Ausfall, Limit), antwortet das lokale Modell, und der Kopf zeigt in Gelb **"Offline-Modell"**. Danach geht es 60 Sekunden direkt zum lokalen Modell, dann wird die Cloud wieder versucht. Nicht umgeschaltet wird bei Konfigurationsfehlern (falscher Schlüssel oder Modellname) und nie mitten in einer Antwort. Dieser Modus braucht einen bezahlten API-Schlüssel und ist für diese Installation nicht vorgesehen.

## Modellvergleich und Plan für schnellere Antworten (2026-10-19)

Gemessen auf dem Server (i5-8500T, 6 Kerne mit AVX2, 7,5 GB RAM) mit `scripts/model_bench.py`: Cats echter Systemprompt und echte Werkzeuge, 11 deutsche Aufgaben je zweimal (Schalten, Rollo prozentual, Dimmen, Zustandsfrage, Sammelfragen mit Zustandsfilter, Automationen, Wetter, Merken, Wissensfrage). Nur die erste Werkzeugwahl wird bewertet, nichts wird ausgeführt.

| Modell (Ollama) | Größe | Treffer | Zeit je Schritt (ohne Kaltstart) | Ausgabe | Bemerkung |
|---|---|---|---|---|---|
| `qwen3:4b-instruct-2507-q4_K_M` (aktuell) | 2,5 GB | **22/22** | 4,4 s | 6,9 Token/s | alles richtig |
| `granite4:3b` | 2,1 GB | 20/22 | ca. 4,2 s | 9,2 Token/s | verfehlt "Rollos und Markisen sind offen" (Filter `an` statt `offen`), kaum schneller |
| `llama3.2:3b` | 2,0 GB | 18/22 | 3,6 s | 9,8 Token/s | nimmt `get_state` für Sammelfragen, ruft `run_python` für "Minuten pro Stunde" |
| `qwen3:1.7b` | 1,4 GB | **8/22** | 2,3 s | 15,6 Token/s | unbrauchbar: dreht an/aus um ("Licht aus" sendet `an`), erfindet Parameter, schreibt Aufrufe als Text |

**Ergebnis: Es gibt für diesen Server kein leichteres Modell, das bei den Aufgaben nicht deutlich schlechter ist.** Die Geschwindigkeit hängt an der Speicherbandbreite (jedes Ausgabe-Token liest das ganze Modell): Ein Werkzeugaufruf sind ca. 29 Token und damit ca. 4 s. Kleinere Modelle sparen nur Zeit, indem sie Fehler machen, und bei Geräten sind falsche Befehle schlimmer als langsame. Ein Versuch mit kurzen Werkzeug- und Parameternamen (`set` statt `set_state`) brachte nichts (28 statt 29 Token).

**Plan (in dieser Reihenfolge, nur der erste Punkt ist ohne Ihre Hilfe möglich):**

1. **Fertig:** Wiederholtes läuft über gelernte Kurzbefehle in 0 s, Sammelfragen, Automationen und Zustände ohne zweiten Modelllauf (4 bis 7 s), keine Korrekturrunden mehr bei Auskunftsfragen ("zähle mir auf ...").
2. **Speicher prüfen (Nutzer, sudo):** `sudo dmidecode -t memory | grep -E "Size|Speed|Locator"`. Steckt nur **ein** RAM-Riegel, ist der Speicher einkanalig: Mit zwei gleichen Riegeln (z. B. 2 x 8 GB DDR4) verdoppelt sich die Bandbreite, und die Ausgabe wird fast doppelt so schnell (ca. 12 Token/s statt 7), ganz ohne Modellwechsel. Gemessen: 7 Token/s x 2,5 GB = ca. 17 GB/s, der Chip kann etwa das Doppelte. Dazu schluckt der knappe RAM (7,5 GB, 2,9 GB Swap belegt, nur 118 MB frei) schon jetzt Reserven.
3. **CPU-Takt (Nutzer, sudo, Systemeinstellung, deshalb nicht von mir):** `sudo cpupower frequency-set -g performance` (Standard ist `powersave`). Erwartung: etwas gleichmäßigere Zeiten nach Leerlauf, vermutlich unter 10 %. Vorher/nachher mit `scripts/chat_probe.py` messen.
4. **Danach, mit 16 GB RAM:** Granite 4 `7b-a1b-h` (Mischmodell mit nur 1 Mrd. aktiven Parametern, ca. 4 GB groß) mit `scripts/model_bench.py` prüfen: Nur etwa ein Viertel der Daten pro Token, also potenziell 2 bis 3 x schneller. Es ist nicht getestet, weil es heute nicht in die 3,4 GB des Ollama-Containers passt, ohne Nextcloud und Co. zu gefährden (CLAUDE.md, Abschnitt 5). Zusätzlich dann `qwen3.5:4b` prüfen. Umstellen nur, wenn die Trefferquote bei 22/22 bleibt: `CAT_LOCAL_MODEL=<name>` in `/srv/homelm/.env`, `docker exec homelm-ollama ollama pull <name>`, `docker compose up -d --force-recreate backend`. Rückweg: alten Wert eintragen.
5. **Nicht empfohlen:** `qwen3:1.7b` (Fehlschaltungen), Cloud-Modell für Geräte (ausdrücklich nicht gewollt), Qwen3-30B-A3B und andere große Mischmodelle (ca. 18 GB RAM).

Hinweis: Wissensfragen beantwortet das lokale Modell manchmal falsch ("Faust" von Lessing, im Test einmal). Dafür ist Claude zuständig (`ask_claude`); das Modell sollte dort öfter abgeben.
