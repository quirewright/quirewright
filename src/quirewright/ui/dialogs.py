"""Dialogs for page operations and document access."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from quirewright import APP_NAME, __version__
from quirewright.i18n import N_, tr


def parse_page_ranges(text: str, page_count: int) -> list[int]:
    """Parse '1-3, 5, 8-' into zero-based page indices (in order, deduplicated)."""
    out: list[int] = []
    text = text.strip()
    if not text or text.lower() == "all":
        return list(range(page_count))
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a.strip() else 1
            end = int(b) if b.strip() else page_count
        else:
            start = end = int(part)
        if start > end:
            start, end = end, start
        for p in range(start, end + 1):
            idx = p - 1
            if 0 <= idx < page_count and idx not in out:
                out.append(idx)
    return out


class _Dialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 14)
        self.body.setSpacing(10)
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.body.addLayout(self.form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.body.addWidget(self.buttons)


class PasswordDialog(_Dialog):
    def __init__(self, filename: str, parent=None):
        super().__init__(tr("Password required"), parent)
        lbl = QLabel(f"“{filename}” is encrypted. Enter the password to open it.")
        lbl.setWordWrap(True)
        self.body.insertWidget(0, lbl)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow(tr("Password"), self.edit)
        self.edit.setFocus()

    def password(self) -> str:
        return self.edit.text()


class InsertPagesDialog(_Dialog):
    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(tr("Insert pages from file"), parent)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText(tr("Choose a PDF…"))
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.path)
        row.addWidget(browse)
        self.form.addRow(tr("File"), row)
        self.pages = QLineEdit("all")
        self.pages.setPlaceholderText(tr("all, or e.g. 1-3, 5"))
        self.form.addRow(tr("Pages"), self.pages)
        self.position = QComboBox()
        self.position.addItem(f"After page {current + 1}", current + 1)
        self.position.addItem(f"Before page {current + 1}", current)
        self.position.addItem(tr("At the beginning"), 0)
        self.position.addItem(tr("At the end"), page_count)
        self.form.addRow(tr("Insert"), self.position)

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, tr("Choose PDF"), "", "PDF files (*.pdf);;All files (*)")
        if p:
            self.path.setText(p)

    def values(self) -> tuple[str, str, int]:
        return self.path.text().strip(), self.pages.text().strip(), int(self.position.currentData())


class ExtractPagesDialog(_Dialog):
    def __init__(self, page_count: int, selected: list[int], parent=None):
        super().__init__(tr("Extract pages"), parent)
        lbl = QLabel(tr("Save the chosen pages to a new PDF. The current document is not changed."))
        lbl.setWordWrap(True)
        self.body.insertWidget(0, lbl)
        default = ",".join(str(i + 1) for i in selected) if selected else "all"
        self.pages = QLineEdit(default)
        self.form.addRow(tr("Pages"), self.pages)
        self.page_count = page_count

    def indices(self) -> list[int]:
        return parse_page_ranges(self.pages.text(), self.page_count)


class SplitDialog(_Dialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__(tr("Split document"), parent)
        lbl = QLabel(tr("Write the document as several files, each with the given number of pages."))
        lbl.setWordWrap(True)
        self.body.insertWidget(0, lbl)
        self.chunk = QSpinBox()
        self.chunk.setRange(1, max(1, page_count))
        self.chunk.setValue(1)
        self.form.addRow(tr("Pages per file"), self.chunk)

    def chunk_size(self) -> int:
        return self.chunk.value()


class CropDialog(_Dialog):
    def __init__(self, page_count: int, selected: list[int], parent=None):
        super().__init__(tr("Crop pages"), parent)
        lbl = QLabel(tr("Trim margins (in points) from the visible page area. Content outside the crop box is hidden, not deleted."))
        lbl.setWordWrap(True)
        self.body.insertWidget(0, lbl)
        self.spins: dict[str, QDoubleSpinBox] = {}
        for key in ("Left", "Top", "Right", "Bottom"):
            s = QDoubleSpinBox()
            s.setRange(0, 10000)
            s.setDecimals(1)
            s.setSuffix(" pt")
            self.spins[key] = s
            self.form.addRow(key, s)
        self.scope = QComboBox()
        self.scope.addItem(tr("Current page"), "current")
        if len(selected) > 1:
            self.scope.addItem(f"Selected pages ({len(selected)})", "selected")
        self.scope.addItem(tr("All pages"), "all")
        self.form.addRow(tr("Apply to"), self.scope)

    def margins(self) -> tuple[float, float, float, float]:
        return tuple(self.spins[k].value() for k in ("Left", "Top", "Right", "Bottom"))  # type: ignore[return-value]

    def scope_value(self) -> str:
        return str(self.scope.currentData())


class BlankPageDialog(_Dialog):
    SIZES = {
        "Same as current page": None,
        "A4 (210 × 297 mm)": (595.28, 841.89),
        "A3 (297 × 420 mm)": (841.89, 1190.55),
        "A5 (148 × 210 mm)": (419.53, 595.28),
        "US Letter (8.5 × 11 in)": (612, 792),
        "US Legal (8.5 × 14 in)": (612, 1008),
        "Tabloid (11 × 17 in)": (792, 1224),
    }

    def __init__(self, current_size: tuple[float, float], current: int, parent=None):
        super().__init__(tr("Insert blank page"), parent)
        self.current_size = current_size
        self.size = QComboBox()
        for name in self.SIZES:
            self.size.addItem(name)
        self.form.addRow(tr("Size"), self.size)
        self.landscape = QComboBox()
        self.landscape.addItems(["Portrait", "Landscape"])
        self.form.addRow(tr("Orientation"), self.landscape)
        self.position = QComboBox()
        self.position.addItem(f"After page {current + 1}", current + 1)
        self.position.addItem(f"Before page {current + 1}", current)
        self.form.addRow(tr("Insert"), self.position)

    def values(self) -> tuple[int, float, float]:
        sz = self.SIZES[self.size.currentText()] or self.current_size
        w, h = sz
        if self.landscape.currentIndex() == 1 and w < h:
            w, h = h, w
        elif self.landscape.currentIndex() == 0 and w > h and self.SIZES[self.size.currentText()] is not None:
            w, h = h, w
        return int(self.position.currentData()), w, h


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QHBoxLayout, QTextBrowser

        from quirewright.ui import theme

        t = theme.current()
        self.setWindowTitle(tr("About {app}").format(app=APP_NAME))
        self.resize(600, 560)
        self.setMinimumSize(480, 400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 18)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(18)
        logo = QLabel()
        logo.setPixmap(theme.app_icon().pixmap(QSize(80, 80)))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        ver = QLabel(tr("Version {version}").format(version=__version__))
        ver.setProperty("role", "muted")
        titles.addWidget(title)
        titles.addWidget(ver)
        titles.addStretch()
        head.addLayout(titles, 1)
        lay.addLayout(head)
        # All prose lives in one scrollable, frameless text view so nothing can be clipped.
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setFrameShape(QTextBrowser.Shape.NoFrame)
        body.setStyleSheet(f"QTextBrowser {{ background: transparent; color: {t.text}; border: none; }}")
        body.document().setDefaultStyleSheet(f"body {{ font-size: 13px; line-height: 1.45; }} a {{ color: {t.accent}; }} .muted {{ color: {t.text_muted}; }}")
        body.setHtml(
            "<p>" + tr("A free and open-source PDF editor that combines vector object editing with page management, "
                       "forms, comments and signatures.") + "</p>"
            + "<p class='muted'>" + tr("A <i>quire</i> is a gathering of folded sheets, the basic unit of a bound book; a <i>wright</i> is a maker.") + "</p>"
            + "<p>" + self._components() + "</p>"
            + "<p>" + tr("Licensed under the GNU Affero General Public License v3.0 or later. "
                         "Source code: <a href=\"https://github.com/quirewright/quirewright\">github.com/quirewright/quirewright</a>") + "</p>"
        )
        lay.addWidget(body, 1)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.reject)
        btn.accepted.connect(self.accept)
        lay.addWidget(btn)

    @staticmethod
    def _components() -> str:
        import platform

        rows = [("Python", platform.python_version())]
        try:
            import PySide6

            rows.append(("PySide6 / Qt", PySide6.__version__))
        except Exception:
            pass
        try:
            import pymupdf

            rows.append(("PyMuPDF / MuPDF", pymupdf.VersionBind + " / " + pymupdf.VersionFitz))
        except Exception:
            pass
        try:
            from importlib.metadata import version

            rows.append(("pyHanko", version("pyhanko")))
            rows.append(("cryptography", version("cryptography")))
        except Exception:
            pass
        try:
            from quirewright.core import ocr

            rows.append(("Tesseract OCR", tr("available") if ocr.tesseract_available() else tr("not installed")))
        except Exception:
            pass
        return "<b>" + tr("Built with") + "</b><br>" + "<br>".join(f"{k}: {v}" for k, v in rows)


NOTICE_TEXT = N_(
    "This software was fully developed by AI. Its human testing and human code review has been "
    "extremely limited. This software comes with no guarantees and no warranties and should not be "
    "relied upon for any critical applications. It is released to the public in hopes that it can be "
    "useful for others. Download and use is covered under the terms of the GNU AGPL License (see "
    "LICENSE for more info). We welcome bug reports and contributions. See CONTRIBUTING for more "
    "information."
)
NOTICE_SETTING = "ui/noticeAcknowledged"


class FirstRunDialog(QDialog):
    """Shown once, on the first start, until the user acknowledges the notice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QHBoxLayout, QTextBrowser

        from quirewright.ui import theme

        t = theme.current()
        self.setWindowTitle(tr("Before you start"))
        self.setModal(True)
        self.resize(600, 470)
        self.setMinimumSize(480, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 18)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(theme.app_icon().pixmap(QSize(56, 56)))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel(tr("Please read before using {app}").format(app=APP_NAME))
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        title.setWordWrap(True)
        head.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)
        body = QTextBrowser()
        body.setOpenExternalLinks(False)
        body.setFrameShape(QTextBrowser.Shape.NoFrame)
        body.setStyleSheet(
            "QTextBrowser { background: #fdecec; color: #5a1414; border: 1px solid #e05a5a; "
            "border-left: 5px solid #c62828; border-radius: 8px; padding: 10px; font-size: 14px; }"
            if not t.dark
            else "QTextBrowser { background: #3a1a1a; color: #f6d9d9; border: 1px solid #b84a4a; "
            "border-left: 5px solid #e05a5a; border-radius: 8px; padding: 10px; font-size: 14px; }"
        )
        body.setHtml(f"<p style='line-height: 1.5'>{tr(NOTICE_TEXT)}</p>")
        lay.addWidget(body, 1)
        hint = QLabel(tr("This notice is shown once. The same text is in the README."))
        hint.setStyleSheet(f"color: {t.text_muted};")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        btn = QDialogButtonBox()
        ok = btn.addButton(tr("I understand"), QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        btn.accepted.connect(self.accept)
        lay.addWidget(btn)


def show_first_run_notice(parent, settings) -> bool:
    """Show the notice unless it was acknowledged before; return True when it was shown."""
    if settings.value(NOTICE_SETTING, "", type=str) == "1":
        return False
    FirstRunDialog(parent).exec()
    settings.setValue(NOTICE_SETTING, "1")
    settings.sync()
    return True
