#!/bin/bash
# Avvia OctoHubs in development mode raggiungibile dalla rete locale.

set -e

DEFAULT_IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
LAN_IP=""

if [ -n "$DEFAULT_IFACE" ]; then
    LAN_IP="$(ipconfig getifaddr "$DEFAULT_IFACE" 2>/dev/null || true)"
fi

if [ -z "$LAN_IP" ] || [[ "$LAN_IP" == 127.* ]]; then
    LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
fi

if [ -z "$LAN_IP" ] || [[ "$LAN_IP" == 127.* ]]; then
    LAN_IP="$(ifconfig | awk '$1 == "inet" && $2 !~ /^127[.]/ {print $2; exit}')"
fi

export OCTOHUBS_HOST="${OCTOHUBS_HOST:-0.0.0.0}"
export OCTOHUBS_PORT="${OCTOHUBS_PORT:-5050}"

echo "=========================================="
echo "OctoHubs LAN test mode"
if [ -n "$LAN_IP" ]; then
    echo "Plugin Emby Base URL: http://${LAN_IP}:${OCTOHUBS_PORT}"
    echo "Plugin Emby Endpoint: http://${LAN_IP}:${OCTOHUBS_PORT}/api/emby/event-bridge/events"
else
    echo "IP LAN non rilevato automaticamente. Controlla Preferenze di rete macOS."
fi
echo "=========================================="

exec ./start_dev.sh
