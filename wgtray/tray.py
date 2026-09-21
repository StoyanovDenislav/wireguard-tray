"""The tray icon, its menu, and the glue between the window/dialogs and
the WireGuard control + update-checking logic."""
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon,
)
from PySide6.QtCore import QTimer

from . import APP_VERSION
from .state import list_configs, load_state, save_state
from .theme import make_icon
from .ui.dialogs import ChangelogDialog, SettingsDialog
from .ui.main_window import MainWindow
from .updater import fetch_latest_release, fetch_release_notes_for, is_newer_version
from .wireguard import HAVE_QR, connect, disconnect, import_conf_file, import_from_qr_image

POLL_INTERVAL_MS = 5_000
AUTO_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 hours


class WgTray:
    def __init__(self, app):
        self.app = app
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
        self.timer.start(POLL_INTERVAL_MS)

        # Opt-in only (off by default) — see SettingsDialog's privacy note.
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.maybe_auto_check_update)
        self.update_timer.start(AUTO_UPDATE_CHECK_INTERVAL_MS)
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
