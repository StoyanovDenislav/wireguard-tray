#!/usr/bin/env python3
"""
Render wg_tray's code-drawn icon to real PNG files on disk, for use in
packaging (AppImage .desktop icon, Windows .ico, macOS .icns) where the
target format needs an actual asset rather than a QIcon built at runtime.

Usage: python3 scripts/export_icon.py <out_dir>
Writes <out_dir>/icon_16.png .. icon_1024.png plus icon.png (512).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from wgtray.theme import make_icon

SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)

    app = QApplication([])
    base = make_icon(True).pixmap(256, 256)

    for size in SIZES:
        scaled = base.scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        scaled.save(os.path.join(out_dir, f"icon_{size}.png"))

    base.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(
        os.path.join(out_dir, "icon.png")
    )
    print(f"Wrote icons to {out_dir}")


if __name__ == "__main__":
    main()
