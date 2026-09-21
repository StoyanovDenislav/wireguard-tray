#!/bin/bash
# wg-tray leak-protection hook for macOS, invoked from a tunnel's
# PostUp/PreDown lines (see wgtray/leak_protection.py, which writes the
# derived .conf that calls this). Root-only — wg-quick already runs
# PostUp/PreDown as root, same as the `wg-quick up/down` invocation itself.
#
# Usage: leak_protection_macos.sh up   <endpoint-port>
#        leak_protection_macos.sh down <endpoint-port>
#
# What "up" does:
#   1. Snapshot every physical interface's current IPv6 setting to a
#      state file, so "down" (or a later "up", if wg-tray crashed last
#      time — see below) can restore it exactly.
#   2. Turn off IPv6 on every physical interface (most WireGuard configs
#      only route 0.0.0.0/0, so IPv6 would otherwise bypass the tunnel).
#   3. Load a pf anchor that: allows DHCP, allows the WireGuard endpoint's
#      own port outbound (so the tunnel can (re)establish), blocks
#      outbound DNS (53/tcp+udp) on every physical interface, and passes
#      everything on utun* — everything else on the physical interfaces
#      is blocked. This is the actual kill switch: if the tunnel drops,
#      the physical interfaces stay locked down instead of leaking.
#
# What "down" does: unloads the pf anchor and restores the snapshotted
# IPv6 settings — in that order, so connectivity comes back before leak
# protection is guaranteed lifted (favors "don't leak" over "don't
# briefly interrupt connectivity" during the flip).
#
# Crash recovery: if wg-tray or the tunnel is force-quit/killed while
# connected, PreDown never runs, so the pf anchor and IPv6-off setting
# would otherwise stick around forever. Every "up" call checks for a
# snapshot left over from a run that never called "down", and if the pf
# anchor isn't currently loaded (a good signal nothing is actively using
# it), restores IPv6 from that stale snapshot before taking a fresh one.
set -euo pipefail

ACTION="${1:?up or down required}"
ENDPOINT_PORT="${2:-51820}"

STATE_DIR="$HOME/.config/wg-tray"
SNAPSHOT_FILE="$STATE_DIR/.leak_protection_snapshot"
ANCHOR_NAME="wg-tray-leakguard"
PF_CONF="/tmp/wg-tray-leakguard.pf.conf"

mkdir -p "$STATE_DIR"

physical_services() {
    # All networksetup "service names" (e.g. "Wi-Fi", "USB 10/100/1000 LAN")
    # for hardware ports that currently have a device — covers Wi-Fi,
    # built-in Ethernet, Thunderbolt bridges, USB dongles, etc. Excludes
    # loopback and WireGuard's own utun* interfaces, which aren't listed
    # as hardware ports anyway.
    networksetup -listallhardwareports | awk '
        /^Hardware Port:/ { port = substr($0, index($0, ":") + 2) }
        /^Device:/ { dev = substr($0, index($0, ":") + 2); if (port != "" && dev != "") print port; port = "" }
    '
}

physical_devices() {
    # Raw device names (en0, en1, ...) for the pf anchor, one per line.
    networksetup -listallhardwareports | awk '/^Device: en[0-9]+$/ { print substr($0, index($0, ":") + 2) }'
}

anchor_loaded() {
    pfctl -a "$ANCHOR_NAME" -s rules 2>/dev/null | grep -q .
}

snapshot_ipv6() {
    : > "$SNAPSHOT_FILE"
    while IFS= read -r service; do
        [ -z "$service" ] && continue
        local v6_state
        # Some hardware ports networksetup lists (e.g. an unconfigured
        # Thunderbolt port) aren't recognized as real network services —
        # `networksetup -getinfo` exits non-zero for those. Under
        # set -o pipefail that failure propagates through the pipeline
        # even though awk succeeds, and set -e would then abort the
        # whole script over one irrelevant port. `|| true` makes this
        # line best-effort, matching every other networksetup call here.
        v6_state="$(networksetup -getinfo "$service" 2>/dev/null | awk -F': ' '/^IPv6: /{print $2; exit}')" || true
        printf '%s\t%s\n' "$service" "$v6_state" >> "$SNAPSHOT_FILE"
    done < <(physical_services)
}

restore_ipv6_from_snapshot() {
    [ -f "$SNAPSHOT_FILE" ] || return 0
    while IFS=$'\t' read -r service v6_state; do
        [ -z "$service" ] && continue
        case "$v6_state" in
            On) networksetup -setv6automatic "$service" 2>/dev/null || true ;;
            *) : ;;  # was already off, or unknown — leave off rather than guess
        esac
    done < "$SNAPSHOT_FILE"
    rm -f "$SNAPSHOT_FILE"
}

do_up() {
    # Crash recovery: a snapshot left over from a session that never
    # called "down", with no anchor currently loaded, means the last run
    # was killed mid-connection. Restore IPv6 from it before proceeding
    # so we don't leave the *previous* session's snapshot stranded, and
    # so this fresh snapshot reflects the real pre-VPN state, not the
    # leftover "IPv6 off" from last time.
    if [ -f "$SNAPSHOT_FILE" ] && ! anchor_loaded; then
        restore_ipv6_from_snapshot
    fi

    snapshot_ipv6

    local devices dev_list=""
    devices="$(physical_devices)"
    if [ -z "$devices" ]; then
        echo "leak-protection: no physical interfaces found, skipping" >&2
        return 0
    fi

    # --- IPv6 off on every physical interface ---
    while IFS= read -r service; do
        [ -z "$service" ] && continue
        networksetup -setv6off "$service" 2>/dev/null || true
    done < <(physical_services)

    # --- pf kill switch, covering every physical interface at once via
    # an interface-list macro, so a Thunderbolt bridge or USB dongle
    # (en1, en2, ...) is covered exactly like en0. ---
    dev_list="{ $(echo "$devices" | tr '\n' ' ' | sed 's/ *$//' | tr ' ' ',') }"

    cat > "$PF_CONF" <<EOF
# wg-tray leak-guard anchor — regenerated on every connect, safe to
# overwrite. Blocks all physical interfaces except DHCP + the WireGuard
# endpoint's own port (needed for the handshake), blocks outbound DNS
# on them explicitly (belt-and-suspenders — the tunnel-up window before
# a rogue process's DNS query would otherwise slip through), and passes
# everything on utun*.
ext_if = "$dev_list"
block drop on \$ext_if all
pass out on \$ext_if proto udp from any to any port 67:68 keep state
pass out quick on \$ext_if proto udp from any to any port $ENDPOINT_PORT keep state
block out quick on \$ext_if proto { tcp, udp } from any to any port 53
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

    # Intentionally not silenced/guarded: if the kill switch's pf anchor
    # fails to load, that's the one failure that should actually abort
    # (via set -e) and be visible in wg-quick's PostUp output — silently
    # continuing would mean the "kill switch" checkbox did nothing.
    pfctl -a "$ANCHOR_NAME" -f "$PF_CONF"
    pfctl -e 2>/dev/null || true  # already-enabled is a harmless failure
}

do_down() {
    # Unload the kill switch first so connectivity is available again...
    pfctl -a "$ANCHOR_NAME" -F all 2>/dev/null || true
    rm -f "$PF_CONF"

    # ...then restore whatever IPv6 state we snapshotted.
    restore_ipv6_from_snapshot
}

case "$ACTION" in
    up) do_up ;;
    down) do_down ;;
    *) echo "leak-protection: unknown action '$ACTION'" >&2; exit 1 ;;
esac
