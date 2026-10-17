# Satellit einrichten (Raspberry Pi)

Ein Satellit ist ein kleines Gerät pro Raum mit Mikrofon und Lautsprecher. Es wartet lokal auf das Wake-Word und schickt erst danach Sprache an Cat. Bis dahin verlässt kein Audio das Gerät.

```
Raum: Mikrofon -> Wake-Word (lokal) -> WebSocket /ws/voice -> Server: VAD, Whisper, Dialog, Piper
                                                  <- Antwort-Audio, spielt über den Lautsprecher
```

Ablauf und Protokoll: `docs/voice-protocol.md`. Der Raum eines Satelliten gilt als Standardraum: "Licht an" im Satelliten der Küche schaltet das Licht der Küche (Fast-Path, `docs/intents.md`). Mehrere Satelliten können gleichzeitig verbunden sein; Anfragen werden nacheinander bearbeitet.

## Was gebaut und geprüft ist, und was nicht

- **Geprüft (Tests):** Konfiguration, Zustandsmaschine (Wake-Word, Streaming, Antwort abspielen, Rückfrage "Continue conversation", Zeitüberschreitung, Wiederverbindung mit Wartezeit, Selbstauslösung durch eigene Stimme verhindert), Anmeldung per Token, **Raum aus der Registrierung** (der Satellit kann ihn nicht selbst festlegen), zwei Satelliten gleichzeitig, falsche Tokens mit Sperre. Ende-zu-Ende gegen einen echten Server mit dem echten Satelliten-Code und simuliertem Audio.
- **Nicht geprüft (braucht Ihre Hardware):** echtes Mikrofon und Lautsprecher (`sounddevice`), Wake-Word auf einem echten Pi (`openWakeWord`), der systemd-Dienst, Audio-Qualität im Raum. "Hey Cat, schalte das Licht an" im Raum ist deshalb noch nicht abgenommen.

## Hardware

- Raspberry Pi Zero 2 W (reicht für Wake-Word und Audio), Pi 3 oder Pi 4 gehen auch. microSD, Netzteil.
- **Am einfachsten: USB-Konferenzlautsprecher** (Mikrofon und Lautsprecher in einem, Echo-Behandlung eingebaut). Alternative: ReSpeaker 2-Mics Pi HAT mit kleinem Lautsprecher; dessen Treiber (Seeed) hängen oft hinter neuen Kernelversionen her, daher ist USB unkomplizierter.
- Ein Satellit pro Raum.

## 1. Betriebssystem

Raspberry Pi OS Lite (64-bit) mit dem Raspberry Pi Imager schreiben, dabei Hostname (z. B. `cat-kueche`), WLAN, Benutzer und SSH setzen. Per SSH anmelden, dann:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-pip libportaudio2 alsa-utils
```

Audio prüfen (Mikrofon, Lautsprecher):

```bash
arecord -l && aplay -l
arecord -d 3 -f S16_LE -r 16000 -c 1 test.wav && aplay test.wav
```

## 2. Satelliten-Software installieren

Den Ordner `satellite/` aus dem HomeLM-Repo nach `/opt/cat-satellite` kopieren (z. B. `scp -r satellite pi@cat-kueche:/tmp/` und dann `sudo mv`), dann:

```bash
sudo useradd --system --create-home --groups audio cat
cd /opt/cat-satellite
sudo python3 -m venv .venv
sudo .venv/bin/pip install -e ".[audio]"
sudo chown -R cat:audio /opt/cat-satellite
```

Auf dem Zero 2 W (512 MB RAM) kann die Installation von `onnxruntime` und `numpy` länger dauern oder Speicher brauchen; bei Abbruch hilft vorübergehend mehr Swap (`dphys-swapfile`).

## 3. Satelliten beim Server anmelden

Auf dem **Server** (nicht auf dem Pi):

```bash
cd /srv/homelm
docker compose exec -T backend python - kueche-pi Küche --data /data < scripts/satellite_token.py
```

Das gibt ein **Token** aus, das nur dieses eine Mal zu sehen ist (auf dem Server steht nur sein Hash in `data/config/satellites.yaml`). Raum genau so schreiben wie in der Geräte-Allowlist. Cat liest das Register bei jeder Änderung selbst neu ein (kein Neustart nötig). Ein Satellit pro Aufruf; ein erneuter Aufruf mit derselben ID erzeugt ein neues Token und macht das alte sofort ungültig. Einen Satelliten sperren: seinen Eintrag aus `data/config/satellites.yaml` löschen.

## 4. Konfiguration auf dem Pi

```bash
sudo mkdir -p /etc/cat-satellite
sudo cp /opt/cat-satellite/config.example.yaml /etc/cat-satellite/config.yaml
sudo chown cat:cat /etc/cat-satellite/config.yaml && sudo chmod 600 /etc/cat-satellite/config.yaml
sudo nano /etc/cat-satellite/config.yaml    # server_url, token, device_id, room
```

`server_url` ist im LAN `ws://192.168.0.10:8090/ws/voice` (unverschlüsselt, nur im lokalen Netz erlaubt; die Konfiguration verweigert `ws://` zu fremden Adressen). Mit HTTPS am Server (siehe `docs/voice.md`) wird daraus `wss://`.

## 5. Testen

```bash
cd /opt/cat-satellite
sudo -u cat .venv/bin/python -m cat_satellite --config /etc/cat-satellite/config.yaml --list-devices
sudo -u cat .venv/bin/python -m cat_satellite --config /etc/cat-satellite/config.yaml --test-speaker
sudo -u cat .venv/bin/python -m cat_satellite --config /etc/cat-satellite/config.yaml --test-mic
sudo -u cat .venv/bin/python -m cat_satellite --config /etc/cat-satellite/config.yaml -v
```

Im letzten Schritt "Hey Jarvis" sagen (das mitgelieferte Test-Wake-Word), dann einen Befehl, z. B. "Mach das Licht an". Im Log stehen Erkennung, Antwort und Latenzen. Zum Weiterreden nach einer Rückfrage ist kein neues Wake-Word nötig.

## 6. Als Dienst einrichten

```bash
sudo cp /opt/cat-satellite/cat-satellite.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cat-satellite
journalctl -u cat-satellite -f
```

Der Dienst startet beim Booten und nach Abstürzen neu und verbindet sich nach Netzausfällen mit wachsender Wartezeit (2 s bis 30 s) wieder.

## Fehlersuche

- **"Der Server lehnt die Verbindung ab":** Token falsch, Satellit nicht eingetragen oder `CAT_VOICE=false`. Nach 10 falschen Versuchen sperrt der Server die Quelle eine Minute.
- **Löst ständig aus oder gar nicht:** `wakeword_threshold` anpassen (höher = strenger).
- **Hört sich selbst:** Konferenzlautsprecher mit Echo-Unterdrückung verwenden oder Lautstärke senken. Während der Antwort wertet der Satellit das Mikrofon nicht aus; danach gilt `cooldown_s`.
- **Erkennung schlecht:** Mikrofon näher, `CAT_STT_MODEL=small` am Server (Standard), siehe `docs/voice.md`.
