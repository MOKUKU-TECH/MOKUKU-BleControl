# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Dark high-tech Qt theme for the vibe monitor, styled after
looper-robotics.com: pure-black page, near-black surfaces, hairline white
borders, sharp 2px corners, a single green accent, and uppercase
letter-spaced section headers."""
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QLabel

ACCENT = "#05cf78"
WARNING = "#ffb020"
TEXT = "#ffffff"
TEXT_SECONDARY = "#cecece"
TEXT_MUTED = "#999999"
TEXT_FAINT = "#666666"
BORDER = "rgba(255, 255, 255, 0.08)"
BORDER_STRONG = "rgba(255, 255, 255, 0.16)"

CONNECTION_COLORS = {
    "disconnected": TEXT_FAINT,
    "scanning": WARNING,
    "connecting": WARNING,
    "connected": ACCENT,
}

CLAUDE_STATE_COLORS = {
    "working": ACCENT,
    "waiting": WARNING,
    "idle": TEXT_FAINT,
}

APP_STYLESHEET = f"""
QWidget {{
    background: #000000;
    color: {TEXT};
    font-size: 13px;
}}
QLabel {{
    background: transparent;
}}
QPushButton {{
    background: #141414;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_STRONG};
    border-radius: 2px;
    padding: 7px 18px;
}}
QPushButton:hover {{
    background: #1a1a1a;
    color: {TEXT};
    border-color: rgba(255, 255, 255, 0.32);
}}
QPushButton:pressed, QPushButton:checked {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:disabled {{
    background: #0a0a0a;
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}
QPushButton[accent="true"] {{
    background: {ACCENT};
    color: #000000;
    border: 1px solid {ACCENT};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background: #04b76a;
    border-color: #04b76a;
}}
QPushButton[accent="true"]:disabled {{
    background: #0a0a0a;
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}
QListWidget, QTextEdit, QLineEdit {{
    background: #0a0a0a;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 2px;
}}
QListWidget::item {{
    padding: 4px 8px;
}}
QListWidget::item:hover {{
    background: #141414;
}}
QListWidget::item:selected {{
    background: rgba(5, 207, 120, 0.12);
    color: {ACCENT};
}}
QLineEdit {{
    padding: 6px 10px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QTabWidget::pane {{
    background: #000000;
    border: 1px solid {BORDER};
    border-radius: 2px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 8px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 2px;
    margin-top: 14px;
    padding-top: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    color: {TEXT_MUTED};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #1d1d1d;
    border-radius: 2px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #333333;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #1d1d1d;
    border-radius: 2px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QMessageBox {{
    background: #141414;
}}
QToolTip {{
    background: #1a1a1a;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER_STRONG};
}}
"""


def monospace_font(point_size=None):
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if point_size is not None:
        font.setPointSize(point_size)
    return font


def section_label(text):
    """Uppercase, letter-spaced, muted header - the looper section style."""
    label = QLabel(text.upper())
    font = label.font()
    font.setPointSize(max(1, font.pointSize() - 1))
    font.setWeight(QFont.DemiBold)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
    label.setFont(font)
    label.setStyleSheet(f"color: {TEXT_MUTED};")
    return label


def hint_label(text):
    label = QLabel(text)
    label.setStyleSheet(f"color: {TEXT_MUTED};")
    return label
