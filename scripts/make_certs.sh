#!/usr/bin/env bash
# Erzeugt eine eigene Zertifizierungsstelle (CA) und ein Serverzertifikat für Cat (HTTPS im LAN).
#
#   cd /srv/homelm && bash scripts/make_certs.sh
#
# Ergebnis:
#   data/certs/ca.crt       die CA, auf Geräten als vertrauenswürdig installieren (öffentlich, unkritisch)
#   data/certs/server.crt   Zertifikat für Cat (gültig 800 Tage)
#   data/certs/server.key   Schlüssel für Cat (nur Besitzer lesbar)
#   ca-private/ca.key       Schlüssel der CA. Liegt BEWUSST außerhalb von data/, der Cat-Container
#                           sieht ihn nie. Sichern oder nach der Einrichtung löschen (dann gibt es
#                           für die Erneuerung eine neue CA, die auf den Geräten neu installiert wird).
#
# Anpassen: SAN="IP:192.168.0.10,DNS:homeserver,DNS:cat.lan" bash scripts/make_certs.sh
# Erneuern vor Ablauf: Skript erneut starten (die vorhandene CA wird weiterverwendet, solange
# ca-private/ca.key da ist), dann `docker compose restart backend`.
set -euo pipefail

OUT="${OUT:-data/certs}"
CA_DIR="${CA_DIR:-ca-private}"
SAN="${SAN:-IP:192.168.0.10,DNS:homeserver,DNS:localhost,IP:127.0.0.1}"
DAYS="${DAYS:-800}"

mkdir -p "$OUT" "$CA_DIR"
chmod 700 "$CA_DIR"
umask 077

if [ ! -f "$CA_DIR/ca.key" ] || [ ! -f "$OUT/ca.crt" ]; then
  echo "Erzeuge neue CA (10 Jahre) ..."
  openssl ecparam -name prime256v1 -genkey -noout -out "$CA_DIR/ca.key"
  cat > "$CA_DIR/ca.cnf" <<'CNF'
[req]
distinguished_name = dn
prompt = no
[dn]
O = HomeLM
CN = Cat Heimserver CA
[v3]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
CNF
  openssl req -x509 -new -key "$CA_DIR/ca.key" -sha256 -days 3650 \
    -config "$CA_DIR/ca.cnf" -extensions v3 -out "$OUT/ca.crt"
fi

echo "Erzeuge Serverzertifikat für: $SAN"
openssl ecparam -name prime256v1 -genkey -noout -out "$OUT/server.key"
cat > "$CA_DIR/server.cnf" <<'CNF'
[req]
distinguished_name = dn
prompt = no
[dn]
O = HomeLM
CN = Cat
CNF
openssl req -new -key "$OUT/server.key" -config "$CA_DIR/server.cnf" -out "$CA_DIR/server.csr"
cat > "$CA_DIR/server.ext" <<EXT
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = $SAN
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
EXT
openssl x509 -req -in "$CA_DIR/server.csr" -CA "$OUT/ca.crt" -CAkey "$CA_DIR/ca.key" \
  -CAserial "$CA_DIR/ca.srl" -CAcreateserial -days "$DAYS" -sha256 \
  -extfile "$CA_DIR/server.ext" -out "$OUT/server.crt"
rm -f "$CA_DIR/server.csr"

chmod 644 "$OUT/ca.crt" "$OUT/server.crt"
chmod 600 "$OUT/server.key"
openssl verify -CAfile "$OUT/ca.crt" "$OUT/server.crt"
openssl x509 -in "$OUT/server.crt" -noout -subject -enddate -ext subjectAltName
echo
echo "Fertig. CA zum Installieren auf Geräten: $OUT/ca.crt"
echo "Cat neu starten:  docker compose up -d --no-build backend"
