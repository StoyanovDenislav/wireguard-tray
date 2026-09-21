"""Application entry point.

Also responsible for making the OS show "wg-tray" instead of "Python"
in the taskbar/dock/alt-tab — that identity is set at three different
layers depending on platform, none of which QApplication.setApplicationName
alone covers.
"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .platform_utils import IS_WINDOWS, find_wg_quick, find_wireguard_exe
from .theme import APP_STYLESHEET, make_app_icon
from .tray import WgTray

APP_NAME = "wg-tray"


def _set_os_level_app_identity():
    if IS_WINDOWS:
        # Without an explicit AppUserModelID, Windows groups this process
        # under "python.exe" in the taskbar and shows the Python icon
        # instead of ours.
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"wgtray.{APP_NAME}"
            )
        except (AttributeError, OSError):
            pass
    # Linux: WM_CLASS is what window managers/taskbars key off of for the
    # app name and for matching a .desktop file's icon. Qt derives it from
    # sys.argv[0] by default, which is "wg_tray"/the interpreter under
    # PyInstaller — setting it explicitly keeps it stable regardless of
    # how the binary was invoked. (Handled below via QGuiApplication.)
    # macOS: the bundle's CFBundleName (set in wg_tray.spec) is what
    # actually drives the menu bar / dock name; nothing to do here.


def main():
    if IS_WINDOWS:
        if not find_wireguard_exe():
            print("Warning: wireguard.exe not found. Install WireGuard for Windows first.")
    elif not find_wg_quick():
        print("Warning: wg-quick not found on PATH. Install wireguard-tools first.")

    _set_os_level_app_identity()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_NAME)  # Linux: matches wg-tray.desktop for name+icon
    app.setStyleSheet(APP_STYLESHEET)
    app.setWindowIcon(make_app_icon())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray detected on this desktop.")
        sys.exit(1)

    tray = WgTray(app)  # noqa: F841 — keep reference alive
    sys.exit(app.exec())
