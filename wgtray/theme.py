"""Dark, Mullvad-style theme (QSS) and the code-drawn tray/app icon."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

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


def make_icon(connected):
    """Abstract tunnel glyph: two nodes joined by a connecting curve."""
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
