#!/bin/bash
# wg-tray leak-protection hook for macOS, invoked from a tunnel's
# PostUp/PreDown lines (see wgtray/leak_protection.py, which writes the
# derived .conf that calls this). Root-only — wg-quick already runs
# PostUp/PreDown as root, same as the `wg-quick up/down` invocation itself.
#
# Usage: leak_protection_macos.sh up   <tunnel-dns-ip> <endpoint-port>
#        leak_protection_macos.sh down <tunnel-dns-ip> <endpoint-port>
#
# What "up" does:
#   1. Snapshot the current physical interface's IPv6 setting and DNS
#      servers to a state file, so "down" can restore them exactly.
#   2. Turn off IPv6 on the physical interface (most WireGuard configs
#      only route 0.0.0.0/0, so IPv6 would otherwise bypass the tunnel).
#   3. Point the physical interface's DNS at the tunnel's DNS server,
#      so leak-testing sites see the tunnel's resolver.
#   4. Load a pf anchor that: allows DHCP, allows the WireGuard handshake
#      UDP port outbound (so the tunnel can (re)establish), passes all
#      traffic on utun*, and blocks everything else on the physical
#      interface, including port 53 direct to any DNS server that isn't
#      going through the tunnel.
#
# What "down" does: unloads the pf anchor and restores the snapshotted
# IPv6/DNS settings — in that order, so connectivity comes back before
# leak protection is guaranteed lifted (favors "don't leak" over "don't
# briefly interrupt connectivity" during the flip).
set -euo pipefail

ACTION="${1:?up or down required}"
TUNNEL_DNS="${2:-}"
ENDPOINT_PORT="${3:-51820}"

STATE_DIR="$HOME/.config/wg-tray"
SNAPSHOT_FILE="$STATE_DIR/.leak_protection_snapshot"
ANCHOR_NAME="wg-tray-leakguard"
PF_CONF="/tmp/wg-tray-leakguard.pf.conf"

mkdir -p "$STATE_DIR"

physical_service() {
    # Map the interface behind the default route to a networksetup
    # "service name" (e.g. "Wi-Fi"), which is what -setv6off/-setdnsservers
    # take instead of a raw device name.
    local dev
    dev="$(route -n get default 2>/dev/null | awk '/interface: / {print $2}')"
    [ -z "$dev" ] && return 1
    networksetup -listallhardwareports | awk -v dev="$dev" '
        /^Hardware Port:/ { port = substr($0, index($0, ":") + 2) }
        $0 ~ "^Device: " dev "$" { print port; exit }
    '
}

physical_device() {
    route -n get default 2>/dev/null | awk '/interface: / {print $2}'
}

do_up() {
    local service dev
    service="$(physical_service)" || { echo "leak-protection: no default route, skipping" >&2; return 0; }
    dev="$(physical_device)"

    # --- Snapshot current state (only if we haven't already, so
    # repeated `up` calls — e.g. wg-quick retries — don't clobber a good
    # snapshot with an already-locked-down one) ---
    if [ ! -f "$SNAPSHOT_FILE" ]; then
        local v6_state dns_servers
        v6_state="$(networksetup -getinfo "$service" | awk -F': ' '/IPv6: /{print $2; exit}')"
        dns_servers="$(networksetup -getdnsservers "$service" 2>/dev/null | tr '\n' ' ')"
        {
            echo "SERVICE=$service"
            echo "V6_STATE=$v6_state"
            echo "DNS_SERVERS=$dns_servers"
        } > "$SNAPSHOT_FILE"
    fi

    # --- IPv6 off (most configs are v4-only AllowedIPs, so v6 would
    # otherwise route around the tunnel entirely) ---
    networksetup -setv6off "$service" 2>/dev/null || true

    # --- Pin DNS to the tunnel's resolver ---
    if [ -n "$TUNNEL_DNS" ]; then
        networksetup -setdnsservers "$service" "$TUNNEL_DNS" 2>/dev/null || true
    fi

    # --- pf kill switch: block the physical interface except DHCP and
    # the WireGuard handshake; pass everything on utun*. This is what
    # actually stops leaks if the tunnel drops, unlike DNS/v6 alone. ---
    cat > "$PF_CONF" <<EOF
# wg-tray leak-guard anchor — regenerated on every connect, safe to
# overwrite. Blocks $dev except DHCP + the WireGuard endpoint's own port
# (needed for the handshake itself), passing everything on utun*.
block drop on $dev all
pass out on $dev proto udp from any to any port 67:68 keep state
pass out quick on $dev proto udp from any to any port $ENDPOINT_PORT keep state
pass on utun0:0 all
pass on utun1:0 all
pass on utun2:0 all
pass on utun3:0 all
pass on utun4:0 all
pass on utun5:0 all
pass on utun6:0 all
pass on utun7:0 all
pass on utun8:0 all
pass on utun9:0 all
pass on lo0 all
EOF

    pfctl -a "$ANCHOR_NAME" -f "$PF_CONF" 2>/dev/null
    pfctl -e 2>/dev/null || true
}

do_down() {
    # Unload the kill switch first so connectivity is available again...
    pfctl -a "$ANCHOR_NAME" -F all 2>/dev/null || true
    rm -f "$PF_CONF"

    # ...then restore whatever DNS/IPv6 state we snapshotted.
    if [ -f "$SNAPSHOT_FILE" ]; then
        # shellcheck disable=SC1090
        source "$SNAPSHOT_FILE"
        if [ -n "${SERVICE:-}" ]; then
            if [ -n "${DNS_SERVERS:-}" ] && [ "$DNS_SERVERS" != " " ]; then
                # shellcheck disable=SC2086
                networksetup -setdnsservers "$SERVICE" $DNS_SERVERS 2>/dev/null || true
            else
                networksetup -setdnsservers "$SERVICE" "Empty" 2>/dev/null || true
            fi
            case "${V6_STATE:-}" in
                On) networksetup -setv6automatic "$SERVICE" 2>/dev/null || true ;;
                *) : ;;  # was already off, or unknown — leave off rather than guess
            esac
        fi
        rm -f "$SNAPSHOT_FILE"
    fi
}

case "$ACTION" in
    up) do_up ;;
    down) do_down ;;
    *) echo "leak-protection: unknown action '$ACTION'" >&2; exit 1 ;;
esac
