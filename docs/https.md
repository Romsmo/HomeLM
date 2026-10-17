# HTTPS im LAN (Mikrofon im Browser)

Browser geben das Mikrofon nur auf `https://` oder `localhost` frei. Cat lauscht darum zusätzlich auf einem HTTPS-Port, mit einem Zertifikat einer **eigenen Zertifizierungsstelle (CA)** nur für Ihr Heimnetz.

| Adresse | Zweck |
|---|---|
| `http://192.168.0.10:8090` | wie bisher (Satelliten, Health-Check, Oberfläche ohne Mikrofon) |
| `https://192.168.0.10:8490` | Oberfläche mit Mikrofon (auch `https://homeserver:8490`, falls Ihr Netz den Namen auflöst) |

Beide Adressen sind dieselbe Cat-Instanz (ein Chatverlauf, ein Zustand). Kein Eingriff in Caddy, Nextcloud, Firewall oder Router: der Port ist nur an `192.168.0.10` gebunden und nicht über Caddy erreichbar. Port 8443 war schon von openHAB belegt, darum 8490 (`CAT_TLS_HOST_PORT`). Ob Ihr Router 8490 ins Internet weiterleitet, kann ich von hier nicht prüfen; normalerweise leitet er nur, was Sie eingerichtet haben (80/443). Das Login bleibt in jedem Fall Pflicht.

## Einmal je Gerät: die CA installieren

Die Datei `ca.crt` ist öffentlich und unkritisch (kein Schlüssel). Sie liegt auf dem Server in `/srv/homelm/data/certs/ca.crt`. **Nur diese Datei** auf Geräte installieren, die Ihnen gehören.

- **Windows (Edge/Chrome):** Datei doppelklicken, "Zertifikat installieren", "Aktueller Benutzer", "Alle Zertifikate in folgendem Speicher speichern", **Vertrauenswürdige Stammzertifizierungsstellen**. Danach den Browser neu starten. Mit Norton/Virenscanner mit Web-Schutz ist das Pflicht: Er schaltet sich in jede HTTPS-Verbindung (auch im LAN) und zeigt sonst ein eigenes, als unsicher markiertes Zertifikat. Firefox hat einen eigenen Speicher (Einstellungen, Datenschutz, Zertifikate, Importieren, "Dieser CA vertrauen, um Websites zu identifizieren").
- **Android:** Datei aufs Handy, Einstellungen, Sicherheit, "Zertifikat installieren", **CA-Zertifikat**.
- **iPhone/iPad:** Datei per AirDrop oder Safari laden, Profil installieren, dann Einstellungen, Allgemein, Info, **Zertifikatsvertrauenseinstellungen**, Vertrauen einschalten.
- **Linux:** `sudo cp ca.crt /usr/local/share/ca-certificates/cat-ca.crt && sudo update-ca-certificates`.

Danach `https://192.168.0.10:8490` öffnen: Schloss ohne Warnung, und der Mikrofon-Knopf unter dem Cat-Kern fragt um Erlaubnis. Wer das Mikrofon einmal erlaubt, hat Cat danach von selbst am Ohr (siehe unten).

## Betrieb

- Zertifikat und Schlüssel: `data/certs/server.crt` und `server.key` (gültig 800 Tage, bis **25.12.2028**). Der Schlüssel der CA liegt bewusst **außerhalb** von `data/` in `/srv/homelm/ca-private/`; der Cat-Container sieht ihn nie.
- **Erneuern** (vor Ablauf): `cd /srv/homelm && bash scripts/make_certs.sh && docker compose restart backend`. Die vorhandene CA bleibt, die Geräte müssen nichts neu installieren. Gehen `ca-private/` verloren, entsteht eine neue CA, und sie muss auf den Geräten neu installiert werden.
- **Andere Namen/IP** (z. B. neuer Hostname): `SAN="IP:192.168.0.10,DNS:homeserver,DNS:cat.lan" bash scripts/make_certs.sh`.
- **HTTPS ausschalten:** `data/certs/server.crt` und `server.key` entfernen und Cat neu starten (Cat meldet im Log, dass HTTPS fehlt, und läuft nur auf HTTP weiter).
- **Satelliten** bleiben auf `ws://192.168.0.10:8090` (kein Mikrofon-Browser, brauchen kein HTTPS).
- Technik: `python -m cat.serve` startet zwei Listener in einem Prozess (HTTP 8000, HTTPS 8443 im Container). Über HTTPS setzt das Login das Cookie mit `Secure`.

## Geprüft

- Server: Zertifikat gegen die CA verifiziert (für die IP und für `homeserver`), `https://192.168.0.10:8490/health` und die Login-Seite antworten, HTTP `:8090` unverändert.
- PC: Der Test von diesem PC aus scheitert erwartungsgemäß am Norton-Web-Schutz (er ersetzt das Zertifikat durch sein eigenes "Untrusted Root"). Nach Installation der CA in den Windows-Speicher ist das behoben; **dieser Browser-Schritt ist noch nicht abgenommen**, weil die CA noch nicht installiert ist.
