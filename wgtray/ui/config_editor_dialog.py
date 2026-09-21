"""Edit a tunnel's raw .conf, either as plain text or via a structured
form for the common fields — the user picks per the "just in case I need
to tweak something wg-tray's UI doesn't expose" escape hatch."""
import os

from PySide6.QtWidgets import (
    QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog

from .. import config_editor, key_encryption
from ..state import config_path


class ConfigEditorDialog(QDialog):
    def __init__(self, tunnel_name, parent=None):
        super().__init__(parent)
        self.tunnel_name = tunnel_name
        self.path = config_path(tunnel_name)
        self.setWindowTitle(f"Edit {tunnel_name}")
        self.resize(560, 480)

        self._original_text = self.path.read_text()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(f"Editing {tunnel_name}.conf")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        mode_row = QHBoxLayout()
        self.form_mode_btn = QPushButton("Form")
        self.raw_mode_btn = QPushButton("Raw text")
        for btn in (self.form_mode_btn, self.raw_mode_btn):
            btn.setCheckable(True)
        self.form_mode_btn.setChecked(True)
        self.form_mode_btn.clicked.connect(lambda: self._switch_mode(0))
        self.raw_mode_btn.clicked.connect(lambda: self._switch_mode(1))
        mode_row.addWidget(self.form_mode_btn)
        mode_row.addWidget(self.raw_mode_btn)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_form_page())
        self.stack.addWidget(self._build_raw_page())
        layout.addWidget(self.stack, 1)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("status-disconnected")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_into_form(self._original_text)
        self.raw_edit.setPlainText(self._original_text)

    def _switch_mode(self, index):
        # Push whatever's in the currently-visible editor into the other
        # one before switching, so edits made in one mode aren't lost or
        # silently overwritten if the user flips back and forth.
        if self.stack.currentIndex() == 0 and index == 1:
            self.raw_edit.setPlainText(self._text_from_form())
        elif self.stack.currentIndex() == 1 and index == 0:
            self._load_into_form(self.raw_edit.toPlainText())

        self.form_mode_btn.setChecked(index == 0)
        self.raw_mode_btn.setChecked(index == 1)
        self.stack.setCurrentIndex(index)
        self.error_label.setText("")

    def _build_form_page(self):
        page = QWidget()
        form = QFormLayout(page)

        self.field_inputs = {}
        for field in config_editor.INTERFACE_FIELDS:
            edit = QLineEdit()
            if field == "PrivateKey":
                edit.setEchoMode(QLineEdit.Password)
                self.private_key_edit = edit
            self.field_inputs[("Interface", field)] = edit
            form.addRow(f"{field}:", edit)

        passphrase_row = QHBoxLayout()
        self.passphrase_btn = QPushButton()
        self.passphrase_btn.clicked.connect(self._on_passphrase_clicked)
        passphrase_row.addWidget(self.passphrase_btn)
        passphrase_row.addStretch(1)
        form.addRow("Encryption:", passphrase_row)

        for field in config_editor.PEER_FIELDS:
            edit = QLineEdit()
            if field in ("PresharedKey",):
                edit.setEchoMode(QLineEdit.Password)
            self.field_inputs[("Peer", field)] = edit
            form.addRow(f"{field}:", edit)

        note = QLabel(
            "Only the fields above are editable here. Anything else in "
            "the file (comments, PostUp/PreDown hooks, etc.) is kept "
            "as-is. Switch to Raw text to edit anything not listed."
        )
        note.setWordWrap(True)
        note.setObjectName("status-disconnected")
        form.addRow(note)

        return page

    def _build_raw_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.raw_edit = QPlainTextEdit()
        self.raw_edit.setFont(QFont("Menlo, Consolas, monospace"))
        layout.addWidget(self.raw_edit)
        return page

    def _load_into_form(self, text):
        for (section, field), edit in self.field_inputs.items():
            edit.setText(config_editor.get_field(text, section, field))

        encrypted = key_encryption.is_encrypted(text)
        # The PrivateKey field shows/edits the real key when not
        # encrypted (as before), but is never a place to view or type a
        # plaintext key once encryption is on — that's the whole point.
        # Setting/removing/changing the passphrase happens through the
        # dedicated button instead, which knows how to actually decrypt
        # first when it needs the real key (e.g. to change the passphrase).
        self.private_key_edit.setEnabled(not encrypted)
        if encrypted:
            self.private_key_edit.setText("")
            self.private_key_edit.setPlaceholderText("(encrypted — see Encryption below)")
        else:
            self.private_key_edit.setPlaceholderText("")
        self.passphrase_btn.setText("Change passphrase…" if encrypted else "Set passphrase…")

    def _on_passphrase_clicked(self):
        text = self._current_text()
        encrypted = key_encryption.is_encrypted(text)

        if encrypted:
            # Changing (or removing) requires the current passphrase
            # first, to actually get at the real key.
            current_passphrase, ok = QInputDialog.getText(
                self, "Current passphrase",
                "Enter the current passphrase to change or remove it:",
                QLineEdit.Password,
            )
            if not ok:
                return
            try:
                decrypted_text = key_encryption.decrypt_config(text, current_passphrase)
            except key_encryption.DecryptionError as e:
                QMessageBox.warning(self, "Wrong passphrase", str(e))
                return

            action = QMessageBox.question(
                self, "Change or remove?",
                "Set a new passphrase, or remove encryption entirely and "
                "store the key in plain text again?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            # Yes = change to a new passphrase, No = remove encryption
            if action == QMessageBox.Cancel:
                return
            if action == QMessageBox.No:
                new_text = decrypted_text
            else:
                new_passphrase = self._prompt_new_passphrase()
                if new_passphrase is None:
                    return
                new_text = key_encryption.encrypt_config(decrypted_text, new_passphrase)
        else:
            new_passphrase = self._prompt_new_passphrase()
            if new_passphrase is None:
                return
            try:
                new_text = key_encryption.encrypt_config(text, new_passphrase)
            except ValueError as e:
                QMessageBox.warning(self, "Can't encrypt", str(e))
                return

        if self.stack.currentIndex() == 1:
            self.raw_edit.setPlainText(new_text)
        self._load_into_form(new_text)
        if self.stack.currentIndex() == 0:
            self.raw_edit.setPlainText(new_text)

    def _prompt_new_passphrase(self):
        while True:
            passphrase, ok = QInputDialog.getText(
                self, "New passphrase", "Enter a new passphrase:", QLineEdit.Password
            )
            if not ok:
                return None
            if not passphrase:
                QMessageBox.warning(self, "Empty passphrase", "Passphrase can't be empty.")
                continue
            confirm, ok = QInputDialog.getText(
                self, "Confirm passphrase", "Enter it again to confirm:", QLineEdit.Password
            )
            if not ok:
                return None
            if confirm != passphrase:
                QMessageBox.warning(self, "Doesn't match", "The two entries didn't match.")
                continue
            return passphrase

    def _text_from_form(self):
        text = self.raw_edit.toPlainText() or self._original_text
        for (section, field), edit in self.field_inputs.items():
            if edit is self.private_key_edit and not edit.isEnabled():
                # Encrypted: the field is a placeholder, not real content —
                # writing its (empty) text would blow away the encrypted
                # marker. Leave PrivateKey exactly as it already is in
                # `text`; Set/Change/Remove passphrase is the only way to
                # touch it while encrypted.
                continue
            text = config_editor.set_field(text, section, field, edit.text().strip())
        return text

    def _current_text(self):
        if self.stack.currentIndex() == 0:
            return self._text_from_form()
        return self.raw_edit.toPlainText()

    def _on_save(self):
        text = self._current_text()
        try:
            config_editor.validate(text)
        except config_editor.ConfigValidationError as e:
            self.error_label.setText(str(e))
            return

        if text == self._original_text:
            self.accept()
            return

        proceed = QMessageBox.question(
            self,
            "Save changes?",
            f"Save changes to {self.tunnel_name}.conf?\n\n"
            "If this tunnel is currently connected, changes won't take "
            "effect until you reconnect it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if proceed != QMessageBox.Yes:
            return

        # 0600 from creation, not write-then-chmod — this file may hold a
        # plaintext PrivateKey (e.g. right after removing encryption via
        # the button above), and write-then-chmod leaves a brief window
        # at default, umask-dependent permissions.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.accept()
