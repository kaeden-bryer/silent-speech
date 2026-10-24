#!/usr/bin/env bash
# Offline phone setup for the Ascent: a WiFi hotspot plus a trusted HTTPS certificate.
#
#   scripts/setup_network.sh certs [extra-ip ...]   make the local CA + server cert (re-run if the Ascent's IP changes)
#   scripts/setup_network.sh serve-ca               serve the CA on http://<ip>:8080/ca.crt so the iPhone can install it
#   scripts/setup_network.sh hotspot [ssid] [pass]  start the Ascent's own WiFi network (phone joins it)
#   scripts/setup_network.sh hotspot-down           stop the hotspot
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERTS="$ROOT/certs"
CON_NAME="silent-speech-hotspot"
HOTSPOT_IP="10.42.0.1"  # NetworkManager's default address for a shared (hotspot) connection

cmd_certs() {
  mkdir -p "$CERTS/public"
  cd "$CERTS"

  # The CA is created once and reused, so the phone only has to trust it once.
  if [[ ! -f ca.key ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
      -keyout ca.key -out ca.pem -subj "/CN=Silent Speech Local CA" \
      -addext "basicConstraints=critical,CA:TRUE" \
      -addext "keyUsage=critical,keyCertSign,cRLSign"
    chmod 600 ca.key
    echo "Created new CA (the phone must install it)."
  fi
  cp ca.pem public/ca.crt  # only this public file is ever served; ca.key stays private

  # Every name/IP the phone might type must be listed, or Safari rejects the cert.
  local sans="DNS:localhost,DNS:$(hostname),DNS:$(hostname).local,IP:127.0.0.1,IP:$HOTSPOT_IP"
  local ip
  for ip in $(hostname -I) "$@"; do
    [[ "$ip" == *:* ]] && continue  # skip IPv6
    sans+=",IP:$ip"
  done

  cat > server.ext <<EXT
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$sans
EXT
  openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=silent-speech"
  # iOS rejects server certs valid for more than 398 days.
  openssl x509 -req -sha256 -days 397 -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
    -out server.pem -extfile server.ext
  rm -f server.csr
  chmod 600 server.key

  echo "Server cert covers: $sans"
  echo "Next: '$0 serve-ca', open the printed URL on the iPhone, then install and trust it (see README)."
}

cmd_serve_ca() {
  [[ -f "$CERTS/public/ca.crt" ]] || { echo "Run '$0 certs' first." >&2; exit 1; }
  echo "On the iPhone (same network) open one of:"
  local ip
  for ip in $(hostname -I); do [[ "$ip" == *:* ]] || echo "  http://$ip:8080/ca.crt"; done
  cd "$CERTS/public" && exec python3 -m http.server 8080 --bind 0.0.0.0
}

cmd_hotspot() {
  local ssid="${1:-SilentSpeech}" pass="${2:-silentspeech}"
  local dev
  dev="$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')"
  [[ -n "$dev" ]] || { echo "No WiFi device found." >&2; exit 1; }
  nmcli con delete "$CON_NAME" >/dev/null 2>&1 || true
  # 5 GHz (channel 149, no radar-detection delay) is far less crowded than 2.4 GHz at a venue.
  # Fall back to 2.4 GHz if the card can't host a 5 GHz network.
  if ! nmcli dev wifi hotspot ifname "$dev" con-name "$CON_NAME" ssid "$ssid" password "$pass" band a channel 149; then
    echo "5 GHz hotspot failed, falling back to 2.4 GHz." >&2
    nmcli con delete "$CON_NAME" >/dev/null 2>&1 || true
    nmcli dev wifi hotspot ifname "$dev" con-name "$CON_NAME" ssid "$ssid" password "$pass"
  fi
  echo "Hotspot up on $dev: join '$ssid' (password '$pass') on the phone, then open https://$HOTSPOT_IP:8000"
}

cmd_hotspot_down() {
  nmcli con down "$CON_NAME"
}

case "${1:-}" in
  certs) shift; cmd_certs "$@" ;;
  serve-ca) cmd_serve_ca ;;
  hotspot) shift; cmd_hotspot "$@" ;;
  hotspot-down) cmd_hotspot_down ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
