# Sprachpipeline (Phase 6)

```
Audio (16 kHz PCM) -> Silero-VAD -> faster-whisper -> Dialog (gelernter Kurzbefehl oder LLM) -> Piper -> Audio
```

- **VAD:** Silero (ONNX-Modell aus faster-whisper, ohne torch). Erkennt Sprachbeginn und Ende nach einer Pause (`CAT_VAD_SILENCE_S`, Standard 1,5 s), 0,4 s Vorlauf, Geräusche unter 0,3 s werden verworfen, längste Äußerung 20 s.
- **STT:** faster-whisper (CTranslate2, int8, CPU), Modell `CAT_STT_MODEL` (`base` oder `small`). Raum- und Gerätenamen aus der Allowlist gehen als Hinweistext mit ("Küche" statt "Kiche"). Stille ergibt keinen Text (Whisper-Standardsätze werden verworfen).
- **Dialog:** derselbe wie im Chat (gelernte Kurzbefehle zuerst, dann Agent), mit der Vorgabe "1 bis 2 Sätze, kein Markdown". Frage und Antwort erscheinen auch im Chat, und der Cat-Kern in der Mitte zeigt hört zu / denkt nach / spricht.
- **TTS:** Piper, deutsche Stimme `de_DE-thorsten-medium`. Die Antwort wird **satzweise** erzeugt und sofort gesendet, schon während das LLM noch schreibt. Markdown, Emojis und Einheiten (`°C`, `%`) werden zu sprechbarem Text.
- **Priorität:** Rechenthreads laufen mit `nice 10`, damit Nextcloud, Trafficnetwork und openHAB Vorrang haben. Modelle werden beim Start geladen und bleiben warm.

## Einschalten

`CAT_VOICE=true` in `/srv/homelm/.env`, dann `docker compose up -d --no-build`. Beim ersten Start lädt Cat die Modelle nach `data/models` (Erkennungsmodell von huggingface.co, Stimme von huggingface.co/rhasspy/piper-voices; zusammen ca. 200 MB für `base`). Das sind reine Downloads, es gehen keine Hausdaten dorthin. Vorladen geht auch mit `scripts/download_models.py`.

## Mikrofon im Browser

Browser geben das Mikrofon nur auf `https://` oder `localhost` frei. Der Cat-Port im LAN (`http://192.168.0.10:8090`) ist **kein** sicherer Kontext: Der Mikrofon-Knopf ist dort gesperrt und erklärt es im Tooltip. Auf dem Server selbst und für Entwicklung (`http://localhost:...`) geht es. Für das LAN braucht es HTTPS über Caddy (`tls internal`, eigener LAN-Hostname). Das ist ein Eingriff in Caddy und wird nur nach Ihrer Freigabe gemacht, nach dem Ablauf in `CLAUDE.md`, Abschnitt 4. Satelliten (Phase 7) brauchen kein HTTPS.

## Testwerkzeug

```bash
cd backend
uv run python ../scripts/voice_roundtrip.py --say "Wie warm ist es draußen" antwort.wav
uv run python ../scripts/voice_roundtrip.py frage.wav antwort.wav --room Küche
```

Schickt die Datei (oder einen erst synthetisierten Satz) durch VAD, Whisper, Dialog und Piper, speichert die Antwort als WAV und gibt Erkennung, Antworttext und Latenz je Stufe aus.

## Modellwahl und Messwerte

Gemessen auf dem Heimserver (i5-8500T, 6 Kerne, Rechenthreads mit `nice 10`, 3 Threads, übrige Dienste laufen), mit vier von Piper gesprochenen Beispielsätzen:

| | `base` | `small` (Standard) |
|---|---|---|
| Erkennungszeit je Satz (ca. 2 s Audio) | 1,2 bis 1,6 s | 2,4 bis 2,6 s |
| Zeit bis zum ersten Ton der Antwort, ab Sprachende | 1,5 bis 1,9 s | 2,8 bis 2,9 s |
| Erkennung | 1 von 4 wortgetreu, 1 weiterer fast richtig, 2 falsch ("Wie waren es das draußen?") | 3 von 4 wortgetreu |
| RAM von Cat dauerhaft | ca. 430 MiB | ca. 950 bis 970 MiB |
| Modelldateien | 142 MB | 605 MB |

**Entscheidung: `small`.** Ein falsch verstandenes Wort führt zu einem Fehlbefehl oder zur Rückfrage, das kostet mehr als 1,3 Sekunden. Der Preis sind rund 530 MiB mehr RAM (der Server hat danach noch ca. 3,9 GB verfügbar, der Swap blieb bei 700 MB) und eine längere Wartezeit: Pause bis zum Sprachende (1,5 s) plus Erkennung plus Antwort ergibt ungefähr 4 Sekunden bis zur gesprochenen Antwort, mit `base` ungefähr 3 Sekunden. Stellschrauben: `CAT_VAD_SILENCE_S` (kürzere Pause, z. B. 1,0), `CAT_STT_THREADS`/`cpus`, oder `CAT_STT_MODEL=base`. Mit mehr RAM und CPU-Kernen für Cat wird `small` schneller. Echte Sprecher und Raumgeräusche sind schwieriger als die künstliche Stimme der Messung: `small` hat dafür den größeren Sicherheitsabstand.

## Datenschutz

Audio wird nicht gespeichert, nur der erkannte Text landet wie jede Chatnachricht im Verlauf. Die Spracherkennung läuft vollständig lokal.

## Aktivierungsphrasen (Browser-Mikrofon)

Das Browser-Mikrofon ist immer an. Damit Cat nicht auf jedes Gespräch im Raum antwortet, gilt eine Äußerung nur, wenn sie mit einer **Aktivierungsphrase** beginnt oder endet: **"Hey Cat"**, **"Hallo Cat"** oder **"Okay Cat"** ("Hey Cat, mach das Licht an", "Wie spät ist es, Hey Cat"). Sagt jemand nur die Phrase, antwortet Cat kurz ("Ja?", "Ich höre.", "Ja, bitte?"). Nach einer Antwort bleibt ein **Gesprächsfenster** (20 Sekunden) offen: Die nächste Äußerung, z. B. die Antwort auf eine Rückfrage, braucht keine Phrase.

- Die Phrase wird im erkannten **Text** gesucht. Whisper schreibt "Cat" oft anders ("Kat", "Kät", "Katt"): Das gilt auch. Dazu steht "Hey Cat. Hallo Cat. Okay Cat." im Hinweistext für Whisper.
- Was ohne Phrase gesprochen wird, geht an **kein** Sprachmodell, wird nicht gespeichert und nicht angezeigt (das Gerät schickt es zwar zum Server, dort wird es nach der Texterkennung verworfen). Auch der Stimm-Fingerabdruck wird dafür nicht berechnet.
- Satelliten (Pi) wecken über ihr eigenes Wake-Word und brauchen die Phrase nicht.
- Einstellungen: `CAT_WAKE_REQUIRED` (Standard `true`), `CAT_WAKE_PHRASES` (kommagetrennt, Standard `hey cat,hallo cat,okay cat`), `CAT_WAKE_FOLLOWUP_S` (20). Die Oberfläche zeigt "Sag „Hey Cat“ und deine Anfrage" bzw. "Ich höre weiter zu".
- Grenzen: Erkennt Whisper "Cat" gar nicht (z. B. "Katze"), wird die Äußerung verworfen. Dann klappt es mit einer klareren Aussprache oder einer weiteren Phrase in `CAT_WAKE_PHRASES`.

## Füllsätze beim Nachdenken

Das lokale Modell braucht 4 bis 15 Sekunden. Damit Cat in dieser Zeit nicht tot wirkt, sagt es nach `CAT_FILLER_DELAY_S` (1 Sekunde) etwas Passendes, z. B. "Moment, ich schaue kurz nach." oder "Mach ich, einen Moment." und bei sehr langer Wartezeit bis zu zweimal einen weiteren Satz (alle `CAT_FILLER_REPEAT_S`, 9 Sekunden). Sehr schnelle Antworten (gelernte Kurzbefehle) bekommen keinen. Der Satz wird gesprochen und im Chat/unter dem Kern angezeigt, gehört aber nicht zur Antwort und steht nicht im Verlauf. Details und Lernen: `docs/learning.md`.
