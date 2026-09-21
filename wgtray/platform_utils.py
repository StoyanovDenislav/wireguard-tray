"""Platform detection and privilege-escalated command execution.

wg-tray never asks for or stores a password itself — every elevated
command hands off to the OS's own native prompt (pkexec, osascript,
UAC), so this module is the only place that runs anything as admin.
"""
import os
import platform
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
