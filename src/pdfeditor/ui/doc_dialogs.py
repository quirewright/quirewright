"""Document-level dialogs: properties, security, resources, decorations, export, preferences, shortcuts."""

from __future__ import annotations

import datetime as _dt
import os

from PySide6.QtCore import QByteArray, QDate, QDateTime, QSize, Qt, QTime
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdfeditor import APP_ID
from pdfeditor.core.docinfo import PERMISSIONS, SecuritySettings, datetime_to_pdf_date, pdf_date_to_datetime
from pdfeditor.core.document import Document
from pdfeditor.i18n import N_, tr
from pdfeditor.ui.units import UNITS, current_unit, set_current_unit


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class _Base(QDialog):
    def __init__(self, title: str, parent=None, width: int = 460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 14)
        self.body.setSpacing(10)

    def add_buttons(self, ok_text: str = "OK", cancel: bool = True) -> QDialogButtonBox:
        flags = QDialogButtonBox.StandardButton.Ok
        if cancel:
            flags |= QDialogButtonBox.StandardButton.Cancel
        box = QDialogButtonBox(flags)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.body.addWidget(box)
        return box


# --- Document properties ------------------------------------------------------------

class PropertiesDialog(_Base):
    def __init__(self, doc: Document, parent=None):
        super().__init__(tr("Document properties"), parent, 520)
        self.doc = doc
        tabs = QTabWidget()
        self.body.addWidget(tabs)
        # metadata
        meta = QWidget()
        form = QFormLayout(meta)
        form.setHorizontalSpacing(12)
        md = doc.metadata()
        self.fields: dict[str, QLineEdit] = {}
        for key, label in (("title", "Title"), ("author", "Author"), ("subject", "Subject"), ("keywords", "Keywords"), ("creator", "Creator"), ("producer", "Producer")):
            e = QLineEdit(md.get(key, ""))
            self.fields[key] = e
            form.addRow(label, e)
        self.created = _date_edit(md.get("creationDate", ""))
        self.modified = _date_edit(md.get("modDate", ""))
        form.addRow(tr("Created"), self.created)
        form.addRow(tr("Modified"), self.modified)
        tabs.addTab(meta, tr("Description"))
        # info
        info_w = QWidget()
        grid = QFormLayout(info_w)
        info = doc.document_info()
        sec = doc.security_info()
        perms = ", ".join(sorted(k for k, v in sec["permissions"].items() if v)) if sec["encrypted"] else "all"
        rows = [
            ("File", doc.path or "(unsaved)"),
            ("File size", _human_size(info["file_size"]) if info["file_size"] else "–"),
            ("PDF version", info["format"] or "–"),
            ("Pages", str(info["pages"])),
            ("Encryption", info["encryption"] or "none"),
            ("Permissions", perms),
            ("Interactive form", "yes" if info["is_form"] else "no"),
            ("XMP metadata", "present" if info["has_xml_metadata"] else "none"),
            ("Attachments", str(len(doc.attachments()))),
        ]
        for k, v in rows:
            lbl = QLabel(v)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addRow(k, lbl)
        tabs.addTab(info_w, tr("Details"))
        self.add_buttons("Apply")

    def values(self) -> dict[str, str]:
        out = {k: e.text() for k, e in self.fields.items()}
        out["creationDate"] = _date_value(self.created)
        out["modDate"] = _date_value(self.modified)
        return out


def _signature_count(doc) -> int:
    try:
        from pdfeditor.core import signing

        data = open(doc.path, "rb").read() if doc.path else doc.pdf.tobytes()
        return len(signing.signatures(data))
    except Exception:
        return 0


def _date_edit(pdf_date: str) -> QDateTimeEdit:
    e = QDateTimeEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("yyyy-MM-dd HH:mm")
    dt = pdf_date_to_datetime(pdf_date)
    e.setSpecialValueText(tr("(not set)"))
    e.setMinimumDateTime(QDateTime(QDate(1900, 1, 1), QTime(0, 0)))
    if dt is None:
        e.setDateTime(e.minimumDateTime())
    else:
        e.setDateTime(QDateTime(QDate(dt.year, dt.month, dt.day), QTime(dt.hour, dt.minute, dt.second)))
    return e


def _date_value(e: QDateTimeEdit) -> str:
    if e.dateTime() == e.minimumDateTime():
        return ""
    q = e.dateTime()
    return datetime_to_pdf_date(_dt.datetime(q.date().year(), q.date().month(), q.date().day(), q.time().hour(), q.time().minute(), q.time().second()))


# --- Security -----------------------------------------------------------------------

class SecurityDialog(_Base):
    def __init__(self, doc: Document, parent=None):
        super().__init__(tr("Document security"), parent, 480)
        info = doc.security_info()
        pending: SecuritySettings = info["pending"]
        status = QLabel(
            f"This document is currently <b>{'encrypted (' + info['method'] + ')' if info['encrypted'] else 'not encrypted'}</b>."
            " Changes take effect when the document is saved."
        )
        status.setWordWrap(True)
        self.body.addWidget(status)
        self.keep = QRadioButton(tr("Keep the current security settings"))
        self.none = QRadioButton(tr("No password or restrictions"))
        self.encrypt = QRadioButton(tr("Protect with passwords and permissions"))
        self.body.addWidget(self.keep)
        self.body.addWidget(self.none)
        self.body.addWidget(self.encrypt)
        box = QGroupBox(tr("Passwords"))
        form = QFormLayout(box)
        self.user_pw = QLineEdit(pending.user_password)
        self.user_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.user_pw.setPlaceholderText(tr("Required to open the document (optional)"))
        self.owner_pw = QLineEdit(pending.owner_password)
        self.owner_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner_pw.setPlaceholderText(tr("Required to change permissions"))
        self.show_pw = QCheckBox(tr("Show passwords"))
        self.show_pw.toggled.connect(lambda on: [e.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password) for e in (self.user_pw, self.owner_pw)])
        self.method = QComboBox()
        self.method.addItem(tr("AES 256-bit (recommended)"), "aes256")
        self.method.addItem(tr("AES 128-bit"), "aes128")
        self.method.addItem(tr("RC4 128-bit (legacy)"), "rc4_128")
        idx = self.method.findData(pending.method)
        self.method.setCurrentIndex(max(idx, 0))
        form.addRow(tr("Open password"), self.user_pw)
        form.addRow(tr("Owner password"), self.owner_pw)
        form.addRow("", self.show_pw)
        form.addRow(tr("Encryption"), self.method)
        self.body.addWidget(box)
        pbox = QGroupBox(tr("Allow readers to"))
        grid = QGridLayout(pbox)
        self.perm_checks: dict[str, QCheckBox] = {}
        labels = {
            "print": "Print", "print_hq": "Print in high quality", "copy": "Copy text and images", "modify": "Modify content",
            "annotate": "Add comments", "form": "Fill in forms", "accessibility": "Extract for accessibility", "assemble": "Assemble pages",
        }
        for i, (key, label) in enumerate(labels.items()):
            cb = QCheckBox(label)
            cb.setChecked(bool(pending.permissions & PERMISSIONS[key]))
            self.perm_checks[key] = cb
            grid.addWidget(cb, i // 2, i % 2)
        self.body.addWidget(pbox)
        self.enc_widgets = (box, pbox)
        for r in (self.keep, self.none, self.encrypt):
            r.toggled.connect(self._sync)
        {"keep": self.keep, "none": self.none}.get(pending.method, self.encrypt).setChecked(True)
        self._sync()
        self.add_buttons("Apply")

    def _sync(self) -> None:
        on = self.encrypt.isChecked()
        for w in self.enc_widgets:
            w.setEnabled(on)

    def settings(self) -> SecuritySettings:
        if self.keep.isChecked():
            return SecuritySettings(method="keep")
        if self.none.isChecked():
            return SecuritySettings(method="none")
        perms = 0
        for key, cb in self.perm_checks.items():
            if cb.isChecked():
                perms |= PERMISSIONS[key]
        return SecuritySettings(
            method=str(self.method.currentData()), user_password=self.user_pw.text(), owner_password=self.owner_pw.text(), permissions=perms,
        )


# --- Resources (images, fonts, attachments) --------------------------------------------

class ResourcesDialog(_Base):
    def __init__(self, doc: Document, parent=None, on_change=None):
        super().__init__(tr("Document resources"), parent, 680)
        self.doc = doc
        self.on_change = on_change
        self.setMinimumHeight(460)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs)
        self._build_images()
        self._build_fonts()
        self._build_attachments()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        self.body.addWidget(close)

    def _table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.setAlternatingRowColors(True)
        return t

    # images
    def _build_images(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.img_table = self._table(["Preview", "Name", "Size", "Colour", "Pages", "Bytes"])
        self.img_table.setIconSize(QSize(64, 64))
        lay.addWidget(self.img_table)
        row = QHBoxLayout()
        row.addStretch()
        b1 = QPushButton(tr("Extract selected…"))
        b2 = QPushButton(tr("Extract all…"))
        b1.clicked.connect(lambda: self._extract_images(selected=True))
        b2.clicked.connect(lambda: self._extract_images(selected=False))
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        self.tabs.addTab(w, tr("Images"))
        self.images = self.doc.list_images()
        self.img_table.setRowCount(len(self.images))
        for r, im in enumerate(self.images):
            icon_item = QTableWidgetItem()
            png = self.doc.image_pixmap_bytes(im.xref, 64)
            if png:
                pm = QPixmap()
                pm.loadFromData(QByteArray(png))
                icon_item.setIcon(QIcon(pm))
            self.img_table.setItem(r, 0, icon_item)
            self.img_table.setItem(r, 1, QTableWidgetItem(im.name))
            self.img_table.setItem(r, 2, QTableWidgetItem(f"{im.width} × {im.height}"))
            self.img_table.setItem(r, 3, QTableWidgetItem(f"{im.colorspace} {im.bpc} bpc"))
            self.img_table.setItem(r, 4, QTableWidgetItem(", ".join(str(p + 1) for p in im.pages)))
            self.img_table.setItem(r, 5, QTableWidgetItem(_human_size(im.size)))
            self.img_table.setRowHeight(r, 68)
        self.tabs.setTabText(0, f"Images ({len(self.images)})")

    def _extract_images(self, selected: bool) -> None:
        rows = sorted({i.row() for i in self.img_table.selectedIndexes()}) if selected else list(range(len(self.images)))
        if not rows:
            QMessageBox.information(self, tr("Extract images"), tr("Select one or more images first."))
            return
        if len(rows) == 1:
            im = self.images[rows[0]]
            ext, data = self.doc.extract_image(im.xref)
            path, _ = QFileDialog.getSaveFileName(self, tr("Save image"), f"{im.name}.{ext}", f"Image (*.{ext})")
            if path:
                open(path, "wb").write(data)
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Choose folder for images"))
        if not folder:
            return
        n = 0
        for r in rows:
            im = self.images[r]
            try:
                ext, data = self.doc.extract_image(im.xref)
            except Exception:
                continue
            open(os.path.join(folder, f"image-{im.xref}-{im.name}.{ext}"), "wb").write(data)
            n += 1
        QMessageBox.information(self, "Extract images", f"Saved {n} image(s) to {folder}.")

    # fonts
    def _build_fonts(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.font_table = self._table(["Name", "Type", "Encoding", "Embedded", "Pages"])
        self.font_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.font_table)
        note = QLabel(tr("Only embedded fonts can be extracted. Font files are usually subsets and remain subject to the font's licence."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        b1 = QPushButton(tr("Extract selected…"))
        b2 = QPushButton(tr("Extract all embedded…"))
        b1.clicked.connect(lambda: self._extract_fonts(selected=True))
        b2.clicked.connect(lambda: self._extract_fonts(selected=False))
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        self.tabs.addTab(w, tr("Fonts"))
        self.fonts = self.doc.list_fonts()
        self.font_table.setRowCount(len(self.fonts))
        for r, f in enumerate(self.fonts):
            self.font_table.setItem(r, 0, QTableWidgetItem(f.base_font))
            self.font_table.setItem(r, 1, QTableWidgetItem(f.subtype))
            self.font_table.setItem(r, 2, QTableWidgetItem(f.encoding or "–"))
            self.font_table.setItem(r, 3, QTableWidgetItem(f"yes ({f.ext})" if f.embedded else "no"))
            self.font_table.setItem(r, 4, QTableWidgetItem(", ".join(str(p + 1) for p in f.pages[:12]) + ("…" if len(f.pages) > 12 else "")))
        self.tabs.setTabText(1, f"Fonts ({len(self.fonts)})")

    def _extract_fonts(self, selected: bool) -> None:
        rows = sorted({i.row() for i in self.font_table.selectedIndexes()}) if selected else [i for i, f in enumerate(self.fonts) if f.embedded]
        rows = [r for r in rows if self.fonts[r].embedded]
        if not rows:
            QMessageBox.information(self, tr("Extract fonts"), tr("Select one or more embedded fonts first."))
            return
        if len(rows) == 1:
            f = self.fonts[rows[0]]
            name, ext, data = self.doc.extract_font(f.xref)
            path, _ = QFileDialog.getSaveFileName(self, tr("Save font"), f"{name}.{ext}", f"Font (*.{ext})")
            if path:
                open(path, "wb").write(data)
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Choose folder for fonts"))
        if not folder:
            return
        n = 0
        for r in rows:
            try:
                name, ext, data = self.doc.extract_font(self.fonts[r].xref)
            except Exception:
                continue
            open(os.path.join(folder, f"{name}.{ext}"), "wb").write(data)
            n += 1
        QMessageBox.information(self, "Extract fonts", f"Saved {n} font file(s) to {folder}.")

    # attachments
    def _build_attachments(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.att_table = self._table(["File", "Description", "Size", "Modified"])
        self.att_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.att_table)
        row = QHBoxLayout()
        add = QPushButton(tr("Attach file…"))
        add.clicked.connect(self._attach)
        rem = QPushButton(tr("Remove"))
        rem.setProperty("danger", "true")
        rem.clicked.connect(self._remove_attachment)
        ext = QPushButton(tr("Save selected…"))
        ext.clicked.connect(self._extract_attachment)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        row.addWidget(ext)
        lay.addLayout(row)
        self.tabs.addTab(w, tr("Attachments"))
        self._reload_attachments()

    def _reload_attachments(self) -> None:
        self.attachments = self.doc.attachments()
        self.att_table.setRowCount(len(self.attachments))
        for r, a in enumerate(self.attachments):
            self.att_table.setItem(r, 0, QTableWidgetItem(a.filename))
            self.att_table.setItem(r, 1, QTableWidgetItem(a.description))
            self.att_table.setItem(r, 2, QTableWidgetItem(_human_size(a.size)))
            d = pdf_date_to_datetime(a.modified)
            self.att_table.setItem(r, 3, QTableWidgetItem(d.strftime("%Y-%m-%d %H:%M") if d else ""))
        self.tabs.setTabText(2, f"Attachments ({len(self.attachments)})")

    def _attach(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Attach files"))
        for p in paths:
            self.doc.add_attachment(p)
        if paths:
            self._reload_attachments()
            if self.on_change:
                self.on_change()

    def _remove_attachment(self) -> None:
        rows = sorted({i.row() for i in self.att_table.selectedIndexes()})
        if not rows:
            return
        for r in rows:
            self.doc.delete_attachment(self.attachments[r].name)
        self._reload_attachments()
        if self.on_change:
            self.on_change()

    def _extract_attachment(self) -> None:
        rows = sorted({i.row() for i in self.att_table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, tr("Save attachment"), tr("Select an attachment first."))
            return
        if len(rows) == 1:
            a = self.attachments[rows[0]]
            path, _ = QFileDialog.getSaveFileName(self, tr("Save attachment"), a.filename)
            if path:
                open(path, "wb").write(self.doc.extract_attachment(a.name))
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Choose folder"))
        if folder:
            for r in rows:
                a = self.attachments[r]
                open(os.path.join(folder, a.filename), "wb").write(self.doc.extract_attachment(a.name))


# --- Page decorations ---------------------------------------------------------------------

POSITIONS = [
    (N_("Bottom centre"), "bottom-center"), ("Bottom left", "bottom-left"), ("Bottom right", "bottom-right"),
    (N_("Top centre"), "top-center"), ("Top left", "top-left"), ("Top right", "top-right"),
]


class _ScopeMixin:
    def _scope_combo(self, page_count: int, selected: list[int], current: int) -> QComboBox:
        c = QComboBox()
        c.addItem(tr("All pages"), "all")
        if len(selected) > 1:
            c.addItem(f"Selected pages ({len(selected)})", "selected")
        c.addItem(f"Current page ({current + 1})", "current")
        c.addItem(tr("Range…"), "range")
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText(tr("e.g. 2-5, 8"))
        self.range_edit.setVisible(False)
        c.currentIndexChanged.connect(lambda i: self.range_edit.setVisible(c.currentData() == "range"))
        self._page_count, self._selected, self._current = page_count, selected, current
        return c

    def pages(self, combo: QComboBox) -> list[int]:
        from pdfeditor.ui.dialogs import parse_page_ranges

        v = combo.currentData()
        if v == "all":
            return list(range(self._page_count))
        if v == "selected":
            return list(self._selected)
        if v == "current":
            return [self._current]
        return parse_page_ranges(self.range_edit.text(), self._page_count)


class PageNumbersDialog(_Base, _ScopeMixin):
    def __init__(self, page_count: int, selected: list[int], current: int, parent=None):
        super().__init__(tr("Add page numbers"), parent)
        form = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for f in ("{n}", "Page {n}", "Page {n} of {total}", "- {n} -", "{n} / {total}"):
            self.fmt.addItem(f)
        form.addRow(tr("Format"), self.fmt)
        hint = QLabel(tr("{n} = number, {total} = count of numbered pages, {page} = physical page number"))
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        form.addRow("", hint)
        self.start = QSpinBox()
        self.start.setRange(0, 100000)
        self.start.setValue(1)
        form.addRow(tr("Start at"), self.start)
        self.position = QComboBox()
        for label, key in POSITIONS:
            self.position.addItem(tr(label), key)
        form.addRow(tr("Position"), self.position)
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 72)
        self.size.setValue(10)
        self.size.setSuffix(" pt")
        form.addRow(tr("Font size"), self.size)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 300)
        self.margin.setValue(28)
        self.margin.setSuffix(" pt")
        form.addRow(tr("Margin"), self.margin)
        self.scope = self._scope_combo(page_count, selected, current)
        form.addRow(tr("Apply to"), self.scope)
        form.addRow("", self.range_edit)
        self.body.addLayout(form)
        self.add_buttons("Add numbers")


class WatermarkDialog(_Base, _ScopeMixin):
    def __init__(self, page_count: int, selected: list[int], current: int, parent=None):
        super().__init__(tr("Add watermark"), parent)
        form = QFormLayout()
        self.text = QLineEdit("DRAFT")
        form.addRow(tr("Text"), self.text)
        self.size = QDoubleSpinBox()
        self.size.setRange(6, 400)
        self.size.setValue(60)
        self.size.setSuffix(" pt")
        form.addRow(tr("Font size"), self.size)
        self.rotation = QSpinBox()
        self.rotation.setRange(-180, 180)
        self.rotation.setValue(45)
        self.rotation.setSuffix("°")
        form.addRow(tr("Rotation"), self.rotation)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        form.addRow(tr("Opacity"), self.opacity)
        self.color = QComboBox()
        for label, rgb in (("Grey", (0.5, 0.5, 0.5)), ("Red", (0.85, 0.1, 0.1)), ("Blue", (0.1, 0.3, 0.8)), ("Black", (0, 0, 0))):
            self.color.addItem(label, rgb)
        form.addRow(tr("Colour"), self.color)
        self.scope = self._scope_combo(page_count, selected, current)
        form.addRow(tr("Apply to"), self.scope)
        form.addRow("", self.range_edit)
        self.body.addLayout(form)
        self.add_buttons("Add watermark")


LABEL_STYLES = [
    (N_("Decimal (1, 2, 3)"), "D"), ("Roman upper (I, II, III)", "R"), ("Roman lower (i, ii, iii)", "r"),
    (N_("Letters upper (A, B, C)"), "A"), ("Letters lower (a, b, c)", "a"), ("Prefix only (no number)", ""),
]


class PageLabelsDialog(_Base):
    """Edit the page-label ranges (how pages are numbered in viewers)."""

    def __init__(self, page_count: int, rules: list[dict], parent=None):
        super().__init__(tr("Page labels"), parent, 560)
        info = QLabel(tr("Each rule numbers pages from its start page until the next rule. For example a rule "
                      "starting at page 1 with lower-case roman numerals and a second rule starting at page 5 with "
                      "decimal numbers gives i, ii, iii, iv, 1, 2, …"))
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        self.body.addWidget(info)
        self.page_count = page_count
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Start page", "Style", "Prefix", "First number"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.body.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton(tr("Add rule"))
        add.clicked.connect(lambda: self._add_row())
        rem = QPushButton(tr("Remove rule"))
        rem.clicked.connect(self._remove_row)
        clear = QPushButton(tr("Remove all labels"))
        clear.clicked.connect(lambda: self.table.setRowCount(0))
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        row.addWidget(clear)
        self.body.addLayout(row)
        for r in rules:
            self._add_row(r)
        if not rules:
            self._add_row({"startpage": 0, "style": "D", "prefix": "", "firstpagenum": 1})
        self.add_buttons("Apply")

    def _add_row(self, rule: dict | None = None) -> None:
        rule = rule or {"startpage": min(self.page_count - 1, self.table.rowCount()), "style": "D", "prefix": "", "firstpagenum": 1}
        r = self.table.rowCount()
        self.table.insertRow(r)
        start = QSpinBox()
        start.setRange(1, max(1, self.page_count))
        start.setValue(int(rule.get("startpage", 0)) + 1)
        style = QComboBox()
        for label, key in LABEL_STYLES:
            style.addItem(tr(label), key)
        style.setCurrentIndex(max(style.findData(rule.get("style", "D") or ""), 0))
        prefix = QLineEdit(str(rule.get("prefix", "") or ""))
        first = QSpinBox()
        first.setRange(1, 100000)
        first.setValue(int(rule.get("firstpagenum", 1) or 1))
        self.table.setCellWidget(r, 0, start)
        self.table.setCellWidget(r, 1, style)
        self.table.setCellWidget(r, 2, prefix)
        self.table.setCellWidget(r, 3, first)

    def _remove_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True) or ([self.table.rowCount() - 1] if self.table.rowCount() else [])
        for r in rows:
            self.table.removeRow(r)

    def rules(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            out.append({
                "startpage": self.table.cellWidget(r, 0).value() - 1,
                "style": self.table.cellWidget(r, 1).currentData(),
                "prefix": self.table.cellWidget(r, 2).text(),
                "firstpagenum": self.table.cellWidget(r, 3).value(),
            })
        return out


class OcrDialog(_Base, _ScopeMixin):
    def __init__(self, page_count: int, selected: list[int], current: int, languages: list[str], parent=None):
        super().__init__(tr("Recognize text (OCR)"), parent)
        info = QLabel(tr("Adds an invisible, searchable text layer over scanned pages. The page image is not changed. "
                      "Pages that already contain text are skipped unless you choose otherwise."))
        info.setWordWrap(True)
        self.body.addWidget(info)
        form = QFormLayout()
        self.language = QComboBox()
        self.language.setEditable(True)
        for lang in languages:
            self.language.addItem(lang)
        idx = self.language.findText("eng")
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        form.addRow(tr("Language"), self.language)
        hint = QLabel(tr("Combine languages with +, e.g. eng+deu"))
        hint.setProperty("role", "muted")
        form.addRow("", hint)
        self.dpi = QSpinBox()
        self.dpi.setRange(100, 600)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        form.addRow(tr("Resolution"), self.dpi)
        self.skip_text = QCheckBox(tr("Skip pages that already have text"))
        self.skip_text.setChecked(True)
        form.addRow("", self.skip_text)
        self.scope = self._scope_combo(page_count, selected, current)
        form.addRow(tr("Apply to"), self.scope)
        form.addRow("", self.range_edit)
        self.body.addLayout(form)
        self.add_buttons("Recognize")


class ExportImageDialog(_Base):
    def __init__(self, page_count: int, current: int, parent=None):
        super().__init__(tr("Export page as image"), parent)
        form = QFormLayout()
        self.format = QComboBox()
        for label, ext in (("PNG", "png"), ("JPEG", "jpg"), ("SVG (vector)", "svg")):
            self.format.addItem(label, ext)
        form.addRow(tr("Format"), self.format)
        self.dpi = QSpinBox()
        self.dpi.setRange(36, 1200)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" dpi")
        form.addRow(tr("Resolution"), self.dpi)
        self.scope = QComboBox()
        self.scope.addItem(f"Current page ({current + 1})", "current")
        self.scope.addItem(tr("All pages (one file each)"), "all")
        form.addRow(tr("Pages"), self.scope)
        self.annots = QCheckBox(tr("Include annotations and form fields"))
        self.annots.setChecked(True)
        form.addRow("", self.annots)
        self.body.addLayout(form)
        self.format.currentIndexChanged.connect(lambda i: self.dpi.setEnabled(self.format.currentData() != "svg"))
        self.add_buttons("Export…")


class PreferencesDialog(_Base):
    def __init__(self, parent=None):
        super().__init__(tr("Preferences"), parent)
        from PySide6.QtCore import QSettings

        self.settings = QSettings(APP_ID, APP_ID)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem(tr("Follow system"), "system")
        self.theme.addItem(tr("Light"), "light")
        self.theme.addItem(tr("Dark"), "dark")
        if self.settings.contains("ui/dark"):
            self.theme.setCurrentIndex(2 if self.settings.value("ui/dark", False, type=bool) else 1)
        form.addRow(tr("Theme"), self.theme)
        self.units = QComboBox()
        for u in UNITS:
            if u != "px":
                self.units.addItem({"pt": "Points (pt)", "mm": "Millimetres (mm)", "cm": "Centimetres (cm)", "in": "Inches (in)"}[u], u)
        self.units.setCurrentIndex(max(self.units.findData(current_unit()), 0))
        form.addRow(tr("Units"), self.units)
        self.scale_stroke = QCheckBox(tr("Scale stroke width when resizing objects"))
        self.scale_stroke.setChecked(self.settings.value("edit/scaleStroke", True, type=bool))
        form.addRow("", self.scale_stroke)
        self.author = QLineEdit(self.settings.value("user/author", "", type=str))
        self.author.setPlaceholderText(tr("Name shown on comments you add"))
        form.addRow(tr("Your name"), self.author)
        from pdfeditor import i18n

        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("System language"), "system")
        names = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano", "pt": "Português", "nl": "Nederlands"}
        for code in i18n.available_languages():
            self.language_combo.addItem(names.get(code, code), code)
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(self.settings.value("ui/language", "system", type=str)), 0))
        form.addRow(tr("Language"), self.language_combo)
        self.fit_on_open = QComboBox()
        self.fit_on_open.addItem(tr("Fit page"), "page")
        self.fit_on_open.addItem(tr("Fit width"), "width")
        self.fit_on_open.addItem(tr("Actual size"), "100")
        self.fit_on_open.setCurrentIndex(max(self.fit_on_open.findData(self.settings.value("view/fitOnOpen", "page")), 0))
        form.addRow(tr("Zoom when opening"), self.fit_on_open)
        self.grid_size = QDoubleSpinBox()
        self.grid_size.setRange(1, 500)
        self.grid_size.setDecimals(1)
        self.grid_size.setSuffix(" pt")
        self.grid_size.setValue(self.settings.value("view/gridSize", 10.0, type=float))
        form.addRow(tr("Grid spacing"), self.grid_size)
        self.snap_tol = QSpinBox()
        self.snap_tol.setRange(1, 30)
        self.snap_tol.setSuffix(" px")
        self.snap_tol.setValue(int(self.settings.value("view/snapTolerance", 6.0, type=float)))
        form.addRow(tr("Snap distance"), self.snap_tol)
        self.body.addLayout(form)
        self.add_buttons("Save")

    def apply(self) -> dict:
        t = self.theme.currentData()
        if t == "system":
            self.settings.remove("ui/dark")
        else:
            self.settings.setValue("ui/dark", t == "dark")
        set_current_unit(self.units.currentData())
        self.settings.setValue("edit/scaleStroke", self.scale_stroke.isChecked())
        self.settings.setValue("user/author", self.author.text())
        self.settings.setValue("view/fitOnOpen", self.fit_on_open.currentData())
        self.settings.setValue("ui/language", self.language_combo.currentData())
        self.settings.setValue("view/gridSize", float(self.grid_size.value()))
        self.settings.setValue("view/snapTolerance", float(self.snap_tol.value()))
        return {"theme": t, "units": self.units.currentData(), "scale_stroke": self.scale_stroke.isChecked(),
                "language": self.language_combo.currentData()}


class ShortcutsDialog(_Base):
    def __init__(self, actions: list[QAction], parent=None):
        super().__init__(tr("Keyboard shortcuts"), parent, 520)
        self.setMinimumHeight(520)
        tree = QTreeWidget()
        tree.setHeaderLabels([tr("Command"), tr("Shortcut")])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        extra = [
            (N_("Canvas: zoom"), "Ctrl + mouse wheel"), ("Canvas: pan", "Middle mouse drag, or Hand tool"),
            (N_("Canvas: add to selection"), "Shift + click"), ("Canvas: constrain move / square / circle / 45°", "Hold Shift"),
            (N_("Canvas: free resize (ignore aspect)"), "Shift + drag handle"), ("Canvas: nudge selection", "Arrow keys (Shift = 10 pt)"),
            (N_("Canvas: edit text line"), "Double-click text, Enter, or F2"), ("Canvas: edit path nodes", "Double-click a shape"),
            (N_("Pen tool: finish / close"), "Enter or double-click / click first point"), ("Any tool: back to Select", "Esc"),
        ]
        for a in actions:
            if not a.text() or a.shortcut().isEmpty():
                continue
            it = QTreeWidgetItem([a.text().replace("&", "").replace("…", ""), a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)])
            tree.addTopLevelItem(it)
        for name, key in extra:
            tree.addTopLevelItem(QTreeWidgetItem([name, key]))
        self.body.addWidget(tree)
        self.add_buttons("Close", cancel=False)
