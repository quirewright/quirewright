"""Find-in-document bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget

from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Rect
from pdfeditor.i18n import tr
from pdfeditor.ui import theme


class FindBar(QWidget):
    hitChanged = Signal(int, object)  # page index, Rect (scene) or None
    highlightsChanged = Signal(int, list)  # page index, list[Rect]
    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc: Document | None = None
        self.hits: list[tuple[int, Rect]] = []
        self.index = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Find in document…"))
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._search)
        self.edit.returnPressed.connect(self.next)
        self.edit.installEventFilter(self)
        self.case = QCheckBox(tr("Match case"))
        self.case.toggled.connect(lambda on: self._search(self.edit.text()))
        self.count = QLabel("")
        self.count.setProperty("role", "muted")
        self.count.setMinimumWidth(90)
        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(theme.icon("chevron-left"))
        self.prev_btn.setToolTip(tr("Previous match (Shift+Enter)"))
        self.prev_btn.clicked.connect(self.previous)
        self.next_btn = QToolButton()
        self.next_btn.setIcon(theme.icon("chevron-right"))
        self.next_btn.setToolTip(tr("Next match (Enter)"))
        self.next_btn.clicked.connect(self.next)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(theme.icon("close"))
        self.close_btn.setToolTip(tr("Close (Esc)"))
        self.close_btn.clicked.connect(self.hide_bar)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.case)
        lay.addWidget(self.count)
        lay.addWidget(self.prev_btn)
        lay.addWidget(self.next_btn)
        lay.addWidget(self.close_btn)
        self.hide()

    def set_document(self, doc: Document | None) -> None:
        self.doc = doc
        self.hits = []
        self.index = -1
        self.count.setText("")

    def show_bar(self) -> None:
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text():
            self._search(self.edit.text())

    def hide_bar(self) -> None:
        self.hide()
        self.hits = []
        self.index = -1
        self.highlightsChanged.emit(-1, [])
        self.closed.emit()

    def refresh_icons(self) -> None:
        self.prev_btn.setIcon(theme.icon("chevron-left"))
        self.next_btn.setIcon(theme.icon("chevron-right"))
        self.close_btn.setIcon(theme.icon("close"))

    def _search(self, text: str) -> None:
        self.hits = []
        self.index = -1
        if self.doc is None or not text:
            self.count.setText("")
            self.highlightsChanged.emit(-1, [])
            return
        try:
            self.hits = self.doc.search(text, self.case.isChecked())
        except Exception:
            self.hits = []
        if not self.hits:
            self.count.setText(tr("No matches"))
            self.highlightsChanged.emit(-1, [])
            return
        self.next()

    def _go(self, i: int) -> None:
        if not self.hits:
            return
        self.index = i % len(self.hits)
        page, rect = self.hits[self.index]
        self.count.setText(f"{self.index + 1} of {len(self.hits)}")
        self.highlightsChanged.emit(page, [r for p, r in self.hits if p == page])
        self.hitChanged.emit(page, rect)

    def next(self) -> None:
        self._go(self.index + 1)

    def previous(self) -> None:
        self._go(self.index - 1)

    def page_highlights(self, page: int) -> list[Rect]:
        return [r for p, r in self.hits if p == page]

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit and event.type() == event.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.hide_bar()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.previous()
                return True
        return super().eventFilter(obj, event)
