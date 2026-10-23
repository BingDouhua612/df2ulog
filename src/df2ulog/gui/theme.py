"""Dark professional theme for the df2ulog GUI (Qt stylesheet + palette + font)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

COLORS: dict[str, str] = {
    "bg": "#12161c",
    "surface": "#1a2129",
    "surface_hi": "#202935",
    "input": "#0e1319",
    "border": "#2a3542",
    "border_hi": "#33414f",
    "text": "#e6edf5",
    "text_dim": "#9fb0c3",
    "text_faint": "#7d8b9c",
    "accent": "#38bdf8",
    "accent_hi": "#5cc8fa",
    "accent_lo": "#2b9fe0",
    "on_accent": "#071018",
    "success": "#34d399",
    "error": "#f87171",
}

DARK_QSS = """
* { outline: none; }
QMainWindow, QWidget {
    background-color: #12161c;
    color: #e6edf5;
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 10pt;
}
QLabel { background: transparent; color: #e6edf5; }
QLabel#Title { font-size: 20pt; font-weight: 600; color: #f4f8fd; }
QLabel#Subtitle { color: #8b98a8; font-size: 9.5pt; }
QLabel#Hint { color: #7d8b9c; font-size: 9pt; }
QLabel#FieldLabel { color: #9fb0c3; font-size: 9.5pt; }
QLabel#DropTitle { font-size: 11.5pt; font-weight: 600; color: #dbe7f3; }
QLabel#DropIcon { font-size: 26pt; }
QLabel#StatusLabel { color: #9fb0c3; }
QLabel#StatusLabel[state="success"] { color: #34d399; font-weight: 600; }
QLabel#StatusLabel[state="error"] { color: #f87171; font-weight: 600; }
QFrame#Card {
    background-color: #1a2129;
    border: 1px solid #2a3542;
    border-radius: 12px;
}
QFrame#DropZone {
    background-color: #151b23;
    border: 2px dashed #33414f;
    border-radius: 14px;
}
QFrame#DropZone[dragging="true"] {
    border-color: #38bdf8;
    background-color: #172433;
}
QLineEdit {
    background-color: #0e1319;
    border: 1px solid #2a3542;
    border-radius: 8px;
    padding: 7px 10px;
    color: #e6edf5;
    selection-background-color: #38bdf8;
    selection-color: #071018;
}
QLineEdit:focus { border: 1px solid #38bdf8; }
QLineEdit:disabled { color: #6c7a8a; }
QPushButton {
    background-color: #232d39;
    color: #dbe7f3;
    border: 1px solid #31404f;
    border-radius: 8px;
    padding: 8px 16px;
}
QPushButton:hover { background-color: #2b3745; border-color: #3d4f61; }
QPushButton:checked { background-color: #1f3345; border-color: #38bdf8; color: #38bdf8; }
QPushButton:pressed { background-color: #1d2732; }
QPushButton:disabled {
    color: #5d6b7a;
    background-color: #1a222b;
    border-color: #26313d;
}
QPushButton#Primary {
    background-color: #38bdf8;
    color: #071018;
    border: none;
    font-size: 11pt;
    font-weight: 600;
    padding: 11px 18px;
}
QPushButton#Primary:hover { background-color: #5cc8fa; }
QPushButton#Primary:pressed { background-color: #2b9fe0; }
QPushButton#Primary:disabled { background-color: #1f3a49; color: #5f7d8f; }
QPushButton#LangSwitch {
    background-color: #1a2129;
    color: #9fb0c3;
    border: 1px solid #31404f;
    border-radius: 13px;
    padding: 4px 12px;
    font-size: 9pt;
    min-width: 40px;
}
QPushButton#LangSwitch:hover { color: #38bdf8; border-color: #38bdf8; }
QPushButton#Link {
    background: transparent;
    border: none;
    color: #38bdf8;
    padding: 2px;
}
QPushButton#Link:hover { color: #7dd3fc; }
QCheckBox { color: #c9d4e0; spacing: 8px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3a4a5b;
    background: #0e1319;
}
QCheckBox::indicator:hover { border-color: #38bdf8; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QProgressBar {
    background-color: #0e1319;
    border: 1px solid #2a3542;
    border-radius: 8px;
    min-height: 16px;
    max-height: 16px;
}
QProgressBar::chunk {
    border-radius: 7px;
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #38bdf8, stop: 1 #2dd4bf
    );
}
QTextEdit {
    background-color: #0e1319;
    font-size: 9pt;
    border: 1px solid #2a3542;
    border-radius: 10px;
    padding: 8px;
    color: #c9d4e0;
    selection-background-color: #38bdf8;
    selection-color: #071018;
}
QToolTip {
    background-color: #1f2937;
    color: #e6edf5;
    border: 1px solid #374151;
    padding: 6px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: #33414f;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #41546a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QTableWidget {
    background-color: #0e1319;
    alternate-background-color: #121a23;
    border: 1px solid #2a3542;
    border-radius: 9px;
    color: #c9d4e0;
    gridline-color: #22303d;
    selection-background-color: #1f3345;
    selection-color: #e6edf5;
}
QTableWidget::item { padding: 3px 6px; }
QHeaderView::section {
    background-color: #1a2129;
    color: #9fb0c3;
    border: none;
    border-bottom: 1px solid #2a3542;
    padding: 6px 8px;
    font-weight: 600;
    font-size: 9pt;
}
QTableCornerButton::section { background-color: #1a2129; border: none; }
QTabWidget::pane { border: none; background: transparent; margin-top: 2px; }
QTabBar::tab {
    background-color: #1a2129;
    color: #9fb0c3;
    border: 1px solid #2a3542;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 6px 18px;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #232d39; color: #dbe7f3; border-color: #31404f; }
QTabBar::tab:hover { color: #dbe7f3; }
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark professional look: Fusion style + palette + QSS + font."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface_hi"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["on_accent"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["surface_hi"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS["text_faint"]))
    app.setPalette(palette)

    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(DARK_QSS)
