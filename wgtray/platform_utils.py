"""Platform detection and privilege-escalated command execution.

wg-tray never asks for or stores a password itself — every elevated
command hands off to the OS's own native prompt (pkexec, osascript,
UAC), so this module is the only place that runs anything as admin.
"""
import os
import platform
import re
import shutil
import subprocess

from .paths import APP_DIR

IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"


def find_wg_quick():
    for candidate in ("wg-quick", "/opt/homebrew/bin/wg-quick", "/usr/local/bin/wg-quick",
                       "/usr/bin/wg-quick"):
        found = shutil.which(candidate) if "/" not in candidate else (candidate if os.path.exists(candidate) else None)
        if found:
            return found
    return None


def find_wireguard_exe():
    # The official WireGuard for Windows installer puts wireguard.exe here,
    # and it's what the tunnel-service subcommands live on (there's no
    # wg-quick on Windows — WireGuard runs tunnels as services instead).
    for candidate in (
        shutil.which("wireguard.exe") or shutil.which("wireguard"),
        r"C:\Program Files\WireGuard\wireguard.exe",
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def find_bash():
    # macOS needs Homebrew's bash (4+) — the system one is 3.2 and wg-quick
    # refuses to run under it.
    for candidate in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", "/bin/bash"):
        if os.path.exists(candidate):
            return candidate
    return "/bin/bash"


# Known VPN clients that run a background daemon capable of holding the
# default route even after their GUI window is closed — quitting the app
# window alone doesn't stop these. Used to give the user an actionable
# name ("Mullvad VPN is still connected") instead of a generic warning.
_KNOWN_VPN_DAEMONS = {
    "mullvad-daemon": "Mullvad VPN",
    "tailscaled": "Tailscale",
    "nordvpnd": "NordVPN",
    "ovpnagent": "OpenVPN Connect",
    "expressvpnd": "ExpressVPN",
    "protonvpn-app": "Proton VPN",
}


def find_running_vpn_daemons():
    """
    Returns a list of (process_name, friendly_name) for any known VPN
    daemon currently running, regardless of whether it's actually holding
    a route right now — used to name a likely culprit in the conflict
    warning, and to know what a "disconnect it for me" action would need
    to stop. Best-effort: an unrecognized VPN client won't show up here
    even if it's the one actually causing find_conflicting_vpn_interface()
    to trip.
    """
    if IS_WINDOWS:
        return []
    try:
        result = subprocess.run(["ps", "-Ao", "comm="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []

    found = []
    for line in result.stdout.splitlines():
        proc_name = line.strip().rsplit("/", 1)[-1]
        if proc_name in _KNOWN_VPN_DAEMONS:
            found.append((proc_name, _KNOWN_VPN_DAEMONS[proc_name]))
    return found


# Known VPN clients with a safe, official CLI disconnect command we can
# offer to run on the user's behalf. Anything not listed here just gets
# named in the warning — we don't guess at unfamiliar VPN CLIs.
_SAFE_DISCONNECT_COMMANDS = {
    "mullvad-daemon": ["mullvad", "disconnect", "--wait"],
    "tailscaled": ["tailscale", "down"],
}


def disconnect_other_vpn(daemon_process_name):
    """
    Run the known-safe official disconnect command for a detected VPN
    daemon (see _SAFE_DISCONNECT_COMMANDS). Returns (ok, output). Only
    ever called after the user explicitly clicks a "Disconnect X" button
    naming exactly what will run — never automatic.
    """
    argv = _SAFE_DISCONNECT_COMMANDS.get(daemon_process_name)
    if not argv or not shutil.which(argv[0]):
        return False, f"No known safe way to disconnect this automatically."
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def find_conflicting_vpn_interface():
    """
    wg-quick (macOS/Linux) picks the *first* "default" line out of the
    routing table as the gateway to route the WireGuard endpoint itself
    through (see its collect_gateways()). If another VPN/tunnel is
    already up and its utun*/tun*/ppp* interface appears there before
    the real physical gateway, wg-quick tries to use that interface name
    as if it were a gateway IP address and fails with "bad address: X" —
    a wg-quick limitation, not something we can fix, but worth detecting
    up front so the user gets a clear message instead of a raw script
    dump. Returns the offending interface name, or None if the first
    default route looks like a normal IP gateway.
    """
    if not (IS_MAC or IS_LINUX):
        return None
    try:
        if IS_MAC:
            result = subprocess.run(
                ["netstat", "-nr", "-f", "inet"], capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["ip", "route", "show", "default"], capture_output=True, text=True, timeout=5
            )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if IS_MAC:
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "default":
                gateway = parts[1]
                # A real gateway is an IP; a tunnel interface name isn't.
                if not re.match(r"^[0-9a-fA-F:.]+$", gateway):
                    return gateway
                return None
    else:
        # `ip route show default` lines look like:
        # "default via 192.168.1.1 dev en0 ..." or, with no real gateway,
        # "default dev utun3 scope link ..."
        for line in result.stdout.splitlines():
            m = re.search(r"\bdev\s+(\S+)", line)
            if m and "via" not in line:
                dev = m.group(1)
                if re.match(r"^(utun|tun|wg|tailscale|ppp)\d*$", dev):
                    return dev
    return None


def run_privileged(argv):
    """
    Run argv (a list) with elevated privileges, returning (ok, output).
    Linux: pkexec (graphical sudo prompt via polkit).
    macOS: osascript admin-privileges prompt (native GUI password dialog).
    Windows: re-launch this same script's helper via ShellExecute "runas"
             (native UAC prompt), since Windows has no argv-based sudo.
    """
    if IS_LINUX:
        pkexec = shutil.which("pkexec")
        if not pkexec:
            return False, "pkexec not found — install polkit for graphical privilege prompts."
        cmd = [pkexec] + argv
        result = subprocess.run(cmd, capture_output=True, text=True)
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr).strip()

    if IS_MAC:
        # osascript needs one shell-escaped string, not argv
        quoted = " ".join(_shell_quote(a) for a in argv)
        script = f'do shell script "{quoted}" with administrator privileges'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr).strip()

    if IS_WINDOWS:
        return _run_privileged_windows(argv)

    return False, "Unsupported platform."


def _run_privileged_windows(argv):
    import ctypes
    import time

    exe, *args = argv
    # UAC's ShellExecute "runas" doesn't give us stdout/stderr back directly,
    # so redirect the elevated process's output to a temp file we can read.
    out_path = APP_DIR / "_last_privileged_output.txt"
    APP_DIR.mkdir(parents=True, exist_ok=True)
    quoted_args = " ".join(_win_quote(a) for a in args)
    # cmd /c so we can redirect; keep the window hidden.
    wrapped_args = f'/c ""{exe}" {quoted_args}" > "{out_path}" 2>&1'

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "cmd.exe", wrapped_args, None, 0  # SW_HIDE
    )
    # ShellExecuteW returns a value > 32 on success.
    if result <= 32:
        if result == 5:
            return False, "Elevation was denied."
        return False, f"Failed to launch elevated process (error {result})."

    # ShellExecuteW doesn't hand us a process handle to wait on here, so
    # give the (typically instant) service install/uninstall a moment.
    time.sleep(2)

    output = out_path.read_text(errors="replace").strip() if out_path.exists() else ""
    return True, output


def _win_quote(s):
    if not s or any(c in s for c in ' \t"'):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"
