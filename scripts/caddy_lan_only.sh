#!/usr/bin/env bash
# Cat nur im Heimnetz erreichbar und keine doppelte Passwortabfrage (docs/public-access.md).
#
# Ändert in /srv/docker/caddy/Caddyfile NUR den Block "ai.catscastlecloud.de":
#   - entfernt "basic_auth { ... }" (die zweite Passwortabfrage; Cats eigener Login bleibt),
#   - fügt vor reverse_proxy hinzu: alles außerhalb von 192.168.0.0/16 bekommt 403.
# Alle anderen Blöcke bleiben unverändert. Die Datei wird an Ort und Stelle überschrieben
# (der Mount im Container behält sie), vorher gibt es eine Sicherung mit Zeitstempel.
#
# Aufruf auf dem Server:   sudo bash /srv/homelm/scripts/caddy_lan_only.sh
# Rückgängig:              sudo bash /srv/homelm/scripts/caddy_lan_only.sh --rollback
set -euo pipefail

DIR=/srv/docker/caddy
FILE="$DIR/Caddyfile"
CONTAINER=docker-caddy-1

reload() {
  docker exec "$CONTAINER" caddy validate --config /etc/caddy/Caddyfile
  docker exec "$CONTAINER" caddy reload --config /etc/caddy/Caddyfile
}

if [[ "${1:-}" == "--rollback" ]]; then
  last=$(ls -1t "$DIR"/Caddyfile.bak-lan-* 2>/dev/null | head -n1 || true)
  [[ -n "$last" ]] || { echo "Keine Sicherung Caddyfile.bak-lan-* gefunden"; exit 1; }
  cat "$last" | tee "$FILE" >/dev/null
  reload
  echo "Zurückgesetzt auf $last"
  exit 0
fi

backup="$FILE.bak-lan-$(date +%Y%m%d-%H%M)"
cp -a "$FILE" "$backup"
echo "Sicherung: $backup"

tmp=$(mktemp)
python3 - "$FILE" "$tmp" <<'PY'
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()

m = re.search(r"(?m)^ai\.catscastlecloud\.de \{\n(.*?)^\}\n", text, re.S)
if not m:
    sys.exit("Block ai.catscastlecloud.de nicht gefunden")
body = m.group(1)

# 1. zweite Passwortabfrage entfernen (Hash bleibt nirgends stehen)
body = re.sub(r"(?m)^[ \t]*basic_?auth[^\n]*\{\n.*?^[ \t]*\}\n", "", body, flags=re.S)

# 2. Heimnetz-Sperre vor den Proxy setzen (einmalig)
if "@extern" not in body:
    guard = (
        "    # Nur Heimnetz (Router 192.168.1.1 und alles dahinter); von außen 403.\n"
        "    @extern not remote_ip 192.168.0.0/16\n"
        '    respond @extern "Forbidden" 403\n'
    )
    body = body.replace("    reverse_proxy cat-server:8000", guard + "    reverse_proxy cat-server:8000")
    if guard not in body:
        sys.exit("reverse_proxy cat-server:8000 nicht gefunden")

new = text[: m.start()] + "ai.catscastlecloud.de {\n" + body + "}\n" + text[m.end() :]
open(dst, "w", encoding="utf-8").write(new)
PY

echo "--- Diff (Hash maskiert) ---"
diff <(sed -E 's#\$2[aby]\$[^ ]+#<HASH>#g' "$backup") <(sed -E 's#\$2[aby]\$[^ ]+#<HASH>#g' "$tmp") || true

cat "$tmp" | tee "$FILE" >/dev/null
rm -f "$tmp"

if ! reload; then
  echo "Prüfung fehlgeschlagen: stelle die Sicherung wieder her"
  cat "$backup" | tee "$FILE" >/dev/null
  reload || true
  exit 1
fi
echo "Fertig. Prüfen: https://ai.catscastlecloud.de aus dem Heimnetz (Login von Cat) und von außen (403)."
