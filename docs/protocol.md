# WebSocket-Protokoll

Endpunkt: `GET /ws` (WebSocket), nur mit gültigem Sitzungs-Cookie (siehe unten). Alle Nachrichten sind JSON-Text mit dem Feld `type`. Quelle der Wahrheit im Backend: `backend/src/cat/ws/protocol.py` (Pydantic), Spiegel im Frontend: `frontend/src/protocol.ts`. Ein Test prüft, dass beide und dieses Dokument dieselben Typen kennen.

## Anmeldung

- `POST /api/login` mit `{"password": "..."}` setzt das Cookie `cat_session` (HttpOnly, SameSite=Strict, 7 Tage). Nach 5 Fehlversuchen von derselben Quelle gilt 60 s Sperre (HTTP 429).
- `GET /api/me` liefert 200 bei gültiger Sitzung, sonst 401. `POST /api/logout` löscht das Cookie.
- Das Passwort kommt aus `CAT_PASSWORD` (`.env`). Ohne Passwort ist kein Login möglich (HTTP 503).
- Der WebSocket wird ohne Sitzung oder bei fremdem `Origin` geschlossen (Code 1008, vor dem Handshake als HTTP 403).
- Offen bleibt nur `/health` sowie die statischen Dateien des Frontends (Login-Seite); alle Daten laufen über `/api` und `/ws`.

## Server an Browser

| `type` | Felder | Bedeutung |
|---|---|---|
| `chat.message` | `id`, `role` (`user`/`assistant`/`system`), `text`, `ts` | Neue Nachricht. Assistentennachrichten starten leer und füllen sich per `chat.delta`. |
| `chat.delta` | `id`, `delta` | Textteil für die Nachricht mit dieser `id` (Streaming). |
| `chat.done` | `id` | Antwort ist vollständig. |
| `chat.clear` | | Verlauf wurde geleert. |
| `stage.show` | `item` (`id`, `kind` = `html`/`chart`/`markdown`/`devices`, `title`, `content`, `chart`, `created_at`) | Neuer Stage-Inhalt. |
| `stage.clear` | | Stage und Historie geleert. |
| `widget.update` | `id`, `kind`, `title`, `status` (`loading`/`ok`/`error`), `data`, `error`, `updated_at`, `refreshable` | Neuer Zustand eines Widgets. |
| `voice.state` | `state` (`idle`/`listening`/`thinking`/`speaking`) | Zustand des Cat-Orbs. |
| `device.list` | `control` (`readonly`/`test`/`full`), `error`, `devices` (`id`, `name`, `room`, `type`, `risk`, `state`, `unit`, `online`, `controllable`, `test`) | Alle freigegebenen Geräte. `control` ist der Steuerungsmodus des Servers; `controllable` je Gerät folgt aus Modus, Testflag und Typ. |
| `device.state` | `id`, `state`, `unit`, `online` | Zustandsänderung eines Geräts. |
| `confirm.request` | `id`, `device`, `command`, `summary`, `expires_in` | Rückfrage für ein Gerät mit Risiko `high`. Der Server führt den Befehl nur nach `confirm.response` mit `approved: true` aus. |
| `confirm.resolved` | `id` | Rückfrage ist erledigt (beantwortet, abgelaufen oder abgebrochen): Dialog schließen. |
| `error` | `message` | Fehlermeldung an den Nutzer. |

Beim Verbinden sendet der Server zuerst den Chatverlauf (`chat.message`), dann die Stage-Historie (`stage.show`), die aktuellen Widget-Zustände (`widget.update`) und zuletzt die Geräteliste (`device.list`).

## Browser an Server

| `type` | Felder | Bedeutung |
|---|---|---|
| `chat.message` | `text` (1-4000 Zeichen) | Nutzernachricht. Der Server bestätigt sie mit einem `chat.message` der Rolle `user`. |
| `chat.clear` | | Verlauf leeren (nur wenn Cat gerade nicht antwortet). |
| `stage.clear` | | Stage leeren. |
| `widget.refresh` | `id` | Widget sofort neu laden. |
| `confirm.response` | `id`, `approved` | Antwort auf `confirm.request`. Unbekannte, abgelaufene oder schon beantwortete IDs werden ignoriert. |
| `device.command` | `id`, `command` | Befehl aus dem Geräte-Panel (z. B. `on`, `off`, `up`, `50`). Läuft durch dieselben Prüfungen wie ein Tool-Aufruf: Allowlist, Modus, Befehl, Bestätigung bei `high`. |

Ungültige Nachrichten beantwortet der Server mit `error`, die Verbindung bleibt offen.
