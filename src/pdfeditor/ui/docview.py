"""One open document: find bar, rulers and canvas, shown as a tab."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from pdfeditor.core.document import Document
from pdfeditor.ui import theme
from pdfeditor.ui.canvas import PageCanvas
from pdfeditor.ui.findbar import FindBar
from pdfeditor.ui.rulers import RULER_SIZE, Ruler


class DocumentView(QWidget):
    def __init__(self, doc: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc = doc
        self.canvas = PageCanvas()
        self.findbar = FindBar()
        self.hruler = Ruler(self.canvas, "h")
        self.vruler = Ruler(self.canvas, "v")
        self.corner = QWidget()
        self.corner.setFixedSize(RULER_SIZE, RULER_SIZE)
        self.corner.setAutoFillBackground(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.findbar)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.corner, 0, 0)
        grid.addWidget(self.hruler, 0, 1)
        grid.addWidget(self.vruler, 1, 0)
        grid.addWidget(self.canvas, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        lay.addWidget(grid_w, 1)

        self.canvas.cursorMoved.connect(self._cursor_moved)
        self.canvas.viewChanged.connect(self.refresh_rulers)
        self.canvas.pageChanged.connect(lambda i: self.refresh_rulers())
        self.canvas.pageEdited.connect(lambda i: self.refresh_rulers())
        for ruler in (self.hruler, self.vruler):
            ruler.guidePreview.connect(self.canvas.set_guide_preview)
            ruler.guideRequested.connect(self.canvas.add_guide)
        self.findbar.set_document(doc)
        self.canvas.set_document(doc)
        self.apply_theme()

    def set_rulers_visible(self, on: bool) -> None:
        self.hruler.setVisible(on)
        self.vruler.setVisible(on)
        self.corner.setVisible(on)

    def apply_theme(self) -> None:
        t = theme.current()
        self.corner.setStyleSheet(f"background: {t.panel}; border-right: 1px solid {t.border}; border-bottom: 1px solid {t.border};")
        self.canvas.apply_theme()
        self.findbar.refresh_icons()
        self.refresh_rulers()

    def refresh_rulers(self) -> None:
        self.hruler.update()
        self.vruler.update()

    def _cursor_moved(self, pos: QPointF) -> None:
        self.hruler.set_cursor(pos.x())
        self.vruler.set_cursor(pos.y())

    def title(self) -> str:
        return ("• " if self.doc.is_modified else "") + self.doc.title

    def tooltip(self) -> str:
        return self.doc.path or "Unsaved document"

    def close_document(self) -> None:
        self.findbar.set_document(None)
        self.canvas.set_document(None)
        self.doc.close()
