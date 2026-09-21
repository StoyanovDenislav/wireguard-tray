"""The tray icon, its menu, and the glue between the window/dialogs and
the WireGuard control + update-checking logic."""
from pathlib import Path

from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon,
)
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from . import APP_VERSION
from .state import list_configs, load_state, save_state
from .theme import make_icon
from .ui.dialogs import ChangelogDialog, SettingsDialog, VpnConflictDialog
from .ui.main_window import MainWindow
from .updater import fetch_latest_release, fetch_release_notes_for, is_newer_version
from .wireguard import (
    HAVE_QR, check_for_conflicting_vpn, connect, disconnect, import_conf_file,
    import_from_qr_image,
)

POLL_INTERVAL_MS = 5_000
AUTO_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 hours


class _ToggleWorker(QObject):
    """
    Runs the connect/disconnect sequence off the main thread.

    connect()/disconnect() block on subprocess.run() while pkexec/
    osascript/UAC's privilege prompt is up, with nothing pumping the Qt
    event loop in the meantime. On Linux especially, a GUI app that stops
    responding to events while a separate elevation dialog is open can
    get treated as unresponsive by the window manager and have its main
    window hidden/minimized — this worker keeps the event loop (and the
    window) alive for the whole toggle instead.
    """
    finished = Signal(bool, str)  # ok, error_message ("" if ok)

    def __init__(self, target_name, active_name):
        super().__init__()
        self.target_name = target_name
        self.active_name = active_name

    def run(self):
        # An uncaught exception here would kill the worker silently (Qt
        # doesn't propagate it anywhere visible) and leave the button
        # disabled forever, since _on_toggle_finished/set_toggle_busy(False)
        # would never run — exactly the "button stops working" failure
        # mode this replaces. Never let connect()/disconnect() raise past
        # this point uncaught.
        try:
            self._run()
        except Exception as e:
            self.finished.emit(False, f"Unexpected error: {e}")

    def _run(self):
        active = self.active_name
        name = self.target_name
        if active == name:
            ok, out = disconnect(name)
            self.finished.emit(ok, "" if ok else f"Failed to disconnect:\n{out}")
            return

        if active:
            ok, out = disconnect(active)
            if not ok:
                self.finished.emit(False, f"Failed to disconnect '{active}' first:\n{out}")
                return

        ok, out = connect(name)
        self.finished.emit(ok, "" if ok else f"Failed to connect:\n{out}")


class WgTray:
    def __init__(self, app):
        self.app = app
        self._toggle_thread = None
        self._toggle_worker = None
        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        # Not using setContextMenu here: on some platforms that binds the
        # menu to left-click too, which is exactly the split we don't
        # want. activated's reason tells left vs right click apart, and
        # QMenu.popup() is used explicitly for the right-click case.
        self.window = MainWindow(self)
        self.rebuild_menu()
        self.tray.activated.connect(self.on_tray_activated)
        # Connected once here, not per-toggle in _start_toggle_worker —
        # that was a real bug: reconnecting this signal on every toggle
        # left N stale connections after N toggles, so a single failed
        # connect/disconnect would call self.error() N times and stack
        # up N modal QMessageBox dialogs, which looked like the error
        # dialog "looping" when you tried to close it (closing one just
        # revealed the next one queued behind it).
        self.window.toggle_finished.connect(self._on_toggle_finished)
        self.tray.show()

        # Show the window once on startup.
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

    def on_tray_activated(self, reason):
        # Trigger = left-click (or the platform's primary tap) -> window.
        # Context menu request = right-click -> menu. Some platforms also
        # send DoubleClick on a fast double left-click; treat that as
        # "show the window" too rather than doing nothing.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()
        elif reason == QSystemTrayIcon.Context:
            self.menu.popup(QCursor.pos())

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

        # The VPN-conflict check/dialog only matters when we're about to
        # connect (not when just disconnecting), and needs to run on the
        # main thread since it can show a dialog.
        if active != name and not self._resolve_vpn_conflict():
            return

        self._start_toggle_worker(name, active)

    def _start_toggle_worker(self, name, active):
        if getattr(self, "_toggle_thread", None) is not None:
            return  # a toggle is already in flight; ignore re-clicks

        self.window.set_toggle_busy(True)

        self._toggle_thread = QThread()
        self._toggle_worker = _ToggleWorker(name, active)
        self._toggle_worker.moveToThread(self._toggle_thread)
        self._toggle_thread.started.connect(self._toggle_worker.run)
        # Connect the worker's finished signal to self.window's own
        # toggle_finished signal (re-emitting it), rather than to a plain
        # method on WgTray directly — WgTray is an ordinary Python
        # object, not a QObject, so Qt has no thread context for it and a
        # direct connection would invoke the handler on the worker's own
        # thread. That then touches QMenu/QAction from off the main
        # thread, logging "Cannot create children for a parent that is in
        # a different thread" (or worse). self.window *is* a QObject with
        # main-thread affinity, so this lets Qt's normal cross-thread
        # auto-queuing do the right thing. toggle_finished itself is only
        # connected to _on_toggle_finished once, in __init__ — connecting
        # it here too, per-toggle, was the bug behind stacked/looping
        # error dialogs after a couple of failed toggles.
        self._toggle_worker.finished.connect(self.window.toggle_finished)
        self._toggle_worker.finished.connect(self._toggle_thread.quit)
        self._toggle_thread.finished.connect(self._cleanup_toggle_thread)
        self._toggle_thread.start()

    def _on_toggle_finished(self, ok, error_message):
        if not ok:
            self.error(error_message)
        self.refresh_all()

    def _cleanup_toggle_thread(self):
        self.window.set_toggle_busy(False)
        self._toggle_thread.deleteLater()
        self._toggle_worker.deleteLater()
        self._toggle_thread = None
        self._toggle_worker = None

    def _resolve_vpn_conflict(self):
        """
        Checks for another VPN holding the default route before
        connecting, and if found, shows VpnConflictDialog. Returns True
        if it's fine to proceed with connecting (no conflict, or the
        user chose "Connect anyway" / successfully disconnected the
        other VPN), False if the user cancelled.
        """
        conflict = check_for_conflicting_vpn()
        if conflict is None:
            return True

        dlg = VpnConflictDialog(conflict, self.window)
        proceed = dlg.exec()
        if not proceed:
            return False
        if dlg.disconnected:
            # Re-check — disconnecting one daemon doesn't guarantee the
            # route is clear yet (or that it was even the actual culprit).
            return check_for_conflicting_vpn() is None
        return True

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
