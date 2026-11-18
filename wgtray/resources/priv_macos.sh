#!/bin/bash
# Root-owned helper, run via sudo NOPASSWD (see install_helper_macos.sh).
# Usage: wgtray-priv up|down <conf> [leak-port]
# <conf> comes from an unprivileged user, so treat it as hostile: only a
# regular file the user owns under their wg-tray dirs, hook lines stripped
# (wg-quick runs PostUp etc. as root), root-owned hooks added instead.
set -u
LIB=/Library/PrivilegedHelperTools/wg-tray
RD=/var/run/wg-tray
export PATH="$LIB/bin" WGTRAY_STATE_DIR=/var/db/wg-tray
umask 077

op="${1:-}"; conf="${2:-}"; port="${3:-}"
user="${SUDO_USER:-}"
[ -n "$user" ] && [ "$user" != root ] || { echo "must run via sudo" >&2; exit 1; }
[ "$op" = up ] || [ "$op" = down ] || { echo "bad op" >&2; exit 1; }
[ -z "$port" ] || [[ "$port" =~ ^[0-9]{1,5}$ ]] || { echo "bad port" >&2; exit 1; }

home=$(dscl . -read "/Users/$user" NFSHomeDirectory | awk '{print $2}')
case "$conf" in *..*) echo "bad path" >&2; exit 1;; esac
case "$conf" in
  "$home/.config/wg-tray/configs/"*.conf|"$home/.config/wg-tray/runtime/"*.conf) ;;
  *) echo "bad path" >&2; exit 1;;
esac
[ -f "$conf" ] && [ ! -L "$conf" ] && [ "$(stat -f %u "$conf")" = "$(id -u "$user")" ] \
  || { echo "bad config file" >&2; exit 1; }
iface=$(basename "$conf" .conf)
[[ "$iface" =~ ^[a-zA-Z0-9_=+.-]{1,15}$ ]] || { echo "bad name" >&2; exit 1; }

mkdir -p "$RD" /var/db/wg-tray
safe="$RD/$iface.conf"
trap 'rm -f "$safe"' EXIT
awk -v port="$port" -v lib="$LIB" '
  tolower($0) ~ /^[ \t]*(preup|postup|predown|postdown|saveconfig)[ \t]*=/ { next }
  { print }
  port != "" && tolower($0) ~ /^[ \t]*\[interface\][ \t]*$/ {
    print "PostUp = " lib "/leak_protection_macos.sh up " port
    print "PreDown = " lib "/leak_protection_macos.sh down " port
  }' "$conf" > "$safe"

bash="$LIB/bin/bash"
if [ "$op" = up ]; then
  "$bash" "$LIB/bin/wg-quick" up "$safe"; exit $?
fi
"$bash" "$LIB/bin/wg-quick" down "$safe"; rc=$?
if [ $rc -ne 0 ] && [ ! -e "/var/run/wireguard/$iface.name" ]; then
  # tunnel already gone: wg-quick skipped PreDown, so lift the kill switch ourselves
  [ -z "$port" ] || "$LIB/leak_protection_macos.sh" down "$port"
  exit 0
fi
exit $rc
