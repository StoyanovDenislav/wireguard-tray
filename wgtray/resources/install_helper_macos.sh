#!/bin/bash
# One-time, run as root (via the app's single admin prompt).
# Usage: install_helper_macos.sh <user> <bash> <wg-quick> <wg> <wireguard-go> <res-dir>
# Copies the tools into a root-owned dir: Homebrew's bin dirs are
# admin-writable, so pointing sudoers at them would be a root hole.
set -eu
user="$1"; src_bash="$2"; wgq="$3"; wg="$4"; wgo="$5"; res="$6"
[[ "$user" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "bad user" >&2; exit 1; }
LIB=/Library/PrivilegedHelperTools/wg-tray
rm -rf "$LIB"; mkdir -p "$LIB/bin"
install -m 755 "$src_bash" "$LIB/bin/bash"
install -m 755 "$wgq" "$LIB/bin/wg-quick"
install -m 755 "$wg" "$LIB/bin/wg"
install -m 755 "$wgo" "$LIB/bin/wireguard-go"
install -m 755 "$res/leak_protection_macos.sh" "$LIB/leak_protection_macos.sh"
install -m 755 "$res/priv_macos.sh" "$LIB/wgtray-priv"
chown -R root:wheel "$LIB"
tmp=$(mktemp)
echo "$user ALL=(root) NOPASSWD: $LIB/wgtray-priv up *, $LIB/wgtray-priv down *" > "$tmp"
visudo -cf "$tmp"
install -m 440 -o root -g wheel "$tmp" /etc/sudoers.d/wg-tray
rm -f "$tmp"
