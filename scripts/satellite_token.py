"""Legt einen Satelliten an: erzeugt ein Token und trägt nur dessen Hash ein.

Auf dem Server (ohne weitere Pakete, nutzt das Backend-Image):

    cd /srv/homelm
    docker compose exec -T backend python - kueche-pi Küche --data /data \\
        < scripts/satellite_token.py

Oder lokal mit PyYAML:

    python scripts/satellite_token.py kueche-pi Küche --data data

Das Token wird genau einmal ausgegeben (in die config.yaml des Satelliten eintragen). In
`data/config/satellites.yaml` landet nur der SHA-256-Hash. Ein bestehender Eintrag mit derselben
id bekommt ein neues Token (das alte ist dann ungültig). Danach Cat neu starten, damit das
Register neu gelesen wird: `docker compose restart backend`.
"""

import argparse
import hashlib
import os
import re
import secrets
from pathlib import Path

import yaml


def hash_token(token: str) -> str:
    """Muss zu cat.satellites.hash_token passen (SHA-256, hex)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("id", help="Name des Satelliten, z. B. kueche-pi (a-z, 0-9, - und _)")
    parser.add_argument("room", help="Raum, wie in der Geräte-Allowlist, z. B. Küche")
    parser.add_argument(
        "--data", default=os.environ.get("CAT_DATA_DIR", "data"), help="Datenordner"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", args.id):
        parser.error("id darf nur a-z, 0-9, - und _ enthalten (max. 40 Zeichen)")
    path = Path(args.data) / "config" / "satellites.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    entries = [e for e in (data or {}).get("satellites", []) if e.get("id") != args.id]
    token = secrets.token_urlsafe(32)
    entries.append({"id": args.id, "room": args.room.strip(), "token_sha256": hash_token(token)})
    header = (
        "# Registrierte Satelliten (nur Hashes, keine Tokens), erzeugt mit satellite_token.py\n"
    )
    body = yaml.safe_dump({"satellites": entries}, allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")
    print(f"Satellit '{args.id}' (Raum {args.room}) eingetragen in {path}")
    print("Token (nur jetzt sichtbar, in die config.yaml des Satelliten eintragen):")
    print(token)
    print("Danach Cat neu starten: docker compose restart backend")


if __name__ == "__main__":
    main()
