"""Sidebar (tunnel list) + detail pane main window, Mullvad/OpenVPN-style."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..state import list_configs


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
