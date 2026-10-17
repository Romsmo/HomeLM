#!/usr/bin/env bash
# Schaltet ai.catscastlecloud.de frei: hängt einen Block an das Caddyfile an (docs/public-access.md).
#
#   cd /srv/homelm && sudo bash scripts/enable_public_access.sh
#
# Ablauf nach CLAUDE.md, Abschnitt 4: Sicherung mit Zeitstempel, Block anhängen, mit
# `caddy validate` prüfen (bei Fehler wird die Sicherung sofort zurückgespielt), per Reload
# anwenden (kein Neustart), danach Zertifikat-Log und Gegenprobe der bestehenden Seiten.
# Das Passwort für den Caddy-Login wird nur gehasht und nirgends gespeichert (außer dem Hash im
# Caddyfile). Ohne Caddy-Login: NO_BASIC_AUTH=1 sudo -E bash scripts/enable_public_access.sh
set -euo pipefail

CADDYFILE="${CADDYFILE:-/srv/docker/caddy/Caddyfile}"
CONTAINER="${CONTAINER:-docker-caddy-1}"
HOST="${HOST:-ai.catscastlecloud.de}"
UPSTREAM="${UPSTREAM:-cat-server:8000}"

if [ ! -w "$CADDYFILE" ]; then
  echo "Keine Schreibrechte auf $CADDYFILE. Bitte mit sudo starten." >&2
  exit 1
fi
if grep -q "^$HOST" "$CADDYFILE"; then
  echo "In $CADDYFILE gibt es schon einen Block für $HOST. Nichts zu tun."
  exit 0
fi
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container $CONTAINER läuft nicht." >&2
  exit 1
fi
if ! docker exec "$CONTAINER" getent hosts "${UPSTREAM%%:*}" >/dev/null 2>&1; then
  echo "Caddy erreicht ${UPSTREAM%%:*} nicht. Läuft Cat im Netz docker_proxy?" >&2
  echo "  cd /srv/homelm && docker compose up -d --no-build backend" >&2
  exit 1
fi

AUTH=""
if [ "${NO_BASIC_AUTH:-0}" != "1" ]; then
  read -r -p "Benutzername für den Caddy-Login: " LOGIN_USER
  read -r -s -p "Passwort für den Caddy-Login (mindestens 16 Zeichen): " LOGIN_PW
  echo
  if [ "${#LOGIN_PW}" -lt 16 ]; then
    echo "Zu kurz (${#LOGIN_PW} Zeichen). Abbruch, es wurde nichts geändert." >&2
    exit 1
  fi
  HASH="$(printf '%s\n' "$LOGIN_PW" | docker exec -i "$CONTAINER" caddy hash-password)"
  unset LOGIN_PW
  AUTH="    basic_auth {
        ${LOGIN_USER} ${HASH}
    }
"
fi

BACKUP="$CADDYFILE.bak-$(date +%Y%m%d-%H%M)"
cp -a "$CADDYFILE" "$BACKUP"
echo "Sicherung: $BACKUP"

cat >> "$CADDYFILE" <<EOF

$HOST {
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
${AUTH}    reverse_proxy $UPSTREAM
}
EOF

if ! docker exec "$CONTAINER" caddy validate --config /etc/caddy/Caddyfile; then
  echo "Prüfung fehlgeschlagen, spiele die Sicherung zurück." >&2
  cp -a "$BACKUP" "$CADDYFILE"
  exit 1
fi
docker exec "$CONTAINER" caddy reload --config /etc/caddy/Caddyfile
echo "Caddy neu geladen. Zertifikat wird geholt (kann eine halbe Minute dauern) ..."
sleep 20
docker logs --since 1m "$CONTAINER" 2>&1 | grep -i -E "$HOST|certificate|obtain|error" | tail -8 || true

echo
echo "Gegenprobe:"
for url in "https://$HOST/health" https://catscastlecloud.de/status.php https://trafficnetwork.link/; do
  printf '  %s -> ' "$url"
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 "$url" || echo "Fehler"
done
echo "  (der Cat-Link antwortet mit 401, solange der Caddy-Login davor steht, das ist richtig)"
echo
echo "Rollback: sudo cp -a $BACKUP $CADDYFILE && docker exec $CONTAINER caddy reload --config /etc/caddy/Caddyfile"
