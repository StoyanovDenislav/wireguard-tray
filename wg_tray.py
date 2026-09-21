#!/usr/bin/env python3
"""
wg-tray — a tiny, open-source, no-telemetry WireGuard tray client.

Lives in your system tray like Mullvad/OpenVPN's app, but is just a thin
GUI wrapper around the real `wg-quick` binary you already trust. No
accounts, no phone-home, no bundled analytics — it shells out to wg-quick
and nothing else.

Works on:
  - Linux (tested target: Artix + KDE, but any DE with a tray works)
  - macOS (uses the wireguard-tools you installed via Homebrew)
  - Windows (uses the official WireGuard for Windows install)

Import a config either as a .conf file, or by pointing it at a PNG/JPG
screenshot of a QR code (e.g. one shown by your wg-panel) — it'll decode
the WireGuard config straight out of the image, no phone needed.
"""

import sys
import os
import platform
import shutil
import subprocess
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QFileDialog,
    QInputDialog, QLineEdit
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import Qt, QTimer

try:
    from pyzbar.pyzbar import decode as qr_decode
    from PIL import Image
    HAVE_QR = True
except ImportError:
    HAVE_QR = False

APP_DIR = Path.home() / ".config" / "wg-tray"
CONFIGS_DIR = APP_DIR / "configs"
STATE_FILE = APP_DIR / "state.json"

IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------
# Privilege-escalated command execution
# ---------------------------------------------------------------------

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
    import time
    time.sleep(2)

    output = out_path.read_text(errors="replace").strip() if out_path.exists() else ""
    return True, output


def _win_quote(s):
    if not s or any(c in s for c in ' \t"'):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------
# Config + state management
# ---------------------------------------------------------------------

def ensure_dirs():
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"active": None}))


def load_state():
    ensure_dirs()
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {"active": None}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def list_configs():
    ensure_dirs()
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.conf"))


def config_path(name):
    return CONFIGS_DIR / f"{name}.conf"


# ---------------------------------------------------------------------
# WireGuard control
# ---------------------------------------------------------------------

def connect(name):
    if IS_WINDOWS:
        wireguard = find_wireguard_exe()
        if not wireguard:
            return False, "wireguard.exe not found. Install WireGuard for Windows first."
        conf = str(config_path(name))
        argv = [wireguard, "/installtunnelservice", conf]
    else:
        wg_quick = find_wg_quick()
        if not wg_quick:
            return False, "wg-quick not found. Install wireguard-tools first."
        conf = str(config_path(name))
        if IS_MAC:
            bash = find_bash()
            argv = [bash, wg_quick, "up", conf]
        else:
            argv = [wg_quick, "up", conf]

    ok, out = run_privileged(argv)
    if ok:
        state = load_state()
        state["active"] = name
        save_state(state)
    return ok, out


def disconnect(name):
    if IS_WINDOWS:
        wireguard = find_wireguard_exe()
        if not wireguard:
            return False, "wireguard.exe not found."
        # WireGuard for Windows names the service after the tunnel (config
        # stem), not the config path — unlike /installtunnelservice.
        argv = [wireguard, "/uninstalltunnelservice", name]
    else:
        wg_quick = find_wg_quick()
        if not wg_quick:
            return False, "wg-quick not found."
        conf = str(config_path(name))
        if IS_MAC:
            bash = find_bash()
            argv = [bash, wg_quick, "down", conf]
        else:
            argv = [wg_quick, "down", conf]

    ok, out = run_privileged(argv)
    if ok:
        state = load_state()
        if state.get("active") == name:
            state["active"] = None
        save_state(state)
    return ok, out


# ---------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------

def import_conf_file(src_path, name):
    dest = config_path(name)
    if dest.exists():
        raise FileExistsError(f"A tunnel named '{name}' already exists.")
    dest.write_text(Path(src_path).read_text())
    os.chmod(dest, 0o600)


def import_from_qr_image(image_path, name):
    if not HAVE_QR:
        raise RuntimeError(
            "QR decoding needs pyzbar + Pillow. Install with:\n"
            "  pip install pyzbar pillow\n"
            "and the zbar system library (brew install zbar / pacman -S zbar)."
        )
    img = Image.open(image_path)
    results = qr_decode(img)
    if not results:
        raise ValueError("No QR code found in that image.")
    payload = results[0].data.decode("utf-8")
    if "[Interface]" not in payload:
        raise ValueError("QR code didn't contain a WireGuard config.")
    dest = config_path(name)
    if dest.exists():
        raise FileExistsError(f"A tunnel named '{name}' already exists.")
    dest.write_text(payload)
    os.chmod(dest, 0o600)


# ---------------------------------------------------------------------
# Icon (drawn in code so there's no external asset to bundle/trust)
# ---------------------------------------------------------------------

def make_icon(connected):
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor("#3ddc84") if connected else QColor("#888888")
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(8, 8, 48, 48)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, "W")
    painter.end()
    return QIcon(pix)


# ---------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------

class WgTray:
    def __init__(self, app):
        self.app = app
        ensure_dirs()
        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.rebuild_menu()
        self.tray.show()

        # Poll connection state periodically in case it changes outside
        # this app (e.g. you ran wg-quick manually in a terminal).
        self.timer = QTimer()
        self.timer.timeout.connect(self.rebuild_menu)
        self.timer.start(5000)

    def current_active(self):
        return load_state().get("active")

    def rebuild_menu(self):
        self.menu.clear()
        active = self.current_active()
        self.tray.setIcon(make_icon(bool(active)))

        status_action = QAction(
            f"● Connected: {active}" if active else "○ Disconnected", self.menu
        )
        status_action.setEnabled(False)
        self.menu.addAction(status_action)
        self.menu.addSeparator()

        configs = list_configs()
        if not configs:
            empty = QAction("No tunnels imported yet", self.menu)
            empty.setEnabled(False)
            self.menu.addAction(empty)
        else:
            for name in configs:
                label = f"{'✓ ' if name == active else '   '}{name}"
                action = QAction(label, self.menu)
                action.triggered.connect(lambda checked=False, n=name: self.toggle(n))
                self.menu.addAction(action)

        self.menu.addSeparator()

        import_file_action = QAction("Import .conf file…", self.menu)
        import_file_action.triggered.connect(self.do_import_file)
        self.menu.addAction(import_file_action)

        import_qr_action = QAction("Import from QR image…", self.menu)
        import_qr_action.triggered.connect(self.do_import_qr)
        self.menu.addAction(import_qr_action)

        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)

    def toggle(self, name):
        active = self.current_active()
        if active == name:
            ok, out = disconnect(name)
            if not ok:
                self.error(f"Failed to disconnect:\n{out}")
        else:
            if active:
                ok, out = disconnect(active)
                if not ok:
                    self.error(f"Failed to disconnect '{active}' first:\n{out}")
                    return
            ok, out = connect(name)
            if not ok:
                self.error(f"Failed to connect:\n{out}")
        self.rebuild_menu()

    def do_import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select WireGuard .conf file", str(Path.home()), "Config files (*.conf)"
        )
        if not path:
            return
        default_name = Path(path).stem
        name, ok = QInputDialog.getText(
            None, "Tunnel name", "Name this tunnel:", QLineEdit.Normal, default_name
        )
        if not ok or not name.strip():
            return
        try:
            import_conf_file(path, name.strip())
            self.rebuild_menu()
        except Exception as e:
            self.error(str(e))

    def do_import_qr(self):
        if not HAVE_QR:
            self.error(
                "QR decoding isn't installed.\n\n"
                "Run: pip install pyzbar pillow\n"
                "And install the zbar library:\n"
                "  macOS: brew install zbar\n"
                "  Linux: sudo pacman -S zbar   (or apt install libzbar0)\n"
                "  Windows: pip install pyzbar pillow (bundles zbar's DLL)"
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            None, "Select QR code image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return
        name, ok = QInputDialog.getText(
            None, "Tunnel name", "Name this tunnel:", QLineEdit.Normal, "tunnel"
        )
        if not ok or not name.strip():
            return
        try:
            import_from_qr_image(path, name.strip())
            self.rebuild_menu()
        except Exception as e:
            self.error(str(e))

    def error(self, msg):
        QMessageBox.warning(None, "wg-tray", msg)


def main():
    if IS_WINDOWS:
        if not find_wireguard_exe():
            print("Warning: wireguard.exe not found. Install WireGuard for Windows first.")
    elif not find_wg_quick():
        print("Warning: wg-quick not found on PATH. Install wireguard-tools first.")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "wg-tray", "No system tray detected on this desktop.")
        sys.exit(1)

    tray = WgTray(app)  # noqa: F841 — keep reference alive
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
