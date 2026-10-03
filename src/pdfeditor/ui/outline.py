"""Outline (bookmarks) panel with basic editing."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdfeditor.core.docinfo import OutlineItem
from pdfeditor.core.document import Document
from pdfeditor.i18n import N_, tr
from pdfeditor.ui import theme


class OutlinePanel(QWidget):
    pageActivated = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc: Document | None = None
        self.current_page = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._activate)
        self.tree.itemActivated.connect(self._activate)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        lay.addWidget(self.tree, 1)
        self.empty = QLabel(tr("No bookmarks. Use + to add one for the current page."))
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText(tr("+"))
        self.add_btn.setToolTip(tr("Add a bookmark for the current page"))
        self.add_btn.clicked.connect(self.add_bookmark)
        self.sub_btn = QToolButton()
        self.sub_btn.setText(tr("↳"))
        self.sub_btn.setToolTip(tr("Add a child bookmark under the selected one"))
        self.sub_btn.clicked.connect(lambda: self.add_bookmark(child=True))
        self.del_btn = QToolButton()
        self.del_btn.setIcon(theme.icon("trash"))
        self.del_btn.setToolTip(tr("Delete the selected bookmark"))
        self.del_btn.clicked.connect(self.delete_selected)
        self.ren_btn = QToolButton()
        self.ren_btn.setIcon(theme.icon("edit"))
        self.ren_btn.setToolTip(tr("Rename the selected bookmark"))
        self.ren_btn.clicked.connect(self.rename_selected)
        for b in (self.add_btn, self.sub_btn, self.ren_btn, self.del_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.remove_listener(self._on_event)
        self.doc = doc
        if doc is not None:
            doc.add_listener(self._on_event)
        self.refresh()

    def _on_event(self, event: str, payload) -> None:
        if event in ("pages", "saved"):
            self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        items = self.doc.outline() if self.doc is not None else []
        self.empty.setVisible(not items)
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for it in items:
            node = QTreeWidgetItem([it.title or "(untitled)"])
            node.setData(0, Qt.ItemDataRole.UserRole, it.page)
            node.setToolTip(0, f"Page {it.page}" if it.page > 0 else "No destination")
            while stack and stack[-1][0] >= it.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((it.level, node))
        self.tree.expandAll()
        for b in (self.add_btn, self.sub_btn, self.ren_btn, self.del_btn):
            b.setEnabled(self.doc is not None)

    def _activate(self, item: QTreeWidgetItem, col: int = 0) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(page, int) and page > 0:
            self.pageActivated.emit(page - 1)

    # -- editing ------------------------------------------------------------------
    def _flatten(self) -> list[OutlineItem]:
        out: list[OutlineItem] = []

        def walk(node: QTreeWidgetItem, level: int) -> None:
            out.append(OutlineItem(level, node.text(0), int(node.data(0, Qt.ItemDataRole.UserRole) or 0)))
            for i in range(node.childCount()):
                walk(node.child(i), level + 1)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 1)
        return out

    def add_bookmark(self, child: bool = False) -> None:
        if self.doc is None:
            return
        title, ok = QInputDialog.getText(self, "Add bookmark", f"Title for page {self.current_page + 1}:")
        if not ok or not title.strip():
            return
        node = QTreeWidgetItem([title.strip()])
        node.setData(0, Qt.ItemDataRole.UserRole, self.current_page + 1)
        sel = self.tree.currentItem()
        if child and sel is not None:
            sel.addChild(node)
        elif sel is not None and sel.parent() is not None:
            sel.parent().insertChild(sel.parent().indexOfChild(sel) + 1, node)
        elif sel is not None:
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(sel) + 1, node)
        else:
            self.tree.addTopLevelItem(node)
        self.doc.set_outline(self._flatten(), "Add bookmark")

    def rename_selected(self) -> None:
        sel = self.tree.currentItem()
        if sel is None or self.doc is None:
            return
        title, ok = QInputDialog.getText(self, tr("Rename bookmark"), tr("Title:"), text=sel.text(0))
        if ok and title.strip():
            sel.setText(0, title.strip())
            self.doc.set_outline(self._flatten(), "Rename bookmark")

    def delete_selected(self) -> None:
        sel = self.tree.currentItem()
        if sel is None or self.doc is None:
            return
        parent = sel.parent()
        if parent is not None:
            parent.removeChild(sel)
        else:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(sel))
        self.doc.set_outline(self._flatten(), "Delete bookmark")

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(tr("Add bookmark here"), self.add_bookmark)
        menu.addAction(tr("Add child bookmark"), lambda: self.add_bookmark(child=True))
        if self.tree.currentItem() is not None:
            menu.addAction(tr("Rename…"), self.rename_selected)
            menu.addAction(tr("Set to current page"), self._retarget)
            menu.addSeparator()
            menu.addAction(tr("Delete"), self.delete_selected)
        menu.exec(self.tree.mapToGlobal(pos))

    def _retarget(self) -> None:
        sel = self.tree.currentItem()
        if sel is None or self.doc is None:
            return
        sel.setData(0, Qt.ItemDataRole.UserRole, self.current_page + 1)
        self.doc.set_outline(self._flatten(), "Edit bookmark")
