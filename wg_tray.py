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
import urllib.request
import urllib.error
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QFileDialog,
    QInputDialog, QLineEdit, QMainWindow, QWidget, QListWidget,
    QListWidgetItem, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QFrame, QSizePolicy, QDialog, QCheckBox, QTextBrowser, QDialogButtonBox
)
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont, QCloseEvent, QDesktopServices
from PySide6.QtCore import Qt, QTimer, QSize, QUrl

try:
    from pyzbar.pyzbar import decode as qr_decode
    from PIL import Image
    HAVE_QR = True
except ImportError:
    HAVE_QR = False

APP_VERSION = "0.2.1"
GITHUB_REPO = "StoyanovDenislav/wireguard-tray"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

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

DEFAULT_STATE = {
    "active": None,
    "seen_version": None,
    "auto_update_check": False,
}


def ensure_dirs():
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(DEFAULT_STATE))


def load_state():
    ensure_dirs()
    try:
        state = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        state = {}
    # Backfill any keys older state files on disk don't have yet.
    for key, default in DEFAULT_STATE.items():
        state.setdefault(key, default)
    return state


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def list_configs():
    ensure_dirs()
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.conf"))


def config_path(name):
    return CONFIGS_DIR / f"{name}.conf"


# ---------------------------------------------------------------------
# Update checking
#
# Privacy note: this never runs unless the user clicks "Check for
# updates" or has explicitly opted in to automatic checks (off by
# default). It's a single unauthenticated GET to GitHub's public
# releases API — same as opening the Releases page in a browser. No
# hardware IDs, no analytics, no custom telemetry server.
# ---------------------------------------------------------------------

def _parse_version(v):
    v = v.lstrip("v")
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_version(candidate, current):
    return _parse_version(candidate) > _parse_version(current)


def fetch_latest_release():
    """
    Hit GitHub's public releases API. Returns a dict with 'version',
    'notes' (the release body — our CI auto-fills this from commits via
    generate_release_notes), and 'url', or None on any failure (offline,
    rate-limited, etc. all fail silently — this is a nice-to-have, never
    something that should interrupt the user).
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "wg-tray"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "version": data.get("tag_name", "").lstrip("v"),
            "notes": data.get("body", "").strip(),
            "url": data.get("html_url", RELEASES_PAGE_URL),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


def fetch_release_notes_for(version):
    """Look up the changelog body for a specific tag (e.g. after an
    update), falling back to None if it can't be fetched."""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/v{version}"
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json", "User-Agent": "wg-tray"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("body", "").strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


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
# Theme (dark, Mullvad-style)
# ---------------------------------------------------------------------

ACCENT = "#3ddc84"
ACCENT_DIM = "#2a9d5e"
BG = "#1b1f24"
BG_ALT = "#232830"
BG_RAISED = "#2b313b"
FG = "#e8ecef"
FG_MUTED = "#8a929c"
BORDER = "#333a44"

APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {FG};
    font-size: 13px;
}}

QListWidget {{
    background-color: {BG_ALT};
    border: none;
    outline: none;
    padding: 6px;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-radius: 6px;
    margin: 2px 0;
    color: {FG};
}}

QListWidget::item:selected {{
    background-color: {BG_RAISED};
    color: {ACCENT};
}}

QListWidget::item:hover:!selected {{
    background-color: {BG_RAISED};
}}

QLabel {{
    color: {FG};
    background: transparent;
}}

QLabel#status-connected {{
    color: {ACCENT};
}}

QLabel#status-disconnected {{
    color: {FG_MUTED};
}}

QPushButton {{
    background-color: {BG_RAISED};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}

QPushButton:hover {{
    border-color: {ACCENT_DIM};
}}

QPushButton:pressed {{
    background-color: {BORDER};
}}

QPushButton:disabled {{
    color: {FG_MUTED};
    border-color: {BORDER};
}}

QPushButton#toggle-connect {{
    background-color: {ACCENT};
    color: #0c1210;
    border: none;
    font-weight: 600;
}}

QPushButton#toggle-connect:hover {{
    background-color: {ACCENT_DIM};
}}

QPushButton#toggle-disconnect {{
    background-color: transparent;
    color: {FG};
    border: 1px solid {BORDER};
    font-weight: 600;
}}

QPushButton#toggle-disconnect:hover {{
    border-color: #d9534f;
    color: #d9534f;
}}

QFrame[frameShape="5"] {{
    color: {BORDER};
    max-width: 1px;
}}

QMenu {{
    background-color: {BG_ALT};
    color: {FG};
    border: 1px solid {BORDER};
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {BG_RAISED};
    color: {ACCENT};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
"""


# ---------------------------------------------------------------------
# Icon (drawn in code so there's no external asset to bundle/trust)
# ---------------------------------------------------------------------

def make_icon(connected):
    """Abstract tunnel glyph: two nodes joined by a connecting curve."""
    from PySide6.QtGui import QPainterPath
    from PySide6.QtCore import QPointF

    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    color = QColor(ACCENT) if connected else QColor(FG_MUTED)
    node_color = QColor("#ffffff") if connected else QColor("#cfd4d9")

    node_r = 8
    a = QPointF(18, 46)   # bottom-left node center
    b = QPointF(46, 18)   # top-right node center

    pen = painter.pen()
    pen.setColor(color)
    pen.setWidth(6)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    path = QPainterPath(a)
    # Bow the connecting curve toward the top-left corner, away from the
    # a-b diagonal, so it reads as an arc rather than a straight line.
    path.quadTo(QPointF(14, 14), b)
    painter.drawPath(path)

    painter.setPen(Qt.NoPen)
    painter.setBrush(node_color)
    painter.drawEllipse(a, node_r, node_r)
    painter.drawEllipse(b, node_r, node_r)

    painter.end()
    return QIcon(pix)


def make_app_icon():
    # A static, always-"connected"-colored variant used for window/taskbar
    # icons, where a live connection state doesn't make sense as glyph color.
    return make_icon(True)


# ---------------------------------------------------------------------
# Main window (sidebar of tunnels + detail pane), Mullvad/OpenVPN-style
# ---------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("wg-tray")
        self.resize(680, 420)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Sidebar ---
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.currentItemChanged.connect(self.on_selection_changed)
        sidebar_layout.addWidget(self.list)

        sidebar_buttons = QHBoxLayout()
        sidebar_buttons.setContentsMargins(8, 8, 8, 8)
        import_file_btn = QPushButton("+ .conf")
        import_file_btn.clicked.connect(self.controller.do_import_file)
        import_qr_btn = QPushButton("+ QR")
        import_qr_btn.clicked.connect(self.controller.do_import_qr)
        sidebar_buttons.addWidget(import_file_btn)
        sidebar_buttons.addWidget(import_qr_btn)
        sidebar_layout.addLayout(sidebar_buttons)

        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(8, 0, 8, 8)
        settings_btn = QPushButton("Settings…")
        settings_btn.clicked.connect(self.controller.show_settings)
        settings_row.addWidget(settings_btn)
        sidebar_layout.addLayout(settings_row)

        root.addWidget(sidebar)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        root.addWidget(divider)

        # --- Detail pane ---
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(32, 32, 32, 32)
        detail_layout.setSpacing(12)
        detail_layout.addStretch(1)

        self.name_label = QLabel("No tunnel selected")
        name_font = QFont()
        name_font.setPointSize(20)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setAlignment(Qt.AlignCenter)
        detail_layout.addWidget(self.name_label)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        detail_layout.addWidget(self.status_label)

        detail_layout.addSpacing(16)

        self.toggle_btn = QPushButton("Connect")
        self.toggle_btn.setObjectName("toggle-connect")
        self.toggle_btn.setFixedHeight(48)
        self.toggle_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toggle_btn.setMinimumWidth(180)
        self.toggle_btn.clicked.connect(self.on_toggle_clicked)
        toggle_row = QHBoxLayout()
        toggle_row.addStretch(1)
        toggle_row.addWidget(self.toggle_btn)
        toggle_row.addStretch(1)
        detail_layout.addLayout(toggle_row)

        detail_layout.addStretch(2)

        root.addWidget(detail, 1)

        self.refresh()

    def closeEvent(self, event: QCloseEvent):
        # Minimize to tray instead of quitting — the tray icon stays live.
        event.ignore()
        self.hide()

    def selected_name(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self):
        active = self.controller.current_active()
        previously_selected = self.selected_name()

        self.list.blockSignals(True)
        self.list.clear()
        for name in list_configs():
            item = QListWidgetItem(f"●  {name}" if name == active else f"   {name}")
            item.setData(Qt.UserRole, name)
            self.list.addItem(item)
            if name == previously_selected or (previously_selected is None and name == active):
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

        self.update_detail()

    def on_selection_changed(self, *_):
        self.update_detail()

    def update_detail(self):
        name = self.selected_name()
        active = self.controller.current_active()

        if name is None:
            self.name_label.setText("No tunnels imported yet")
            self.status_label.setText("Use + .conf or + QR to add one")
            self.status_label.setObjectName("status-disconnected")
            self.toggle_btn.setEnabled(False)
            self.toggle_btn.setText("Connect")
            self.toggle_btn.setObjectName("toggle-connect")
            self._repolish(self.status_label, self.toggle_btn)
            return

        self.toggle_btn.setEnabled(True)
        self.name_label.setText(name)
        if name == active:
            self.status_label.setText("● Connected")
            self.status_label.setObjectName("status-connected")
            self.toggle_btn.setText("Disconnect")
            self.toggle_btn.setObjectName("toggle-disconnect")
        else:
            self.status_label.setText("○ Disconnected")
            self.status_label.setObjectName("status-disconnected")
            self.toggle_btn.setText("Connect")
            self.toggle_btn.setObjectName("toggle-connect")
        self._repolish(self.status_label, self.toggle_btn)

    def _repolish(self, *widgets):
        # Force QSS re-evaluation after changing objectName at runtime.
        for w in widgets:
            w.style().unpolish(w)
            w.style().polish(w)

    def on_toggle_clicked(self):
        name = self.selected_name()
        if name is None:
            return
        self.controller.toggle(name)


# ---------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        version_label = QLabel(f"wg-tray v{APP_VERSION}")
        version_font = QFont()
        version_font.setBold(True)
        version_label.setFont(version_font)
        layout.addWidget(version_label)

        state = load_state()

        self.auto_check_box = QCheckBox("Automatically check for updates")
        self.auto_check_box.setChecked(bool(state.get("auto_update_check")))
        self.auto_check_box.toggled.connect(self.on_auto_toggle)
        layout.addWidget(self.auto_check_box)

        privacy_note = QLabel(
            "When enabled, wg-tray periodically makes a single anonymous\n"
            "request to GitHub's public release list to see if a newer\n"
            "version exists. No account, hardware ID, or usage data is\n"
            "ever sent — same as opening the Releases page in a browser."
        )
        privacy_note.setWordWrap(True)
        privacy_note.setObjectName("status-disconnected")
        layout.addWidget(privacy_note)

        check_row = QHBoxLayout()
        self.check_btn = QPushButton("Check for updates now")
        self.check_btn.clicked.connect(self.on_check_clicked)
        check_row.addWidget(self.check_btn)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)

    def on_auto_toggle(self, checked):
        state = load_state()
        state["auto_update_check"] = checked
        save_state(state)

    def on_check_clicked(self):
        self.check_btn.setEnabled(False)
        self.result_label.setText("Checking…")
        QApplication.processEvents()

        release = fetch_latest_release()
        self.check_btn.setEnabled(True)

        if release is None:
            self.result_label.setText(
                "Couldn't reach GitHub to check for updates. Try again later."
            )
            return

        if is_newer_version(release["version"], APP_VERSION):
            self.result_label.setText(
                f"A newer version is available: v{release['version']}"
            )
            open_btn = QPushButton(f"Download v{release['version']}…")
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release["url"])))
            self.layout().insertWidget(self.layout().count() - 1, open_btn)
        else:
            self.result_label.setText("You're up to date.")


# ---------------------------------------------------------------------
# Changelog dialog (shown once after an update)
# ---------------------------------------------------------------------

class ChangelogDialog(QDialog):
    def __init__(self, version, notes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("What's new")
        self.resize(480, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel(f"wg-tray v{version}")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        notes_view = QTextBrowser()
        notes_view.setOpenExternalLinks(True)
        notes_view.setMarkdown(notes or "_No changelog notes available for this release._")
        layout.addWidget(notes_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


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
        self.window = MainWindow(self)
        self.rebuild_menu()
        self.tray.show()

        # Show the window once on startup; after that, the tray icon just
        # opens its menu (left-click) — "Open window..." brings it back.
        self.show_window()
        self.maybe_show_changelog()

        # Poll connection state periodically in case it changes outside
        # this app (e.g. you ran wg-quick manually in a terminal).
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(5000)

        # Opt-in only (off by default) — see SettingsDialog's privacy note.
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.maybe_auto_check_update)
        self.update_timer.start(6 * 60 * 60 * 1000)  # every 6 hours
        self.maybe_auto_check_update()

    def show_window(self):
        self.window.refresh()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def show_settings(self):
        dlg = SettingsDialog(self, self.window)
        dlg.exec()

    def maybe_show_changelog(self):
        state = load_state()
        seen = state.get("seen_version")
        if seen == APP_VERSION:
            return
        # First-ever launch (no seen_version yet) shouldn't show a changelog
        # popup — only show it when upgrading from a previously-seen version.
        if seen is not None:
            notes = fetch_release_notes_for(APP_VERSION)
            if notes is not None:
                ChangelogDialog(APP_VERSION, notes, self.window).exec()
        state["seen_version"] = APP_VERSION
        save_state(state)

    def maybe_auto_check_update(self):
        if not load_state().get("auto_update_check"):
            return
        release = fetch_latest_release()
        if release and is_newer_version(release["version"], APP_VERSION):
            self.tray.showMessage(
                "wg-tray update available",
                f"Version {release['version']} is available. Open Settings to download it.",
                QSystemTrayIcon.Information,
                8000,
            )

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
        open_window_action = QAction("Open window…", self.menu)
        open_window_action.triggered.connect(self.show_window)
        self.menu.addAction(open_window_action)

        settings_action = QAction("Settings…", self.menu)
        settings_action.triggered.connect(self.show_settings)
        self.menu.addAction(settings_action)

        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)

    def refresh_all(self):
        self.rebuild_menu()
        if self.window.isVisible():
            self.window.refresh()

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
        self.refresh_all()

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
            self.refresh_all()
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
            self.refresh_all()
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
    app.setApplicationName("wg-tray")
    app.setApplicationDisplayName("wg-tray")
    app.setStyleSheet(APP_STYLESHEET)
    app.setWindowIcon(make_app_icon())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "wg-tray", "No system tray detected on this desktop.")
        sys.exit(1)

    tray = WgTray(app)  # noqa: F841 — keep reference alive
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
