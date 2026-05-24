#!/usr/bin/env bash
set -Eeuo pipefail

INSTALLER_DIR="${EXPRESSVPN_INSTALLER_DIR:-/installer}"
ACTIVATION_CODE_FILE="${EXPRESSVPN_ACTIVATION_CODE_FILE:-/run/secrets/expressvpn_activation_code}"
LOCATION="${EXPRESSVPN_LOCATION:-}"
PROTOCOL="${EXPRESSVPN_PROTOCOL:-lightwayudp}"
SOCKS_LISTEN_ADDR="${SOCKS_LISTEN_ADDR:-0.0.0.0}"
SOCKS_PORT="${SOCKS_PORT:-1080}"

log() {
  printf '[expressvpn-sidecar] %s\n' "$*"
}

ensure_tun() {
  if [[ ! -c /dev/net/tun ]]; then
    log "missing /dev/net/tun; run with devices: /dev/net/tun:/dev/net/tun"
    exit 1
  fi
}

find_installer() {
  find "$INSTALLER_DIR" -maxdepth 1 -type f -iname 'expressvpn-linux*.run' | sort -V | tail -n 1
}

install_expressvpn() {
  if command -v expressvpnctl >/dev/null 2>&1; then
    return
  fi

  local installer
  installer="$(find_installer || true)"
  if [[ -z "$installer" ]]; then
    log "ExpressVPN installer not found in $INSTALLER_DIR"
    log "Place the official Linux Universal Installer at $INSTALLER_DIR/expressvpn-linux-*.run"
    exit 78
  fi

  log "installing ExpressVPN from $installer"
  chmod +x "$installer" || true
  if ! "$installer" -- --headless; then
    log "headless install flag failed; retrying installer with default arguments"
    "$installer"
  fi
}

login_expressvpn() {
  if [[ ! -f "$ACTIVATION_CODE_FILE" ]]; then
    log "activation code file not found: $ACTIVATION_CODE_FILE"
    exit 78
  fi
  chmod 600 "$ACTIVATION_CODE_FILE" || true

  if expressvpnctl status >/tmp/expressvpn-status 2>&1; then
    if ! grep -qi 'not.*logged\|sign.*in\|login' /tmp/expressvpn-status; then
      log "ExpressVPN appears to be logged in"
      return
    fi
  fi

  log "logging in with activation code file"
  expressvpnctl login "$ACTIVATION_CODE_FILE"
}

connect_expressvpn() {
  log "enabling background mode"
  expressvpnctl background enable || true

  log "enabling network lock"
  expressvpnctl set networklock true || true

  if [[ -n "$PROTOCOL" ]]; then
    log "setting protocol: $PROTOCOL"
    expressvpnctl set protocol "$PROTOCOL" || true
  fi

  if [[ -n "$LOCATION" ]]; then
    log "connecting to location: $LOCATION"
    expressvpnctl connect "$LOCATION"
  else
    log "connecting to smart/recent location"
    expressvpnctl connect
  fi
}

start_proxy() {
  log "starting SOCKS5 proxy on ${SOCKS_LISTEN_ADDR}:${SOCKS_PORT}"
  exec microsocks -i "$SOCKS_LISTEN_ADDR" -p "$SOCKS_PORT"
}

ensure_tun
install_expressvpn
login_expressvpn
connect_expressvpn
start_proxy
