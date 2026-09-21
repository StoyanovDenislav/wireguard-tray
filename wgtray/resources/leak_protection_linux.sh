#!/bin/bash
# wg-tray leak-protection hook for Linux, invoked from a tunnel's
# PostUp/PreDown lines (see wgtray/leak_protection.py, which writes the
# derived .conf that calls this). Root-only — wg-quick already runs
# PostUp/PreDown as root, same as `wg-quick up/down` itself.
#
# Usage: leak_protection_linux.sh up   <endpoint-port>
#        leak_protection_linux.sh down <endpoint-port>
#
# Deliberately init-system-agnostic (systemd, runit, OpenRC, s6, dinit,
# ...): everything here is either a kernel knob (sysctl) or a firewall
# rule (nftables), neither of which depends on which init/service
# manager the distro uses. In particular, this never touches DNS
# resolver configuration (no resolvectl/nmcli/resolv.conf editing) —
# see the module docstring in leak_protection.py for why: blocking DNS
# at the firewall is more robust than pinning a resolver, and it sidesteps
# needing to detect systemd-resolved vs NetworkManager vs a plain
# resolv.conf across every possible distro/init combination.
#
# What "up" does:
#   1. Snapshot every physical interface's current IPv6 sysctl setting,
#      so "down" (or a later "up", if wg-tray crashed last time — see
#      below) can restore it exactly.
#   2. Disable IPv6 on every physical interface via sysctl (most
#      WireGuard configs only route 0.0.0.0/0, so IPv6 would otherwise
#      bypass the tunnel entirely).
#   3. Load an nftables table that: allows DHCP, allows the WireGuard
#      endpoint's own port outbound (so the tunnel can (re)establish),
#      blocks outbound DNS (53/tcp+udp) on every physical interface, and
#      accepts everything on wg*/tun* — everything else on the physical
#      interfaces is dropped. This is the actual kill switch: if the
#      tunnel drops, the physical interfaces stay locked down instead of
#      leaking.
#
# What "down" does: removes the nftables table and restores the
# snapshotted IPv6 sysctl settings — in that order, so connectivity
# comes back before leak protection is guaranteed lifted.
#
# Crash recovery: if wg-tray or the tunnel is force-quit/killed while
# connected, PreDown never runs, so the nftables table and IPv6-disabled
# sysctl would otherwise stick around forever. Every "up" call checks
# for a snapshot left over from a run that never called "down", and if
# our nftables table isn't currently loaded (a good signal nothing is
# actively using it), restores IPv6 from that stale snapshot before
# taking a fresh one.
set -euo pipefail

ACTION="${1:?up or down required}"
ENDPOINT_PORT="${2:-51820}"

STATE_DIR="$HOME/.config/wg-tray"
SNAPSHOT_FILE="$STATE_DIR/.leak_protection_snapshot"
TABLE_NAME="wgtray_leakguard"

mkdir -p "$STATE_DIR"

physical_devices() {
    # Every interface under /sys/class/net except loopback, WireGuard's
    # own interfaces, other tunnel devices, and common virtual/container
    # interfaces that don't carry real outbound traffic. This is a kernel
    # directory listing, not a service call, so it works identically
    # regardless of init system or which DNS/network manager (if any) is
    # running.
    local dev
    for dev in /sys/class/net/*; do
        dev="$(basename "$dev")"
        case "$dev" in
            lo|wg*|tun*|tap*|docker*|veth*|br-*|virbr*|podman*) continue ;;
        esac
        echo "$dev"
    done
}

table_loaded() {
    nft list table inet "$TABLE_NAME" >/dev/null 2>&1
}

snapshot_ipv6() {
    : > "$SNAPSHOT_FILE"
    local dev sysctl_path state
    while IFS= read -r dev; do
        [ -z "$dev" ] && continue
        sysctl_path="/proc/sys/net/ipv6/conf/$dev/disable_ipv6"
        # Some interfaces (mostly virtual ones we've already excluded,
        # but be defensive) may not have an ipv6 conf entry at all.
        if [ -r "$sysctl_path" ]; then
            state="$(cat "$sysctl_path" 2>/dev/null || echo "")"
        else
            state=""
        fi
        printf '%s\t%s\n' "$dev" "$state" >> "$SNAPSHOT_FILE"
    done < <(physical_devices)
}

restore_ipv6_from_snapshot() {
    [ -f "$SNAPSHOT_FILE" ] || return 0
    local dev state sysctl_path
    while IFS=$'\t' read -r dev state; do
        [ -z "$dev" ] && continue
        [ -z "$state" ] && continue
        sysctl_path="/proc/sys/net/ipv6/conf/$dev/disable_ipv6"
        [ -w "$sysctl_path" ] && echo "$state" > "$sysctl_path" 2>/dev/null || true
    done < "$SNAPSHOT_FILE"
    rm -f "$SNAPSHOT_FILE"
}

do_up() {
    # Crash recovery: see module docstring.
    if [ -f "$SNAPSHOT_FILE" ] && ! table_loaded; then
        restore_ipv6_from_snapshot
    fi

    snapshot_ipv6

    local devices
    devices="$(physical_devices)"
    if [ -z "$devices" ]; then
        echo "leak-protection: no physical interfaces found, skipping" >&2
        return 0
    fi

    # --- IPv6 off on every physical interface ---
    local dev sysctl_path
    while IFS= read -r dev; do
        [ -z "$dev" ] && continue
        sysctl_path="/proc/sys/net/ipv6/conf/$dev/disable_ipv6"
        [ -w "$sysctl_path" ] && echo 1 > "$sysctl_path" 2>/dev/null || true
    done < <(physical_devices)

    # --- nftables kill switch. Built as one atomic `nft -f` load so
    # there's never a window with a half-applied ruleset. ---
    local nft_conf
    nft_conf="$(mktemp)"
    chmod 600 "$nft_conf"
    {
        echo "table inet $TABLE_NAME {"
        echo "    chain output {"
        echo "        type filter hook output priority 0; policy accept;"
        while IFS= read -r dev; do
            [ -z "$dev" ] && continue
            # DHCP (needed to keep/renew a lease on the physical link).
            echo "        oifname \"$dev\" udp dport { 67, 68 } accept"
            # The WireGuard endpoint's own handshake/keepalive port.
            echo "        oifname \"$dev\" udp dport $ENDPOINT_PORT accept"
            # DNS block — belt-and-suspenders; everything else below
            # already blocks all other traffic on this interface too.
            echo "        oifname \"$dev\" tcp dport 53 drop"
            echo "        oifname \"$dev\" udp dport 53 drop"
            # Drop everything else outbound on this physical interface.
            echo "        oifname \"$dev\" drop"
        done < <(physical_devices)
        echo "    }"
        echo "}"
    } > "$nft_conf"

    nft -f "$nft_conf"
    rm -f "$nft_conf"
}

do_down() {
    # Remove the kill switch first so connectivity is available again...
    nft delete table inet "$TABLE_NAME" 2>/dev/null || true

    # ...then restore whatever IPv6 state we snapshotted.
    restore_ipv6_from_snapshot
}

case "$ACTION" in
    up) do_up ;;
    down) do_down ;;
    *) echo "leak-protection: unknown action '$ACTION'" >&2; exit 1 ;;
esac
