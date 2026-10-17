# Sprachpipeline (Phase 6)

```
Audio (16 kHz PCM) -> Silero-VAD -> faster-whisper -> Dialog (Fast-Path oder LLM) -> Piper -> Audio
```

- **VAD:** Silero (ONNX-Modell aus faster-whisper, ohne torch). Erkennt Sprachbeginn und Ende nach einer Pause (`CAT_VAD_SILENCE_S`, Standard 1,5 s), 0,4 s Vorlauf, Geräusche unter 0,3 s werden verworfen, längste Äußerung 20 s.
- **STT:** faster-whisper (CTranslate2, int8, CPU), Modell `CAT_STT_MODEL` (`base` oder `small`). Raum- und Gerätenamen aus der Allowlist gehen als Hinweistext mit ("Küche" statt "Kiche"). Stille ergibt keinen Text (Whisper-Standardsätze werden verworfen).
- **Dialog:** derselbe wie im Chat (Fast-Path zuerst, dann Agent), mit der Vorgabe "1 bis 2 Sätze, kein Markdown". Frage und Antwort erscheinen auch im Chat, und der Orb zeigt hört zu / denkt nach / spricht.
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

Siehe `docs/PROGRESS.md`, Phase 6 (Messung auf dem Server). Faustregel: `base` ist schneller, `small` erkennt Umlaute und Namen besser, braucht aber etwa dreimal so viel Rechenzeit und RAM.

## Datenschutz

Audio wird nicht gespeichert, nur der erkannte Text landet wie jede Chatnachricht im Verlauf. Die Spracherkennung läuft vollständig lokal.
