#!/usr/bin/env sh
set -eu

DOMAIN="${1:-alesturslimitadaapi.top}"
WARN_DAYS="${SSL_WARN_DAYS:-21}"
CERT_PATH="${SSL_CERT_PATH:-/etc/letsencrypt/live/$DOMAIN/fullchain.pem}"

if [ ! -f "$CERT_PATH" ]; then
  echo "ERROR: certificate file not found: $CERT_PATH" >&2
  exit 2
fi

END_DATE="$(openssl x509 -enddate -noout -in "$CERT_PATH" | sed 's/^notAfter=//')"
END_TS="$(date -d "$END_DATE" +%s)"
NOW_TS="$(date +%s)"
DAYS_LEFT="$(( (END_TS - NOW_TS) / 86400 ))"

echo "Domain: $DOMAIN"
echo "Certificate: $CERT_PATH"
echo "Expires: $END_DATE"
echo "Days left: $DAYS_LEFT"

if [ "$DAYS_LEFT" -le "$WARN_DAYS" ]; then
  echo "WARNING: certificate expires in $DAYS_LEFT days or less."
  exit 1
fi

echo "OK: certificate has more than $WARN_DAYS days left."
