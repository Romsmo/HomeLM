# Cat unter ai.catscastlecloud.de (Reverse-Proxy, echtes Zertifikat, nur Heimnetz)

Cat ist über Caddy unter `https://ai.catscastlecloud.de` erreichbar, mit einem **echten Let's-Encrypt-Zertifikat** (Caddy holt es selbst, wie für `catscastlecloud.de`). Damit ist `window.isSecureContext` wahr und das **Browser-Mikrofon geht ohne CA-Installation**.

## Stand seit 2026-11-21: nur aus dem Heimnetz, eine Passwortabfrage

Auf Anweisung des Nutzers ist Cat **nicht mehr aus dem Internet erreichbar** (das stellt die Regel "Cat nicht aus dem Internet erreichbar", CLAUDE.md Abschnitt 4, wieder her) und es gibt **nur noch die Anmeldung von Cat selbst**, nicht mehr zusätzlich die Browser-Abfrage von Caddy. Zwei unabhängige Sperren:

1. **Cat selbst** (`CAT_LAN_ONLY=true`, `backend/src/cat/lan.py`): Anfragen, deren Client-IP nicht zum Heimnetz gehört, bekommen 403, auch WebSockets (fail closed). Die IP ist hinter Caddy die echte, weil `CAT_TRUSTED_PROXIES` den Proxy nennt und Caddy fremde `X-Forwarded-For`-Header nicht glaubt (Standard).
2. **Heimnetz heißt:** alle privaten Adressen (`192.168.x.x` mit dem Router `192.168.1.1` und seinem Netz, `10.x`, `172.16-31.x`, Loopback) **plus die aufgelöste öffentliche Adresse der Domain** (`CAT_LAN_TRUSTED_HOSTS=ai.catscastlecloud.de`). Grund: Ruft ein Gerät im Heimnetz die Domain auf, spiegelt der Router die Anfrage über die öffentliche Adresse des Anschlusses zurück (NAT-Loopback), und Caddy sieht diese als Absender. Cat löst den Namen alle 5 Minuten neu auf, folgt also einer wechselnden IP; schlägt das DNS fehl, bleibt die letzte Liste. Aus dem Internet kann niemand mit der Adresse **deines** Anschlusses als Absender kommen. Weitere feste Adressen: `CAT_LAN_TRUSTED_IPS`.
3. **Caddy** (`ai.catscastlecloud.de`-Block): nur Zertifikat, Proxy und Sicherheitsheader, **keine** IP-Regel und **kein** `basic_auth` mehr. (Zwischenstand 21.11. vormittags: Caddy hatte `@extern not remote_ip 192.168.0.0/16`; das blockte die Rückspiegelung der Domain und wurde entfernt, `scripts/caddy_lan_only.sh` ist damit überholt und nur noch für den Rückbau des `basic_auth` gedacht.)

**Gut zu wissen**
- Die Domain geht damit **im Heimnetz mit dem echten Zertifikat** (Mikrofon ohne CA-Installation). `https://192.168.0.10:8490` und `http://192.168.0.10:8090` gehen weiter.
- Eine globale IPv6-Adresse im Heimnetz gilt als "außen" (403); dann die IPv4-Adresse nutzen.
- **Unterwegs** (Mobilfunk) geht Cat nicht. Wer von außen will, nutzt ein VPN ins Heimnetz.
- Cats Anmelde-Sperre (5 Fehlversuche je IP, 60 s) bleibt.
- Nicht geprüft werden konnte ein Zugriff von einer echten Außenadresse (kein Gerät außerhalb); getestet ist die Entscheidung mit simulierten Quell-IPs über den Proxy-Weg (8.8.8.8 und 217.88.249.83: 403; Heimnetz und die eigene öffentliche Adresse: 200) und mit Tests. Bitte einmal mit dem Handy im Mobilfunk gegenprüfen (erwartet: 403).

Rollback: `CAT_LAN_ONLY=false` in `/srv/homelm/.env` (Cat offen, nur noch das Login) und `docker compose --profile offline up -d --no-build backend`. Die Caddyfile-Sicherungen liegen als `Caddyfile.bak-lan-*` (vor der Umstellung: Passwortabfrage von Caddy, keine Sperre) und `Caddyfile.bak-lan2-*` (mit der starren Sperre) in `/srv/docker/caddy`.

## Frühere Variante (Internet, mit zweiter Hürde)

Bis 2026-11-21 war Cat über Caddy aus dem Internet erreichbar (bewusste Abweichung von der Regel, mit ausdrücklicher Freigabe des Nutzers, `basic_auth` als zweite Hürde). Der Rest dieser Seite beschreibt diese Variante und die Grundeinrichtung des Blocks.

## Voraussetzungen

- DNS: `ai.catscastlecloud.de` zeigt auf die öffentliche IP des Servers. Geprüft am 17.10.2026: löst auf `217.88.249.83` auf, wie `catscastlecloud.de` (Nameserver `ns1.asok.de`).
- Ports 80 und 443 gehen zum Server (Caddy beantwortet sie bereits für Nextcloud und Trafficnetwork).
- **Ein starkes Cat-Passwort.** Es ist dann die einzige Hürde zwischen dem Internet und Ihrem Haus-Assistenten. Mindestens 16 Zeichen oder eine Passphrase aus 4 bis 5 Wörtern; `CAT_PASSWORD` in `/srv/homelm/.env` ändern (nie im Chat nennen), danach `docker compose up -d --no-build backend`.
- `CAT_DEVICE_CONTROL` bleibt `readonly` oder `test`, bis Sie bewusst auf `full` stellen. Türen, Schlösser und Garagen verlangen unabhängig davon immer eine Bestätigung im Backend.

## Was Cat dafür bekommt (im Repo, ohne Eingriff in Fremdes)

- `docker-compose.yml`: Der Cat-Container tritt dem bestehenden Docker-Netz `docker_proxy` (external) bei, Alias `cat-server`. So erreicht Caddy ihn unter `cat-server:8000`. Alle anderen Ports bleiben wie sie sind.
- `CAT_TRUSTED_PROXIES=172.19.0.0/16` (in `.env`, das Netz von Caddy): Nur von dort glaubt Cat `X-Forwarded-For` und `X-Forwarded-Proto`. Ohne das sähe Cat jeden Besucher als Caddy: Die Anmelde-Sperre träfe alle gemeinsam, und das Login-Cookie wäre nicht `Secure`.
- **Anmelde-Sperre je echter Client-IP** (5 Fehlversuche, 60 s) und neu eine **globale Sperre**: Kommen aus dem Internet insgesamt 20 Fehlversuche, ist die Anmeldung von außen 10 Minuten gesperrt (verteiltes Raten). Aus dem Heimnetz zählt das nicht, dort sperrt nur die Quelle selbst.
- Das Cookie ist hinter dem Proxy `Secure`, `HttpOnly` und `SameSite=strict`. WebSocket-Ursprungsprüfung und Upload-Prüfung vergleichen den Origin mit dem Host (Caddy reicht den Host durch).

## Der Eingriff in Caddy (braucht Ihre Freigabe und sudo)

Ist-Zustand: `/srv/docker/caddy/Caddyfile` (Besitzer `root`, 833 Bytes) mit den Blöcken `catscastlecloud.de`, `http://192.168.0.10, http://homeserver`, `trafficnetwork.link` und `portainer.catscastlecloud.de`. Caddy läuft im Netz `docker_proxy`, Datei read-only eingehängt.

**Minimaler Diff: ein neuer Block am Ende, nichts Bestehendes wird geändert:**

```
ai.catscastlecloud.de {
    encode zstd gzip
    request_body {
        max_size 30MB
    }
    header {
        Strict-Transport-Security "max-age=15552000"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
        X-Frame-Options "DENY"
        -Server
    }
    reverse_proxy cat-server:8000
}
```

Optional als zweite Hürde (Browser fragt vor Cat nach Name und Passwort, `caddy hash-password` erzeugt den Hash): vor `reverse_proxy` einfügen

```
    basic_auth {
        IHR_NAME HIER_DER_HASH
    }
```

### Ablauf (CLAUDE.md, Abschnitt 4)

```bash
cd /srv/docker/caddy
# 1. Sicherung mit Zeitstempel
sudo cp -a Caddyfile Caddyfile.bak-$(date +%Y%m%d-%H%M)
# 2. Block anhängen (Datei bleibt dieselbe, der Mount behält sie)
sudo tee -a Caddyfile >/dev/null <<'EOF'

ai.catscastlecloud.de {
    ... (Block von oben)
}
EOF
# 3. Prüfen, dann per Reload (kein Neustart) anwenden
docker exec docker-caddy-1 caddy validate --config /etc/caddy/Caddyfile
docker exec docker-caddy-1 caddy reload --config /etc/caddy/Caddyfile
# 4. Zertifikat abwarten (Log) und prüfen
docker logs --since 2m docker-caddy-1 2>&1 | grep -i -E "ai.catscastlecloud|certificate|error"
```

### Danach prüfen

- `https://ai.catscastlecloud.de` zeigt Cat mit Schloss, Anmeldung, Mikrofon-Abfrage.
- `https://catscastlecloud.de` (Nextcloud), `https://trafficnetwork.link` und das Portainer-Verhalten antworten wie vorher.
- Von außen (Mobilfunk): Login-Seite erreichbar, `/api/files` ohne Anmeldung `401`.

### Rollback

```bash
cd /srv/docker/caddy
sudo cp -a Caddyfile.bak-<Zeitstempel> Caddyfile
docker exec docker-caddy-1 caddy reload --config /etc/caddy/Caddyfile
```

Cat selbst wieder privat machen, ohne Caddy zu berühren: `CAT_TRUSTED_PROXIES` leeren. Der Block bleibt dann wirkungslos, solange Cat nicht mehr im Netz `docker_proxy` ist (Abschnitt `networks` in `docker-compose.yml` entfernen, `docker compose up -d --no-build backend`).

## Was bleibt öffentlich erreichbar

Alles, was Cat unter `/` ausliefert: die Login-Seite und `/health`. Hinter dem Login liegt alles andere. Der Satelliten-Weg (`/ws/voice` mit Token) wäre technisch ebenfalls erreichbar, die Token sind gehasht und die Versuche begrenzt; Satelliten nutzen weiter das LAN (`ws://192.168.0.10:8090`).
