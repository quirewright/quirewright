"""In-app help viewer: renders the bundled Markdown user guide with a contents sidebar and search."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QImage, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMainWindow,
    QSplitter,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from quirewright import APP_NAME
from quirewright.i18n import tr
from quirewright.ui import theme

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "help")
GUIDE_PATH = os.path.join(HELP_DIR, "USER_GUIDE.md")


class GuideBrowser(QTextBrowser):
    """QTextBrowser that loads images from the help directory and fits them to the viewport width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._natural: dict[str, tuple[int, int]] = {}

    def loadResource(self, kind: int, url: QUrl):
        if kind == QTextDocument.ResourceType.ImageResource:
            path = url.toLocalFile() if url.isLocalFile() else os.path.join(HELP_DIR, url.toString())
            image = QImage(path)
            if not image.isNull():
                self._natural[url.toString()] = (image.width(), image.height())
                return image
        return super().loadResource(kind, url)

    def fit_images(self) -> None:
        """Give every image a width no larger than the viewport (keeping its aspect ratio)."""
        doc = self.document()
        avail = self.viewport().width() - 2 * int(doc.documentMargin()) - 8
        if avail < 100:
            return
        cursor = QTextCursor(doc)
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isImageFormat():
                    img = fmt.toImageFormat()
                    natural = self._natural.get(img.name())
                    if natural is None:
                        self.loadResource(QTextDocument.ResourceType.ImageResource, QUrl(img.name()))
                        natural = self._natural.get(img.name())
                    if natural:
                        w = min(avail, natural[0])
                        if int(img.width()) != w:
                            img.setWidth(w)
                            img.setHeight(round(w * natural[1] / natural[0]))
                            cursor.setPosition(frag.position())
                            cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                            cursor.setCharFormat(img)
                it += 1
            block = block.next()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.fit_images()


def guide_markdown() -> str:
    try:
        with open(GUIDE_PATH, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "# User guide\n\nThe guide file is missing from this installation."


def _stylesheet(t: theme.Theme) -> str:
    return f"""
    body {{ color: {t.text}; font-size: 14px; line-height: 1.5; }}
    h1 {{ font-size: 26px; font-weight: 700; margin-top: 0; margin-bottom: 12px; }}
    h2 {{ font-size: 19px; font-weight: 700; margin-top: 28px; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid {t.border}; }}
    h3 {{ font-size: 15px; font-weight: 700; margin-top: 18px; margin-bottom: 6px; color: {t.accent}; }}
    p {{ margin: 6px 0 10px 0; }}
    li {{ margin: 3px 0; }}
    a {{ color: {t.accent}; text-decoration: none; }}
    code {{ font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; background: {t.panel_alt}; padding: 1px 4px; border-radius: 3px; }}
    pre {{ font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 10px; margin: 8px 0; }}
    table {{ border-collapse: collapse; margin: 8px 0 12px 0; }}
    th {{ background: {t.panel_alt}; text-align: left; padding: 6px 10px; border: 1px solid {t.border}; font-weight: 600; }}
    td {{ padding: 5px 10px; border: 1px solid {t.border}; vertical-align: top; }}
    hr {{ border: none; border-top: 1px solid {t.border}; }}
    """


class HelpWindow(QMainWindow):
    """A small reader with a contents tree, search, and themed Markdown rendering."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Help")
        self.resize(1040, 760)
        self.setWindowFlag(Qt.WindowType.Window, True)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)
        self.back_btn = QToolButton()
        self.back_btn.setIcon(theme.icon("chevron-left"))
        self.back_btn.setToolTip(tr("Back (Alt+Left)"))
        self.fwd_btn = QToolButton()
        self.fwd_btn.setIcon(theme.icon("chevron-right"))
        self.fwd_btn.setToolTip(tr("Forward (Alt+Right)"))
        tb.addWidget(self.back_btn)
        tb.addWidget(self.fwd_btn)
        tb.addSeparator()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search the guide…  (Enter: next, Shift+Enter: previous)"))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(320)
        tb.addWidget(self.search)
        self.match_label = QLabel("")
        self.match_label.setProperty("role", "muted")
        self.match_label.setContentsMargins(10, 0, 10, 0)
        tb.addWidget(self.match_label)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        self.open_ext = QToolButton()
        self.open_ext.setIcon(theme.icon("export"))
        self.open_ext.setToolTip(tr("Open the guide in your default Markdown viewer"))
        self.open_ext.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(GUIDE_PATH)))
        tb.addWidget(self.open_ext)

        split = QSplitter()
        self.toc = QTreeWidget()
        self.toc.setHeaderHidden(True)
        self.toc.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.toc.setMinimumWidth(200)
        self.toc.setIndentation(14)
        self.browser = GuideBrowser()
        self.browser.setSearchPaths([HELP_DIR])
        self.browser.setOpenExternalLinks(True)
        self.browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.browser.document().setDocumentMargin(28)
        split.addWidget(self.toc)
        split.addWidget(self.browser)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 800])
        self.setCentralWidget(split)

        self.back_btn.clicked.connect(self.browser.backward)
        self.fwd_btn.clicked.connect(self.browser.forward)
        self.browser.backwardAvailable.connect(self.back_btn.setEnabled)
        self.browser.forwardAvailable.connect(self.fwd_btn.setEnabled)
        self.toc.currentItemChanged.connect(self._toc_activated)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._search_next)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Shift+Return"), self.search, activated=self._search_prev)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.browser.backward)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.browser.forward)
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        self.reload()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        t = theme.current()
        doc = self.browser.document()
        doc.setDefaultStyleSheet(_stylesheet(t))
        font = QFont()
        font.setPointSizeF(10.5)
        self.browser.setFont(font)
        self.browser.setMarkdown(guide_markdown())
        self.browser.fit_images()
        self.browser.setStyleSheet(f"QTextBrowser {{ background: {t.panel}; color: {t.text}; }}")
        self.toc.setStyleSheet(f"QTreeWidget {{ background: {t.panel_alt}; }} QTreeWidget::item {{ padding: 4px 2px; }}")
        self._build_toc()
        self.back_btn.setEnabled(False)
        self.fwd_btn.setEnabled(False)

    def _build_toc(self) -> None:
        self.toc.blockSignals(True)
        self.toc.clear()
        doc = self.browser.document()
        block = doc.begin()
        parents: dict[int, QTreeWidgetItem] = {}
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level and 1 <= level <= 3:
                item = QTreeWidgetItem([block.text()])
                item.setData(0, Qt.ItemDataRole.UserRole, block.blockNumber())
                if level == 1:
                    item.setFont(0, _bold(item.font(0)))
                    self.toc.addTopLevelItem(item)
                    parents = {1: item}
                else:
                    parent = parents.get(level - 1) or parents.get(1)
                    if parent is not None:
                        parent.addChild(item)
                    else:
                        self.toc.addTopLevelItem(item)
                    parents[level] = item
            block = block.next()
        self.toc.expandAll()
        self.toc.blockSignals(False)

    def _toc_activated(self, item: QTreeWidgetItem | None, previous=None) -> None:
        if item is None:
            return
        n = item.data(0, Qt.ItemDataRole.UserRole)
        block = self.browser.document().findBlockByNumber(int(n))
        if not block.isValid():
            return
        top = self.browser.document().documentLayout().blockBoundingRect(block).top()
        self.browser.verticalScrollBar().setValue(int(top) - 8)
        cursor = QTextCursor(block)
        self.browser.setTextCursor(cursor)

    def show_section(self, title: str) -> None:
        """Scroll to the first heading whose text contains ``title`` (case-insensitive)."""
        needle = title.lower()
        for i in range(self.toc.topLevelItemCount()):
            found = self._find_item(self.toc.topLevelItem(i), needle)
            if found is not None:
                self.toc.setCurrentItem(found)
                return

    def _find_item(self, item: QTreeWidgetItem, needle: str) -> QTreeWidgetItem | None:
        if needle in item.text(0).lower():
            return item
        for i in range(item.childCount()):
            r = self._find_item(item.child(i), needle)
            if r is not None:
                return r
        return None

    # -- search ----------------------------------------------------------------
    def _search_changed(self, text: str) -> None:
        self.browser.moveCursor(QTextCursor.MoveOperation.Start)
        if not text:
            self.match_label.setText("")
            return
        self._search_next()

    def _count_matches(self, text: str) -> int:
        doc = self.browser.document()
        n = 0
        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(text, cursor)
            if cursor.isNull():
                break
            n += 1
        return n

    def _search_next(self) -> None:
        text = self.search.text()
        if not text:
            return
        if not self.browser.find(text):
            self.browser.moveCursor(QTextCursor.MoveOperation.Start)
            self.browser.find(text)
        self.match_label.setText(f"{self._count_matches(text)} match(es)")

    def _search_prev(self) -> None:
        text = self.search.text()
        if not text:
            return
        if not self.browser.find(text, QTextDocument.FindFlag.FindBackward):
            self.browser.moveCursor(QTextCursor.MoveOperation.End)
            self.browser.find(text, QTextDocument.FindFlag.FindBackward)


def _bold(font: QFont) -> QFont:
    f = QFont(font)
    f.setBold(True)
    return f
