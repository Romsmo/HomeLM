# Server-Inventar (Stand 2026-10-17, nur lesend erhoben, ohne Secrets)

Erhoben per SSH als Benutzer `catscastle`. Zuerst ohne Docker-Zugriff, nach Aufnahme in die Gruppe `docker` (durch den Nutzer) auch mit `docker ps/stats/network ls`. Es wurde nichts geändert. nftables bleibt ungelesen (siehe "Nicht geprüft").

## Rechner

| Punkt | Wert |
|---|---|
| Host | `homeserver`, Debian 13 (trixie), Kernel 6.12.111 |
| CPU | Intel Core i5-8500T, 6 Kerne, 2,1 GHz, keine GPU |
| RAM | **7,5 GiB gesamt**, davon ca. 5,1 GiB verfügbar (Stand: 2,5 GiB belegt, Rest Cache) |
| Swap | 7,8 GiB, **596 MiB belegt** |
| Last | ca. 0,1 bis 0,2 (Uptime 6,8 Tage) |
| Docker | 29.8.2 (Daemon läuft) |
| Netzwerk | `eno1` 192.168.0.10/24 (Standardroute über 192.168.0.1), `wlan0` 192.168.1.78/24 ist aktiv |

## Datenträger

| Mount | Größe | Belegt | Frei |
|---|---|---|---|
| `/` (NVMe) | 226 GB | 77 GB (36 %) | 138 GB |
| `/mnt/intensodrive` (USB-SSD) | 469 GB | 361 GB (**82 %**) | 85 GB |

## Dienste (aus den Compose-Dateien in `/srv/docker`, Secrets maskiert)

Compose-Verbund: `compose.yaml`, `compose.extra.yaml`, `compose.portainer-proxy.yaml`, `compose.trafficnetwork.yaml` (zusammengestellt über `COMPOSE_FILE` in der nicht lesbaren `.env`).

- **Caddy** (`caddy:2`, Ports 80 und 443 auf allen Adressen, Netzwerke `proxy` und `trafficnetwork`). Caddyfile:
  - `catscastlecloud.de` an Nextcloud (`app:80`).
  - `http://192.168.0.10, http://homeserver` an Nextcloud (reines HTTP, ohne TLS).
  - `trafficnetwork.link` an `trafficnetwork-server:3000`.
  - `portainer.catscastlecloud.de` nur für `remote_ip 192.168.0.0/24`, sonst 403.
- **Nextcloud** (`app`, `cron`, Image `nextcloud:${NC_VERSION}-apache`), **MariaDB 11.4**, **Redis 7**. Netzwerke `proxy` und `backend`. Daten unter `/mnt/intensodrive/data`.
- **openHAB** (`network_mode: host`, serieller Adapter Prolific als `/dev/ttyUSB0`). Java-Prozess belegt ca. 1,1 GB RAM.
- **cloudflare-ddns** (`network_mode: host`) für `trafficnetwork.link`.
- **Portainer** (nur an `192.168.0.10:9443`, mountet den Docker-Socket).
- **Trafficnetwork** liegt in `/srv/trafficnetwork` (Node-Server ca. 220 MB, PostgreSQL mit mehreren Prozessen), eigenes Netzwerk `trafficnetwork` (extern).

## Offene Ports (`ss -ltn`)

| Port | Adresse | Wer |
|---|---|---|
| 80, 443 | alle | Caddy |
| 22 | alle | SSH |
| 9443 | 192.168.0.10 | Portainer |
| **8080**, 8443, 5007 | alle | openHAB (Host-Netzwerk) |
| 8101, 41185 | nur localhost | openHAB-Konsole bzw. intern |
| 8090, 8091, 8100 | | **frei** |

openHAB: `GET http://127.0.0.1:8080/rest/` antwortet mit HTTP 200. Konfiguration liegt unter `/srv/docker/openhab/conf` (items, things, rules, sitemaps und weitere).

## Größte Speicherverbraucher

openHAB-JVM ca. 1,1 GB, Trafficnetwork-Node ca. 220 MB, PostgreSQL-Prozesse zusammen ca. 0,9 GB (mit geteiltem Speicher), dockerd ca. 125 MB, Apache/Nextcloud ca. 60 MB, MariaDB ca. 60 MB.

## Container (Stand 2026-10-17, `docker ps -a`, `docker stats`)

| Container | Status | RAM |
|---|---|---|
| docker-openhab-1 (4.2.2) | healthy, 6 Tage | 1,12 GiB |
| trafficnetwork-server-postgres-1 (PostGIS 16) | healthy, 6 Tage | 1,67 GiB (inkl. Cache) |
| trafficnetwork-server-server-1 | healthy, 3 Tage | 253 MiB |
| docker-app-1 / docker-cron-1 (Nextcloud 33) | 6 Tage | 140 MiB / 14 MiB |
| docker-db-1 (MariaDB 11.4) / docker-redis-1 | 6 Tage | 62 MiB / 3 MiB |
| docker-caddy-1 / docker-portainer-1 / docker-cloudflare-ddns-1 | 6 Tage | 49 / 40 / 23 MiB |
| tn-ingest (ingestion) | **Exited (0) vor 8 Tagen** (kein Fehler, läuft nicht dauerhaft) | |

Keine Container haben ein `mem_limit` (Limit zeigt die gesamten 7,5 GiB). Docker-Netzwerke: `docker_proxy` (Caddy, Nextcloud, Portainer), `docker_backend` (DB, Redis), `trafficnetwork` (extern), `docker_default`, `bridge`. Caddy hängt in `docker_proxy` und `trafficnetwork`. Volumes: u. a. `trafficnetwork-server_postgres-data`, `docker_caddy_data`, `docker_portainer_data` (zusammen 23 GB). Docker-Images 5,7 GB, Build-Cache 2,2 GB (1,3 GB räumbar, wird nicht angefasst).

## Abweichungen von `CLAUDE.md` Abschnitt 2

1. **RAM ist 7,5 GiB, kein Upgrade erfolgt.** Es wird schon etwas ausgelagert (596 MiB Swap).
2. Die USB-SSD ist 469 GB groß und zu **82 % voll** (361 GB belegt, nicht ca. 223 GB). Ein Backup-Job fehlt weiterhin.
3. Der Benutzer `catscastle` ist **nicht** in der Gruppe `docker` (Socket gehört `root:docker`, Gruppe `docker` hat die ID 989). `sudo` verlangt ein Passwort.
4. `/srv` gehört `root`: **`/srv/homelm` existiert nicht und kann ohne Root nicht angelegt werden.**
5. Unbekanntes Verzeichnis `/srv/rettung` (u. a. `nextcloud.log.beschaedigt` und ein Nextcloud-`appdata`-Ordner vom 27.12.2023). Wird nicht angefasst.
6. Port **8080 gehört openHAB**. Cat darf ihn nicht verwenden (Standard in Cat ist künftig 8090).
7. `wlan0` (192.168.1.78) ist aktiv, die Route 192.168.1.0/24 besteht.

## Nicht geprüft (braucht Docker- oder Root-Rechte)

- Welche Quell-IP Caddy tatsächlich sieht (Hintergrund: Portainer liefert aus dem LAN 403).
- nftables inklusive Tabelle `ohtunnel`, ob der IoT-Weg über `wlan0` funktioniert.
- Inhalt der `.env` (bewusst nicht gelesen), Zustand `europe-data` von `ingestion` (wird nicht angefasst).
