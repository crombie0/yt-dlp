#!/usr/bin/env bash
set -Eeuo pipefail

SOCKS_LISTEN_ADDR="${SOCKS_LISTEN_ADDR:-127.0.0.1}"
SOCKS_PORT="${SOCKS_PORT:-1080}"
CHECK_URL="${EXPRESSVPN_HEALTHCHECK_URL:-https://api.ipify.org?format=json}"

curl \
  --fail \
  --silent \
  --show-error \
  --max-time 10 \
  --socks5-hostname "${SOCKS_LISTEN_ADDR}:${SOCKS_PORT}" \
  "$CHECK_URL" \
  | grep -q '"ip"'
