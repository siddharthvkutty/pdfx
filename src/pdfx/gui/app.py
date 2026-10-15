"""Main window: a landing page of tool sheets, then one page per tool."""
from __future__ import annotations

import sys

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .theme import (
    DESK, DESK_DEEP, ICON, INK, MUTED, MUTED_ON_DESK, PAPER, PAPER_EDGE, PAPER_SHADE, RED, RED_DARK,
)
import pdfx

from .tools import TOOLS, ask_install_libreoffice
from .widgets import Sheet

# Slate desk, paper sheets, red only on actions. Surfaces differ by tone, not by lines.
QSS = f"""
QWidget {{ font-size: 15px; }}
QLabel {{ color: {INK}; }}
QMainWindow, QStackedWidget, #home {{ background: {DESK}; }}
#header {{ background: {DESK_DEEP}; }}
#logo {{ font-size: 26px; font-weight: 800; color: {PAPER}; }}
#back {{ background: transparent; color: {PAPER}; font-weight: 600; }}
#back:hover {{ background: rgba(255, 255, 255, 24); }}
#headline {{ font-size: 40px; font-weight: 800; color: {PAPER}; }}
#sub {{ font-size: 17px; color: {MUTED_ON_DESK}; }}
#panel {{ background: {PAPER}; }}
#panelTitle {{ font-size: 26px; font-weight: 800; }}
#note {{ font-size: 14px; color: {MUTED}; }}
#dropTitle {{ font-size: 34px; font-weight: 800; }}
QPushButton {{ background: {PAPER_SHADE}; color: {INK}; border: 0; border-radius: 0; padding: 10px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {PAPER_EDGE}; }}
QPushButton:disabled {{ background: {PAPER_SHADE}; color: #a3a6ab; }}
QPushButton#primary {{ background: {RED}; color: white; padding: 16px; font-size: 17px; font-weight: 700; }}
QPushButton#primary:hover {{ background: {RED_DARK}; }}
QPushButton#primary:disabled {{ background: #e7b8ba; color: white; }}
QPushButton#reset {{ background: transparent; color: {MUTED}; padding: 6px 8px; font-size: 13px; }}
QPushButton#reset:hover {{ color: {INK}; background: {PAPER_SHADE}; }}
QPushButton#reset:disabled {{ color: transparent; background: transparent; }}
QListWidget {{ background: {DESK}; border: 0; outline: 0; padding: 14px; }}
QListWidget::item {{ color: {MUTED_ON_DESK}; padding: 4px; font-size: 14px; }}
QListWidget::item:selected {{ background: rgba(216, 38, 45, 70); border: 3px solid {RED}; color: white; }}
QScrollBar:vertical {{ background: {DESK}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #4a5868; min-height: 32px; border-radius: 6px; }}
QScrollBar::handle:vertical:hover {{ background: #5d6d7f; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QLineEdit {{ background: {PAPER_SHADE}; border: 2px solid {PAPER_SHADE}; border-radius: 0; padding: 7px 8px; selection-background-color: {RED}; }}
QLineEdit:focus {{ border-color: {INK}; }}
/* any border/padding rule on QSpinBox blanks its text in Qt 6 once the buttons are hidden, so fill only */
QSpinBox {{ background: {PAPER_SHADE}; min-height: 28px; }}
QTabWidget::pane {{ border: 0; padding-top: 10px; }}
QTabBar::tab {{ background: {PAPER_SHADE}; padding: 8px 20px; font-weight: 600; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {INK}; color: white; }}
#tabpage {{ background: {PAPER}; }}
QRadioButton {{ padding: 6px 0; }}
QProgressBar {{ background: {PAPER_SHADE}; border: 0; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {RED}; }}
"""


class Card(Sheet):
    """One tool: a sheet with a few grey text lines on top, as on the app icon, and its name at the bottom."""

    clicked = Signal()

    def __init__(self, title, blurb):
        super().__init__(fold=40, radius=12, hoverable=True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)  # equal columns, not by text length
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 26, 26, 24)
        self.blurb = blurb
        t, b = QLabel(title), QLabel(blurb)
        self.blurb_label = b
        t.setStyleSheet(f"color: {INK}; font-size: 22px; font-weight: 800;")
        b.setStyleSheet(f"color: {MUTED}; font-size: 14px;")
        lay.addSpacing(54)  # room for the grey lines; titles then line up across tiles
        for w in (t, b):
            w.setWordWrap(True)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        lay.addStretch()
        self.setMinimumHeight(170)

    def set_available(self, ok: bool, note: str = ""):
        """Unavailable tiles are dimmed and show `note`; they stay clickable so the click can explain why."""
        self._hoverable = ok
        self.blurb_label.setText(self.blurb if ok else note)
        if ok:
            self.setGraphicsEffect(None)
        else:
            dim = QGraphicsOpacityEffect(self)
            dim.setOpacity(0.45)
            self.setGraphicsEffect(dim)

    def paint_content(self, p, w, h):
        p.setBrush(QColor(PAPER_EDGE))
        usable = w - 52 - 40  # keep clear of the fold
        for i, frac in enumerate((0.9, 0.7, 0.45)):
            p.drawRoundedRect(QRectF(26, 28 + i * 16, usable * frac, 8), 4, 4)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


def icon_label(height: int) -> QLabel:
    label = QLabel()
    pm = QPixmap(str(ICON))
    if not pm.isNull():
        label.setPixmap(pm.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation))
    return label


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pdfX")
        self.resize(1240, 800)

        self.stack = QStackedWidget()
        home = QWidget()
        home.setObjectName("home")
        hl = QVBoxLayout(home)
        hl.setContentsMargins(56, 36, 56, 44)
        title = QLabel("Fix your PDFs without uploading them.")
        title.setObjectName("headline")
        title.setWordWrap(True)
        font = title.font()
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 97)
        title.setFont(font)
        sub = QLabel("Merge, split, reorder, watermark, compress and convert. Everything runs on this computer.")
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        words = QVBoxLayout()
        words.addStretch()
        words.addWidget(title)
        words.addSpacing(8)
        words.addWidget(sub)
        words.addStretch()
        hero = QHBoxLayout()
        hero.addLayout(words, 1)
        hero.addSpacing(40)
        hero.addWidget(icon_label(190), alignment=Qt.AlignmentFlag.AlignVCenter)
        hl.addLayout(hero)
        cards = QGridLayout()
        cards.setSpacing(18)
        for col in range(4):
            cards.setColumnStretch(col, 1)
        hl.addSpacing(24)
        hl.addLayout(cards, 1)
        self.stack.addWidget(home)

        self.cards: list[tuple] = []
        for n, cls in enumerate(TOOLS):
            tool = cls()
            self.stack.addWidget(tool)
            card = Card(tool.title, tool.blurb)
            card.clicked.connect(lambda t=tool: self.open_tool(t))
            cards.addWidget(card, n // 4, n % 4)
            self.cards.append((tool, card))

        header = QFrame()
        header.setObjectName("header")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(20, 8, 20, 8)
        logo = QLabel(f"pdf<span style='color:{RED}'>X</span>")  # the icon's red X
        logo.setObjectName("logo")
        self.back = QPushButton("← All tools")
        self.back.setObjectName("back")
        self.back.clicked.connect(lambda: self.show_tool(home))
        self.home = home
        self.back.hide()
        hh.addWidget(logo)
        hh.addSpacing(12)
        hh.addWidget(self.back)
        hh.addStretch()

        root = QWidget()
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(header)
        col.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.refresh_availability()

    def refresh_availability(self):
        have = pdfx.libreoffice_path() is not None  # looked up again each time, in case it was just installed
        for tool, card in self.cards:
            if tool.needs_libreoffice:
                card.set_available(have, "Needs LibreOffice. Click for the download link.")

    def open_tool(self, tool):
        if tool.needs_libreoffice and not pdfx.libreoffice_path():
            ask_install_libreoffice(self)
            self.refresh_availability()
            return
        self.show_tool(tool)

    def show_tool(self, widget):
        if widget is self.home:
            self.refresh_availability()
        self.stack.setCurrentWidget(widget)
        self.back.setVisible(self.stack.currentIndex() != 0)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("pdfX")
    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)  # QSS sets every colour; keep native dialogs consistent
    app.setStyleSheet(QSS)
    win = Window()
    win.show()
    sys.exit(app.exec())
