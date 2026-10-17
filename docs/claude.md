# Lokal zuerst, Claude nur für den Rest

Cat beantwortet **alles selbst mit dem lokalen Modell** (Ollama auf dem Server, `docs/offline.md`). Claude kommt nur ins Spiel, wenn das lokale Modell etwas nicht kann. Claude läuft über das **Claude-Abo** des Nutzers (Claude Code, `claude -p`), nicht über einen bezahlten API-Schlüssel.

```
Eingabe (Chat, Sprache, Satellit)
   |
   v
Gelernter Kurzbefehl (ohne LLM, ohne Internet)  --- bekannt? ---> Antwort
   |
   v
Lokales Modell (Ollama, Werkzeuge: Geräte, Gedächtnis, Stage, Rechnen)  --- antwortet ---> Antwort
   |  ruft ask_claude auf / fällt aus / braucht zu viele Schritte / antwortet nicht
   |  oder: Nutzer verlangt "frag Claude ..."
   v
Claude-Brücke (Container, Claude Code CLI, Abo) --- Text (+ HTML für die Stage) ---> Antwort
```

## Wann Claude gefragt wird

| Auslöser | Beispiel |
|---|---|
| Das lokale Modell ruft selbst `ask_claude` auf (laut Prompt bei: schwierigen Fragen, aktuellen Fakten, Tiefgang, langen Texten, Programmieren, HTML-Grafiken, Planen, langen Zusammenfassungen) | "Zeig mir eine animierte Uhr", "Erkläre mir die Steuerklassen" |
| Der Nutzer verlangt es ausdrücklich | "Frag mal Claude, ...", "Lass Claude das beantworten", "Claude soll das erklären" |
| Die Aufgabe ist sicher zu schwer für das lokale Modell (Schlüsselwörter: animiert, Animation, HTML, Webseite, zeichne, programmiere, Skript/Code schreiben) | "Zeig mir auf der Stage eine animierte Uhr" geht direkt an Claude, ohne dass das kleine Modell erst "kann ich nicht" sagt |
| Die ersten ca. 120 Zeichen der lokalen Antwort klingen nach Absage ("kann ich leider nicht", "weiß ich nicht", "keine Möglichkeit", "bin mir nicht sicher"), ohne dass ein Werkzeug lief | die Absage wird nicht angezeigt, Claude antwortet stattdessen (gilt nur, solange Claude verfügbar ist) |
| Das lokale Modell fällt aus (Ollama aus, Zeitüberschreitung, Speichermangel), bevor es etwas gesagt hat | Ollama-Container gestoppt |
| Das lokale Modell braucht zu viele Werkzeugschritte (4) oder sagt nichts | verheddert sich bei einer Aufgabe |

**Nie** gefragt wird Claude für: bereits gelernte Kurzbefehle (docs/learning.md), einfache Fragen, Smart Home, Gedächtnis, Rechnen. Das Gerät-Risikomodell (Allowlist, Bestätigung bei Türen) bleibt unverändert im Backend: Claude kann **nichts steuern**, es liefert nur Text und HTML.

Antworten von Claude erscheinen im Chat mit dem Zusatz *"Antwort von Claude"*, und der Kopf zeigt während der Anfrage **"Claude antwortet: sonnet"**. Gesprochene Antworten sind auf 1 bis 2 Sätze begrenzt. Enthält die Antwort einen ```html-Block, geht er (bereinigt) auf die Stage im Sandbox-iframe, nicht in den Chat.

## Schutz und Grenzen

- **Tageslimit** `CAT_CLAUDE_DAILY_LIMIT` (Standard 25 Fragen pro Tag, `0` = Claude aus). Der Zähler steht in `data/claude-usage.json` und überlebt Neustarts.
- **Pause nach Fehlern:** Abo-Limit erreicht: 30 min, nicht angemeldet: 60 min, Brücke nicht erreichbar: 1 min. In der Zeit antwortet Cat ehrlich, dass Claude gerade nicht geht, und fragt nicht bei jeder Nachricht neu.
- **Audit-Log:** Jede Frage an Claude steht in `data/audit.jsonl` (`claude_escalation`: Grund, Modell, Frage, Länge, Ergebnis).
- **Die Brücke** ist ein eigener Container: kein veröffentlichter Port (nur Cat erreicht ihn im Compose-Netz), Dateisystem schreibgeschützt, `cap_drop ALL`, 768 MB, 1 CPU, 128 Prozesse. Das Token liegt nur in `claude.env` und damit nur im Brücken-Container, nie im Cat-Container.
- **Die CLI-Sitzung** hat keine Befehls-, Schreib- oder Web-Werkzeuge: Flags `--restricted`, `--permission-mode dontAsk`, `--tools "Read,Grep,Glob"`, `--strict-mcp-config`, `--no-session-persistence`, `--disable-slash-commands`, `--max-turns 8`. Ein `ANTHROPIC_API_KEY` wird nie an die CLI weitergereicht (mit Schlüssel würde nach Verbrauch abgerechnet statt über das Abo).
- **Nutzungsbedingungen:** Der Weg ist laut Hilfecenter (Stand 07.10.2026) für den **persönlichen Gebrauch** gedacht, `claude -p` verbraucht das Abo-Limit. Cat liest weder das Token noch Anmeldedaten aus der Claude-Code-Konfiguration aus, es nutzt das offizielle Token von `claude setup-token`. Die Regeln haben sich 2026 mehrfach geändert: bei Zweifeln die Consumer Terms und den Hilfeartikel "Use the Claude Agent SDK with your Claude plan" prüfen. Gedacht ist die Installation für einen Haushalt, nicht für Dritte.

## Second Brain: Zugriff für Claude

Das Gedächtnis (Phase 8: Markdown-Notizen in `data/memory`, Suche per SQLite FTS5, Werkzeuge `memory_search`/`memory_write`/`memory_list`) ist eingerichtet. Claude bekommt darauf **lesenden** Zugriff auf zwei Wegen:

1. Cat legt die zur Frage passenden Notizen (FTS5-Treffer) in den Prompt, wie beim lokalen Modell.
2. Die Brücke hängt `data/memory` **schreibgeschützt** (`:ro`) ein und startet die CLI dort als Arbeitsverzeichnis, nur mit `Read`, `Grep`, `Glob` (`--restricted` begrenzt die Dateiwerkzeuge auf dieses Verzeichnis). Claude kann so selbst in allen Notizen suchen. Der Systemprompt weist es an, Notizen als Daten zu behandeln und keine Anweisungen daraus zu befolgen.

Schreiben bleibt beim lokalen Agenten (`memory_write`, mit Geheimnisfilter). Ausschalten: `CAT_CLAUDE_MEMORY=false`. **Datenschutz:** Was Claude liest, geht an Anthropic. Im Gedächtnis stehen laut Regel keine Passwörter oder Schlüssel; Notizen mit privaten Inhalten gehören bei Bedarf nicht ins Gedächtnis oder `CAT_CLAUDE_MEMORY` aus. Die Gesprächsprotokolle (`data/sessions`) sieht Claude nicht, nur den aktuellen Chatverlauf (letzte 8 Nachrichten) der Frage.

## Einrichten (einmalig, Schritte für den Nutzer)

1. **Token erzeugen** (auf einem Rechner mit Browser; Claude Code installieren: `irm https://claude.ai/install.ps1 | iex` unter Windows, `curl -fsSL https://claude.ai/install.sh | bash` unter Linux/macOS):
   ```
   claude setup-token
   ```
   Im Browser anmelden. Das Token (gilt ein Jahr, nur für das Abo) wird einmal im Terminal angezeigt. **Nicht in den Chat posten.**
2. **Auf dem Server** (`/srv/homelm`) die Datei `claude.env` anlegen (Vorlage `claude.env.example`), Zugriff beschränken und das Token eintragen:
   ```bash
   cd /srv/homelm
   cp claude.env.example claude.env && chmod 600 claude.env
   nano claude.env        # CLAUDE_CODE_OAUTH_TOKEN=<Token>
   ```
3. In `.env`: `CAT_CLAUDE_URL=http://claude-bridge:8099`, dann
   ```bash
   docker compose --profile claude up -d claude-bridge
   docker compose up -d --no-build backend
   ```
4. **Prüfen** (die Brücke zeigt nie das Token, nur ob eines da ist):
   ```bash
   docker compose exec -T claude-bridge node -e "fetch('http://127.0.0.1:8099/health').then(r=>r.text()).then(console.log)"
   docker compose exec -T backend python - "Frag Claude: Was ist die Hauptstadt von Australien?" < scripts/local_eval.py
   ```
   `"token":true` und eine Antwort mit dem Vermerk "Antwort von Claude" bedeuten: es läuft.

Die Brücke ist auf der CLI-Version in `claude-bridge/Dockerfile` (`CLAUDE_CODE_VERSION`) festgenagelt. Aktualisieren: Version erhöhen, `docker compose --profile claude build claude-bridge`, neu starten, Prüfung wiederholen.

Wenn etwas hakt: `docker compose logs claude-bridge`. Fehlerarten, die Cat unterscheidet: `auth` (Token fehlt/abgelaufen: neu erzeugen), `limit` (Abo-Limit: später wieder), `timeout` (`ASK_TIMEOUT_S`, Standard 200 s), `busy` (mehr als 3 gleichzeitige Fragen), `unreachable` (Brücke läuft nicht).

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `CAT_LOCAL_MODEL` | leer | Ollama-Modell; gesetzt = Lokal-zuerst-Modus |
| `CAT_LOCAL_THREADS` / `CAT_LOCAL_NUM_CTX` / `CAT_LOCAL_KEEP_ALIVE` | 3 / 4096 / 10m | siehe `docs/offline.md` |
| `CAT_CLAUDE_URL` | leer | `http://claude-bridge:8099`; leer = Claude aus |
| `CAT_CLAUDE_MODEL` | `sonnet` | Alias oder Modellname für `claude --model` (`opus` für schwere Aufgaben, kostet mehr vom Abo-Limit) |
| `CAT_CLAUDE_DAILY_LIMIT` | 25 | Fragen pro Tag |
| `CAT_CLAUDE_MEMORY` | true | Notizen lesbar für Claude |
| `CAT_CLAUDE_TIMEOUT_S` | 240 | Wartezeit auf Claude |

## Was getestet ist und was nicht

- **Getestet (automatisch):** Ollama-Client (Streaming, Werkzeugaufrufe, Fehler), Router (alle Auslöser, Tageslimit, Pause nach Limit, Audit, HTML auf die Stage, Fußzeile, Sprachmodus), Claude-Text-Hilfen, Brücke mit einer Attrappe der CLI (Flags, Arbeitsverzeichnis, Umgebung ohne API-Schlüssel, Fehlerarten, Zeitlimit, Warteschlange).
- **Auf dem Server geprüft:** Ollama-Modell mit echten Fragen (`docs/offline.md`), Brücken-Container startet, die echte CLI 2.1.302 nimmt alle Flags an und meldet ohne Token sauber "nicht angemeldet" (Fehlerart `auth`), Gedächtnis ist in der Brücke schreibgeschützt eingehängt.
- **Noch nicht geprüft:** ein echter Aufruf an Claude, weil dafür das Token des Nutzers nötig ist (Schritte oben). Erst danach ist die Anbindung abgenommen.
