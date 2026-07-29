#!/usr/bin/env sh
set -eu

DOMAIN="${1:-alesturslimitadaapi.top}"
NGINX_CONTAINER="${NGINX_CONTAINER:-flask_nginx}"

if ! command -v certbot >/dev/null 2>&1; then
  echo "ERROR: certbot is not installed on this server." >&2
  exit 2
fi

echo "==> Current certificate status"
sh "$(dirname "$0")/check_origin_ssl_expiry.sh" "$DOMAIN" || true

echo "==> Running certbot renew"
certbot renew --deploy-hook "docker exec $NGINX_CONTAINER nginx -s reload"

echo "==> Reloading nginx container"
docker exec "$NGINX_CONTAINER" nginx -s reload

echo "==> Certificate status after renew"
sh "$(dirname "$0")/check_origin_ssl_expiry.sh" "$DOMAIN" || true
