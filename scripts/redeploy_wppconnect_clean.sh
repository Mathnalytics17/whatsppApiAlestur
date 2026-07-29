#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

WIPE_SESSION="false"
if [ "${1:-}" = "--wipe-session" ]; then
  WIPE_SESSION="true"
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

echo "==> Using compose command: $COMPOSE"
echo "==> WhatsApp Web version: ${WPPCONNECT_WHATSAPP_VERSION:-2.3000.1044015310-alpha}"

echo "==> Removing old/stuck WPPConnect containers"
WPP_CONTAINERS="$(docker ps -aq --filter "name=wppconnect" || true)"
if [ -n "$WPP_CONTAINERS" ]; then
  docker rm -f $WPP_CONTAINERS >/dev/null 2>&1 || true
fi

find_volume() {
  suffix="$1"
  docker volume ls --format '{{.Name}}' | grep "${suffix}$" | head -n 1 || true
}

USER_DATA_VOLUME="$(find_volume "_wppconnect_user_data")"
TOKEN_VOLUME="$(find_volume "_wppconnect_tokens")"

if [ "$WIPE_SESSION" = "true" ]; then
  echo "==> Wiping WPPConnect session volumes. QR login/token setup may be required again."
  [ -n "$USER_DATA_VOLUME" ] && docker volume rm "$USER_DATA_VOLUME" >/dev/null 2>&1 || true
  [ -n "$TOKEN_VOLUME" ] && docker volume rm "$TOKEN_VOLUME" >/dev/null 2>&1 || true
else
  if [ -n "$USER_DATA_VOLUME" ]; then
    echo "==> Removing stale Chromium lock files from volume: $USER_DATA_VOLUME"
    docker run --rm -v "$USER_DATA_VOLUME:/data" alpine sh -c \
      "find /data \( -name 'SingletonLock' -o -name 'SingletonSocket' -o -name 'SingletonCookie' -o -name 'DevToolsActivePort' \) -delete" \
      >/dev/null
  else
    echo "==> No existing WPPConnect userData volume found"
  fi
fi

echo "==> Building WPPConnect image"
$COMPOSE build wppconnect

echo "==> Starting WPPConnect"
$COMPOSE up -d wppconnect

echo "==> WPPConnect status"
docker ps --filter "name=wppconnect" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo "==> Last logs"
docker logs --tail=80 wppconnect
