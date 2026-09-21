"""Settings dialog (update-check preferences) and the one-time changelog
screen shown after an update."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import APP_VERSION
from ..self_update import UpdateError, install_and_relaunch, is_frozen
from ..state import load_state, save_state
from ..updater import asset_for_platform, fetch_latest_release, is_newer_version


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

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self._install_btn = None  # created on demand once an update is found

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)

    def on_auto_toggle(self, checked):
        state = load_state()
        state["auto_update_check"] = checked
        save_state(state)

    def _clear_install_button(self):
        if self._install_btn is not None:
            self._install_btn.setParent(None)
            self._install_btn.deleteLater()
            self._install_btn = None

    def on_check_clicked(self):
        self._clear_install_button()
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

        if not is_newer_version(release["version"], APP_VERSION):
            self.result_label.setText("You're up to date.")
            return

        if not is_frozen():
            self.result_label.setText(
                f"A newer version is available: v{release['version']}\n"
                "(running from source — pull the latest and restart to update)"
            )
            return

        asset = asset_for_platform(release["assets"])
        if asset is None:
            self.result_label.setText(
                f"A newer version is available: v{release['version']}, but no "
                "matching download was found for your platform."
            )
            self._install_btn = QPushButton("Open Releases page…")
            self._install_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release["url"])))
            self.layout().insertWidget(self.layout().count() - 2, self._install_btn)
            return

        self.result_label.setText(f"A newer version is available: v{release['version']}")
        self._install_btn = QPushButton(f"Install v{release['version']}…")
        self._install_btn.clicked.connect(lambda: self.on_install_clicked(asset))
        self.layout().insertWidget(self.layout().count() - 2, self._install_btn)

    def on_install_clicked(self, asset):
        proceed = QMessageBox.question(
            self,
            "Install update?",
            f"Download and install {asset['name']}?\n\n"
            "wg-tray will quit and restart automatically once the update "
            "is installed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if proceed != QMessageBox.Yes:
            return

        self.check_btn.setEnabled(False)
        self._install_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # indeterminate until we know total size

        def on_progress(done, total):
            if total:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(done)
            QApplication.processEvents()

        self.result_label.setText("Downloading update…")
        QApplication.processEvents()

        try:
            install_and_relaunch(asset, on_progress=on_progress)
            # install_and_relaunch calls os._exit(0) on success — nothing
            # after this line runs on the happy path. If we get here, an
            # exception was already raised and caught below instead.
        except UpdateError as e:
            self.progress_bar.setVisible(False)
            self.check_btn.setEnabled(True)
            self._install_btn.setEnabled(True)
            self.result_label.setText(f"Update failed: {e}")


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
