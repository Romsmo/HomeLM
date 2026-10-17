# Audio-Protokoll `/ws/voice`

WebSocket für Mikrofon-Audio rein und Sprachausgabe raus. Genutzt vom Browser und von Satelliten. Alle Audio-Daten sind **PCM, 16 Bit, mono, little endian**.

## Anmeldung

- **Browser:** Sitzungs-Cookie (wie `/ws`) und passender `Origin`.
- **Satellit:** Header `Authorization: Bearer <Token>`. Das Token gehört zu genau einem Satelliten in `data/config/satellites.yaml` (dort steht nur der SHA-256-Hash). Der **Raum** kommt aus diesem Eintrag; ein `hello` des Satelliten kann ihn nicht ändern. Nach 10 falschen Tokens von derselben Quelle sperrt der Server sie 60 Sekunden. Ein Browser kann diesen Header bei WebSockets nicht setzen, fremde Webseiten kommen also nicht über diesen Weg hinein.
- Ohne gültige Anmeldung (oder bei ausgeschalteter Sprachfunktion) wird der Handshake mit HTTP 403 abgelehnt. `GET /api/satellites` (angemeldet) zeigt registrierte Satelliten und ob sie verbunden sind.

## Client an Server

| Art | Inhalt |
|---|---|
| Binär | Mikrofon-Audio, 16 000 Hz. Beliebige Blockgröße bis 64 KiB (üblich: 1024 Bytes = 512 Abtastwerte = 32 ms). Größere Blöcke werden mit `error` abgelehnt. |
| Text (JSON) | `{"type": "hello", "room": "Küche"}`: optional, nur Browser: setzt den Raum des Sprechers (Kontext für das Modell und für gelernte Kurzbefehle, "Licht an" meint dann die Küche). Bei Satelliten wird `hello` (z. B. mit `device_id`) angenommen, der Raum aber aus der Registrierung genommen. |

## Server an Client

| `type` | Felder | Bedeutung |
|---|---|---|
| `voice.ready` | `stt` | Verbindung steht, Modelle sind geladen. |
| `voice.state` | `state` (`listening`/`thinking`/`speaking`/`idle`) | Zustand der Sitzung (derselbe Wert geht an alle Dashboards für den Orb). |
| `voice.transcript` | `text` | Was erkannt wurde. |
| `voice.reply` | `text` | Antworttext (vollständig, kurz). |
| `voice.empty` | | Es wurde nichts Verständliches erkannt. |
| `voice.timeout` | | Nach Verbindungsbeginn hat niemand gesprochen (Satellit: Mikro wieder schließen). |
| `tts.start` | `rate`, `channels`, `format` (`s16le`) | Es folgen binäre Audio-Blöcke der Antwort (Rate meist 22 050 Hz). |
| *(binär)* | PCM16 | Sprachausgabe, satzweise erzeugt und sofort gesendet. |
| `tts.end` | `expects_reply` | Antwort fertig. `true`, wenn die Antwort mit einer Frage endet: Der Satellit öffnet das Mikro erneut ("Continue conversation"). |
| `voice.latency` | `pause_ms`, `stt_ms`, `first_token_ms`, `first_audio_ms`, `total_ms`, `via_fastpath` | Zeiten in ms, gemessen ab dem erkannten Ende der Äußerung (`pause_ms` ist die eingestellte Pause bis zum Sprachende selbst). |
| `error` | `message` | Fehler. Bei zu früher Verbindung (Modelle laden noch) schließt der Server danach mit Code 1013. |

Während Cat denkt oder spricht, wird eingehendes Audio verworfen (Halbduplex: kein Echo, keine Selbstgespräche).

Ist die Sprachfunktion ausgeschaltet (`CAT_VOICE=false`) oder fehlt die Anmeldung, schließt der Server den WebSocket mit Code 1008. `GET /api/voice` (angemeldet) liefert `{enabled, ready, error, stt, voice}`.
