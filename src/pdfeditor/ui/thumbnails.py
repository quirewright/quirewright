"""Pages side panel: thumbnails with multi-select and drag-to-reorder."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDropEvent, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from pdfeditor.core.document import Document
from pdfeditor.ui import theme
from pdfeditor.ui.render import render_page

THUMB_W = 132
THUMB_H = 150


class PagesPanel(QListWidget):
    pageActivated = Signal(int)
    movePagesRequested = Signal(list, int)
    contextMenuRequestedAt = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc: Document | None = None
        self._pending: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._render_next)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setIconSize(QSize(THUMB_W, THUMB_H))
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.contextMenuRequestedAt)
        self.currentRowChanged.connect(self._on_current)
        self.setMinimumWidth(THUMB_W + 48)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.remove_listener(self._on_doc_event)
        self.doc = doc
        if doc is not None:
            doc.add_listener(self._on_doc_event)
        self.refresh()

    def _on_doc_event(self, event: str, payload) -> None:
        if event in ("pages", "saved"):
            current = self.currentRow()
            self.refresh()
            if 0 <= current < self.count():
                self.setCurrentRow(current)
        elif event == "page_content":
            self._invalidate(payload)

    def refresh(self) -> None:
        self.blockSignals(True)
        self.clear()
        self._pending = []
        if self.doc is not None:
            for i in range(self.doc.page_count):
                item = QListWidgetItem(self.doc.page_label(i))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setIcon(self._placeholder(i))
                item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDragEnabled)
                item.setSizeHint(QSize(THUMB_W + 20, THUMB_H + 30))
                self.addItem(item)
                self._pending.append(i)
        self.blockSignals(False)
        if self._pending:
            self._timer.start()

    def _invalidate(self, index: int) -> None:
        if 0 <= index < self.count():
            if index not in self._pending:
                self._pending.append(index)
            self._timer.start()

    def _placeholder(self, index: int) -> QIcon:
        t = theme.current()
        pm = QPixmap(THUMB_W, THUMB_H)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.fillRect(8, 8, THUMB_W - 16, THUMB_H - 16, QColor(t.panel_alt))
        p.end()
        return QIcon(pm)

    def _render_next(self) -> None:
        if not self._pending or self.doc is None:
            self._timer.stop()
            return
        # prioritise visible rows
        vis = self.viewport().rect()
        order = sorted(self._pending, key=lambda i: 0 if self.visualItemRect(self.item(i)).intersects(vis) else 1)
        index = order[0]
        self._pending.remove(index)
        if index >= self.count() or index >= self.doc.page_count:
            return
        try:
            r = self.doc.page_rect(index)
            scale = min((THUMB_W - 8) / max(r.width, 1), (THUMB_H - 8) / max(r.height, 1))
            pm = render_page(self.doc, index, scale * self.devicePixelRatioF())
            pm.setDevicePixelRatio(self.devicePixelRatioF())
        except Exception:
            return
        framed = QPixmap(THUMB_W, THUMB_H)
        framed.fill(Qt.GlobalColor.transparent)
        p = QPainter(framed)
        w = pm.width() / pm.devicePixelRatio()
        h = pm.height() / pm.devicePixelRatio()
        x = (THUMB_W - w) / 2
        y = (THUMB_H - h) / 2
        p.fillRect(int(x) + 2, int(y) + 3, int(w), int(h), QColor(0, 0, 0, 50))
        p.drawPixmap(int(x), int(y), pm)
        p.setPen(QColor(theme.current().border))
        p.drawRect(int(x), int(y), int(w) - 1, int(h) - 1)
        p.end()
        self.item(index).setIcon(QIcon(framed))

    def _on_current(self, row: int) -> None:
        if row >= 0:
            self.pageActivated.emit(row)

    def selected_pages(self) -> list[int]:
        rows = sorted(self.row(it) for it in self.selectedItems())
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        return rows

    def set_current_page(self, index: int) -> None:
        if 0 <= index < self.count() and self.currentRow() != index:
            self.blockSignals(True)
            self.setCurrentRow(index)
            self.blockSignals(False)
            self.scrollToItem(self.item(index))

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        sources = self.selected_pages()
        target_item = self.itemAt(event.position().toPoint())
        if target_item is None:
            target = self.count()
        else:
            target = self.row(target_item)
            rect = self.visualItemRect(target_item)
            if event.position().y() > rect.center().y():
                target += 1
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        if sources and not (len(sources) == 1 and sources[0] == target):
            self.movePagesRequested.emit(sources, target)
