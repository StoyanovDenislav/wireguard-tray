"""Sidebar (tunnel list) + detail pane main window, Mullvad/OpenVPN-style."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import config_editor, leak_protection
from ..state import config_path, leak_protection_enabled, list_configs, set_leak_protection
from .config_editor_dialog import ConfigEditorDialog


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

        self.leak_protection_box = QCheckBox("Kill switch + leak protection")
        self.leak_protection_box.setToolTip(
            "While this tunnel is connected, ALL other internet access on\n"
            "this machine is blocked if the tunnel drops — that's the point\n"
            "of a kill switch, but it means losing internet, not just losing\n"
            "the VPN, until you reconnect or disconnect from wg-tray.\n\n"
            "Also blocks DNS queries and disables IPv6 on your physical\n"
            "network interfaces while connected. Can't be changed while\n"
            "this tunnel is connected."
        )
        self.leak_protection_box.toggled.connect(self.on_leak_protection_toggled)
        if not leak_protection.is_supported():
            self.leak_protection_box.setVisible(False)
        leak_row = QHBoxLayout()
        leak_row.addStretch(1)
        leak_row.addWidget(self.leak_protection_box)
        leak_row.addStretch(1)
        detail_layout.addLayout(leak_row)

        detail_layout.addSpacing(8)

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

        detail_layout.addSpacing(8)

        self.edit_config_btn = QPushButton("Edit config…")
        self.edit_config_btn.clicked.connect(self.on_edit_config_clicked)
        edit_row = QHBoxLayout()
        edit_row.addStretch(1)
        edit_row.addWidget(self.edit_config_btn)
        edit_row.addStretch(1)
        detail_layout.addLayout(edit_row)

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
            self.leak_protection_box.setEnabled(False)
            self.edit_config_btn.setEnabled(False)
            self._repolish(self.status_label, self.toggle_btn)
            return

        self.toggle_btn.setEnabled(True)
        self.name_label.setText(name)

        self.leak_protection_box.blockSignals(True)
        self.leak_protection_box.setChecked(leak_protection_enabled(name))
        self.leak_protection_box.setEnabled(name != active)
        self.leak_protection_box.blockSignals(False)

        self.edit_config_btn.setEnabled(name != active)
        self.edit_config_btn.setToolTip(
            "Disconnect this tunnel first to edit its config." if name == active else ""
        )

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

    def on_leak_protection_toggled(self, checked):
        name = self.selected_name()
        if name is None:
            return

        if checked:
            has_dns = bool(config_editor.get_field(
                config_path(name).read_text(), "Interface", "DNS"
            ))

            message = (
                "This blocks ALL other internet access on this machine if "
                "the tunnel drops, not just the VPN — you'll lose internet "
                "entirely until you reconnect or disconnect this tunnel in "
                "wg-tray.\n\nIt also blocks DNS queries and disables IPv6 "
                "on your physical network interfaces while connected.\n\n"
            )
            if not has_dns:
                message += (
                    "⚠ This tunnel's config has no DNS server set. DNS queries "
                    "will be blocked on your physical network with nothing "
                    "redirecting them through the tunnel instead — name "
                    "resolution will likely stop working entirely while "
                    "connected. Add a DNS = line via Edit config… first "
                    "unless you're sure this is what you want.\n\n"
                )
            message += "Enable it for this tunnel?"

            proceed = QMessageBox.question(
                self,
                "Enable kill switch?",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                self.leak_protection_box.blockSignals(True)
                self.leak_protection_box.setChecked(False)
                self.leak_protection_box.blockSignals(False)
                return

        set_leak_protection(name, checked)
        if not checked:
            leak_protection.remove_protected_config(name)

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

    def on_edit_config_clicked(self):
        name = self.selected_name()
        if name is None:
            return
        dlg = ConfigEditorDialog(name, self)
        dlg.exec()
