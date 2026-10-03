"""Welcome screen shown when no document is open."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from quirewright import APP_NAME, __version__
from quirewright.i18n import tr
from quirewright.ui import theme


class WelcomePage(QWidget):
    openRequested = Signal()
    newRequested = Signal()
    fileRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        card = QFrame()
        card.setProperty("role", "card")
        card.setMaximumWidth(620)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 32, 36, 28)
        lay.setSpacing(14)
        head = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setPixmap(theme.app_icon().pixmap(QSize(56, 56)))
        head.addWidget(self.logo)
        titles = QVBoxLayout()
        t = QLabel(APP_NAME)
        t.setStyleSheet("font-size: 22px; font-weight: 700;")
        s = QLabel(f"Version {__version__} · " + tr("edit PDF content and pages, free and open source"))
        s.setProperty("role", "muted")
        titles.addWidget(t)
        titles.addWidget(s)
        head.addLayout(titles)
        head.addStretch()
        lay.addLayout(head)
        btns = QHBoxLayout()
        self.open_btn = QPushButton(tr("Open PDF…"))
        self.open_btn.setProperty("primary", "true")
        self.open_btn.setMinimumHeight(36)
        self.open_btn.clicked.connect(self.openRequested)
        self.new_btn = QPushButton(tr("New blank document"))
        self.new_btn.setMinimumHeight(36)
        self.new_btn.clicked.connect(self.newRequested)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.new_btn)
        btns.addStretch()
        lay.addLayout(btns)
        hint = QLabel(tr("You can also drop a PDF anywhere in this window."))
        hint.setProperty("role", "muted")
        lay.addWidget(hint)
        self.recent_label = QLabel(tr("RECENT FILES"))
        self.recent_label.setProperty("role", "heading")
        lay.addWidget(self.recent_label)
        self.recent = QListWidget()
        self.recent.setFrameShape(QFrame.Shape.NoFrame)
        self.recent.setMaximumHeight(220)
        self.recent.itemActivated.connect(self._open_item)
        self.recent.itemClicked.connect(self._open_item)
        lay.addWidget(self.recent)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        existing = [p for p in paths if os.path.exists(p)]
        for p in existing:
            it = QListWidgetItem(f"{os.path.basename(p)}    ")
            it.setToolTip(p)
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.recent.addItem(it)
        self.recent_label.setVisible(bool(existing))
        self.recent.setVisible(bool(existing))

    def refresh_theme(self) -> None:
        self.logo.setPixmap(theme.app_icon().pixmap(QSize(56, 56)))

    def _open_item(self, item: QListWidgetItem) -> None:
        p = item.data(Qt.ItemDataRole.UserRole)
        if p:
            self.fileRequested.emit(p)
