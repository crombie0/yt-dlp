#!/usr/bin/env bash
set -Eeuo pipefail

INSTALLER_DIR="${EXPRESSVPN_INSTALLER_DIR:-/installer}"
ACTIVATION_CODE_FILE="${EXPRESSVPN_ACTIVATION_CODE_FILE:-/run/secrets/expressvpn_activation_code}"
LOCATION="${EXPRESSVPN_LOCATION:-}"
PROTOCOL="${EXPRESSVPN_PROTOCOL:-lightwaytcp}"
SOCKS_LISTEN_ADDR="${SOCKS_LISTEN_ADDR:-0.0.0.0}"
SOCKS_PORT="${SOCKS_PORT:-1080}"
CTL_TIMEOUT="${EXPRESSVPN_CTL_TIMEOUT:-30}"
CONNECT_TIMEOUT="${EXPRESSVPN_CONNECT_TIMEOUT:-240}"

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
  sh "$installer" --accept --quiet --noprogress -- --no-gui --sysvinit
}

expressvpnctl_ok() {
  local output
  if ! output="$(expressvpnctl --timeout "$CTL_TIMEOUT" "$@" 2>&1)"; then
    printf '%s\n' "$output"
    return 1
  fi
  if grep -qi 'Timed out after' <<<"$output"; then
    printf '%s\n' "$output"
    return 1
  fi
  printf '%s\n' "$output"
}

start_expressvpn_daemon() {
  local service_name=""
  if [[ -f /etc/init.d/expressvpn-service ]]; then
    service_name="expressvpn-service"
  elif [[ -f /etc/init.d/expressvpn ]]; then
    service_name="expressvpn"
  else
    log "ExpressVPN init script not found"
    exit 1
  fi

  log "starting ExpressVPN daemon via ${service_name}"
  service "$service_name" stop >/dev/null 2>&1 || true
  service "$service_name" start

  for _ in $(seq 1 30); do
    if expressvpnctl_ok status >/tmp/expressvpn-status 2>&1; then
      return
    fi
    sleep 1
  done

  log "ExpressVPN daemon did not become ready"
  sed -n '1,120p' /tmp/expressvpn-status || true
  exit 1
}

login_expressvpn() {
  if [[ ! -f "$ACTIVATION_CODE_FILE" ]]; then
    log "activation code file not found: $ACTIVATION_CODE_FILE"
    exit 78
  fi
  chmod 600 "$ACTIVATION_CODE_FILE" || true

  if expressvpnctl_ok status >/tmp/expressvpn-status 2>&1; then
    if ! grep -qi 'not.*logged\|sign.*in\|login' /tmp/expressvpn-status; then
      log "ExpressVPN appears to be logged in"
      return
    fi
  fi

  log "logging in with activation code file"
  expressvpnctl_ok login "$ACTIVATION_CODE_FILE"
}

connect_expressvpn() {
  log "enabling background mode"
  expressvpnctl_ok background enable || true

  # Keep Network Lock off until the tunnel is established. In container
  # namespaces, enabling it too early can block ExpressVPN's own token refresh.
  log "temporarily disabling network lock for connection setup"
  expressvpnctl_ok set networklock false || true

  if [[ -n "$PROTOCOL" ]]; then
    log "setting protocol: $PROTOCOL"
    expressvpnctl_ok set protocol "$PROTOCOL" || true
  fi

  if [[ -n "$LOCATION" ]]; then
    log "connecting to location: $LOCATION"
    expressvpnctl_ok connect "$LOCATION"
  else
    log "connecting to smart/recent location"
    expressvpnctl_ok connect
  fi

  log "waiting for VPN connection"
  local state vpn_ip
  for _ in $(seq 1 "$CONNECT_TIMEOUT"); do
    state="$(expressvpnctl_ok get connectionstate 2>/dev/null || true)"
    vpn_ip="$(expressvpnctl_ok get vpnip 2>/dev/null || true)"
    if [[ "$state" == "Connected" && -n "$vpn_ip" && "$vpn_ip" != "Unknown" ]]; then
      log "VPN connected"
      log "enabling network lock"
      expressvpnctl_ok set networklock true || true
      return
    fi
    sleep 1
  done

  log "VPN did not connect within ${CONNECT_TIMEOUT}s"
  log "last connection state: ${state:-unknown}"
  log "last VPN IP: ${vpn_ip:-unknown}"
  exit 1
}

start_proxy() {
  log "starting SOCKS5 proxy on ${SOCKS_LISTEN_ADDR}:${SOCKS_PORT}"
  exec microsocks -i "$SOCKS_LISTEN_ADDR" -p "$SOCKS_PORT"
}

ensure_tun
install_expressvpn
start_expressvpn_daemon
login_expressvpn
connect_expressvpn
start_proxy
