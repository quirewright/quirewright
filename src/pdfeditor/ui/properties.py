"""Inspector panel: shows page info or properties of the selected objects."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdfeditor.core.content.model import Color, GObject, PathObject, TextRun, XObjectRef
from pdfeditor.core.geometry import Matrix
from pdfeditor.ui import theme
from pdfeditor.ui.canvas import PageCanvas


class ColorButton(QPushButton):
    colorChanged = Signal(object)  # QColor or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color: QColor | None = None
        self.setFixedSize(36, 24)
        self.clicked.connect(self._pick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_color(self, color: QColor | None) -> None:
        self._color = color
        t = theme.current()
        if color is None:
            self.setStyleSheet(f"QPushButton {{ background: {t.panel_alt}; border: 1px dashed {t.text_muted}; border-radius: 4px; }}")
            self.setToolTip("Unknown colour space")
        else:
            self.setStyleSheet(f"QPushButton {{ background: {color.name()}; border: 1px solid {t.border}; border-radius: 4px; }}")
            self.setToolTip(color.name())

    def _pick(self) -> None:
        start = self._color or QColor("#000000")
        c = QColorDialog.getColor(start, self, "Choose colour")
        if c.isValid():
            self.set_color(c)
            self.colorChanged.emit(c)


def _heading(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "heading")
    return lbl


def _hline() -> QFrame:
    f = QFrame()
    f.setProperty("role", "hline")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def _spin(minimum: float, maximum: float, decimals: int = 2, step: float = 1.0, suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    s.setAlignment(Qt.AlignmentFlag.AlignRight)
    return s


class PropertiesPanel(QScrollArea):
    def __init__(self, canvas: PageCanvas, parent: QWidget | None = None):
        super().__init__(parent)
        self.canvas = canvas
        self._updating = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.setWidget(body)
        self.layout_ = QVBoxLayout(body)
        self.layout_.setContentsMargins(14, 12, 14, 12)
        self.layout_.setSpacing(10)

        # -- page section
        self.page_title = QLabel("Page")
        self.page_title.setProperty("role", "title")
        self.page_info = QLabel("")
        self.page_info.setProperty("role", "muted")
        self.page_info.setWordWrap(True)
        self.doc_info = QLabel("")
        self.doc_info.setProperty("role", "muted")
        self.doc_info.setWordWrap(True)
        self.page_box = QWidget()
        pl = QVBoxLayout(self.page_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        pl.addWidget(self.page_title)
        pl.addWidget(self.page_info)
        pl.addWidget(_hline())
        pl.addWidget(_heading("Document"))
        pl.addWidget(self.doc_info)
        hint = QLabel("Click an object on the page to inspect and edit it. Drag to move, use the handles to resize, "
                      "double-click text to edit it, double-click a shape to edit its nodes.")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        pl.addWidget(_hline())
        pl.addWidget(hint)
        self.layout_.addWidget(self.page_box)

        # -- selection section
        self.sel_box = QWidget()
        sl = QVBoxLayout(self.sel_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        self.sel_title = QLabel("Selection")
        self.sel_title.setProperty("role", "title")
        self.sel_sub = QLabel("")
        self.sel_sub.setProperty("role", "muted")
        self.sel_sub.setWordWrap(True)
        sl.addWidget(self.sel_title)
        sl.addWidget(self.sel_sub)

        sl.addWidget(_heading("Geometry"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.x = _spin(-1e5, 1e5, 2, 1, " pt")
        self.y = _spin(-1e5, 1e5, 2, 1, " pt")
        self.w = _spin(0.01, 1e5, 2, 1, " pt")
        self.h = _spin(0.01, 1e5, 2, 1, " pt")
        self.rot = _spin(-360, 360, 1, 5, "°")
        for i, (lbl, w) in enumerate((("X", self.x), ("Y", self.y), ("W", self.w), ("H", self.h))):
            grid.addWidget(QLabel(lbl), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        grid.addWidget(QLabel("Rotate"), 2, 0)
        grid.addWidget(self.rot, 2, 1)
        self.lock = QCheckBox("Keep aspect")
        self.lock.setChecked(True)
        grid.addWidget(self.lock, 2, 2, 1, 2)
        sl.addLayout(grid)
        self.x.editingFinished.connect(self._apply_geometry)
        self.y.editingFinished.connect(self._apply_geometry)
        self.w.editingFinished.connect(self._apply_geometry)
        self.h.editingFinished.connect(self._apply_geometry)
        self.rot.editingFinished.connect(self._apply_rotation)

        # path style
        self.style_box = QWidget()
        st = QVBoxLayout(self.style_box)
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(6)
        st.addWidget(_heading("Fill & Stroke"))
        row = QHBoxLayout()
        self.fill_check = QCheckBox("Fill")
        self.fill_color = ColorButton()
        row.addWidget(self.fill_check)
        row.addWidget(self.fill_color)
        row.addStretch()
        self.stroke_check = QCheckBox("Stroke")
        self.stroke_color = ColorButton()
        row.addWidget(self.stroke_check)
        row.addWidget(self.stroke_color)
        st.addLayout(row)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        self.width = _spin(0, 1e4, 2, 0.5, " pt")
        form.addRow("Stroke width", self.width)
        st.addLayout(form)
        sl.addWidget(self.style_box)
        self.fill_check.toggled.connect(lambda on: self._style(fill=on))
        self.stroke_check.toggled.connect(lambda on: self._style(stroke=on))
        self.fill_color.colorChanged.connect(lambda c: self._style(fill_color=_to_color(c), fill=True))
        self.stroke_color.colorChanged.connect(lambda c: self._style(stroke_color=_to_color(c), stroke=True))
        self.width.editingFinished.connect(lambda: self._style(line_width=self.width.value()))

        # text
        self.text_box = QWidget()
        tl = QVBoxLayout(self.text_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tl.addWidget(_heading("Text"))
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text content")
        tl.addWidget(self.text_edit)
        tform = QFormLayout()
        tform.setContentsMargins(0, 0, 0, 0)
        tform.setHorizontalSpacing(8)
        self.font_label = QLabel("")
        self.font_label.setProperty("role", "muted")
        self.font_size = _spin(0.1, 1000, 2, 1, " pt")
        self.text_color = ColorButton()
        tform.addRow("Font", self.font_label)
        tform.addRow("Size", self.font_size)
        tform.addRow("Colour", self.text_color)
        tl.addLayout(tform)
        self.text_note = QLabel("")
        self.text_note.setProperty("role", "muted")
        self.text_note.setWordWrap(True)
        tl.addWidget(self.text_note)
        sl.addWidget(self.text_box)
        self.text_edit.returnPressed.connect(self._apply_text)
        self.font_size.editingFinished.connect(lambda: self.canvas.set_text_size(self.font_size.value()))
        self.text_color.colorChanged.connect(lambda c: self.canvas.set_selection_style(fill_color=_to_color(c)))

        # image / other info
        self.other_info = QLabel("")
        self.other_info.setProperty("role", "muted")
        self.other_info.setWordWrap(True)
        sl.addWidget(self.other_info)

        sl.addWidget(_hline())
        btns = QHBoxLayout()
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("danger", "true")
        self.delete_btn.clicked.connect(self.canvas.delete_selection)
        btns.addStretch()
        btns.addWidget(self.delete_btn)
        sl.addLayout(btns)
        self.layout_.addWidget(self.sel_box)
        self.layout_.addStretch()

        canvas.selectionChanged.connect(lambda ids: self.refresh())
        canvas.pageEdited.connect(lambda i: self.refresh())
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._updating = True
        try:
            doc = self.canvas.doc
            objs = self.canvas.selected_objects()
            if doc is None:
                self.page_box.setVisible(True)
                self.sel_box.setVisible(False)
                self.page_title.setText("No document")
                self.page_info.setText("Open a PDF to get started.")
                self.doc_info.setText("")
                return
            if not objs:
                self.page_box.setVisible(True)
                self.sel_box.setVisible(False)
                i = self.canvas.page_index
                r = doc.page_rect(i)
                rot = doc.page_rotation(i)
                self.page_title.setText(f"Page {i + 1} of {doc.page_count}")
                self.page_info.setText(
                    f"{r.width:.1f} × {r.height:.1f} pt  ({r.width / 72 * 25.4:.0f} × {r.height / 72 * 25.4:.0f} mm)"
                    + (f"\nRotation {rot}°" if rot else "")
                )
                n_obj = len(doc.content(i).selectable_objects())
                self.doc_info.setText(f"{doc.title}\n{doc.page_count} page(s) · {n_obj} editable object(s) on this page")
                return
            self.page_box.setVisible(False)
            self.sel_box.setVisible(True)
            kinds = {o.kind for o in objs}
            if len(objs) == 1:
                self.sel_title.setText(_kind_label(objs[0]))
                self.sel_sub.setText(_describe(objs[0]))
            else:
                self.sel_title.setText(f"{len(objs)} objects")
                self.sel_sub.setText(", ".join(sorted(_kind_label(o) for o in objs)))
            rect = self.canvas._selection_rect()
            self.x.setValue(rect.x())
            self.y.setValue(rect.y())
            self.w.setValue(rect.width())
            self.h.setValue(rect.height())
            self.rot.setValue(0)
            paths = [o for o in objs if isinstance(o, PathObject)]
            texts = [o for o in objs if isinstance(o, TextRun)]
            self.style_box.setVisible(bool(paths))
            if paths:
                p = paths[0]
                self.fill_check.setChecked(p.fill)
                self.stroke_check.setChecked(p.stroke)
                self.fill_color.set_color(_to_qcolor(p.state.fill_color))
                self.stroke_color.set_color(_to_qcolor(p.state.stroke_color))
                self.width.setValue(p.state.line_width)
            self.text_box.setVisible(bool(texts) and not paths)
            if texts:
                t = texts[0]
                self.text_edit.setText(t.text if len(texts) == 1 else "")
                self.text_edit.setEnabled(len(texts) == 1)
                fi = t.font_info
                self.font_label.setText(fi.display_name if fi else t.font)
                self.font_size.setValue(t.state.font_size)
                self.text_color.set_color(_to_qcolor(t.state.fill_color))
                notes = []
                if fi is not None and fi.is_subset:
                    notes.append("Subset font: only characters already used in the document can be typed; others fall back to Helvetica.")
                if t.invisible:
                    notes.append("Invisible text (e.g. OCR layer).")
                self.text_note.setText(" ".join(notes))
            others = [o for o in objs if o.kind in ("image", "form", "inline_image", "shading")]
            self.other_info.setVisible(bool(others) and not paths and not texts)
            if others:
                self.other_info.setText("\n".join(_describe(o) for o in others[:5]))
        finally:
            self._updating = False

    # ------------------------------------------------------------------
    def _apply_geometry(self) -> None:
        if self._updating or not self.canvas.selection:
            return
        rect = self.canvas._selection_rect()
        if rect.isNull():
            return
        nx, ny, nw, nh = self.x.value(), self.y.value(), self.w.value(), self.h.value()
        sx = nw / rect.width() if rect.width() > 1e-9 else 1.0
        sy = nh / rect.height() if rect.height() > 1e-9 else 1.0
        if self.lock.isChecked() and (abs(sx - 1) > 1e-9) != (abs(sy - 1) > 1e-9):
            s = sx if abs(sx - 1) > 1e-9 else sy
            sx = sy = s
        m = Matrix.translation(-rect.x(), -rect.y()) * Matrix.scale(sx, sy) * Matrix.translation(nx, ny)
        if m.is_identity(1e-6):
            return
        self.canvas.transform_selection(m, "Set geometry")

    def _apply_rotation(self) -> None:
        if self._updating or not self.canvas.selection:
            return
        deg = self.rot.value()
        if abs(deg) < 1e-9:
            return
        rect = self.canvas._selection_rect()
        c = rect.center()
        m = Matrix.translation(-c.x(), -c.y()) * Matrix.rotation(deg) * Matrix.translation(c.x(), c.y())
        self.canvas.transform_selection(m, "Rotate")
        self.rot.setValue(0)

    def _style(self, **kwargs) -> None:
        if self._updating:
            return
        self.canvas.set_selection_style(**kwargs)

    def _apply_text(self) -> None:
        if self._updating or len(self.canvas.selection) != 1:
            return
        self.canvas.set_text(self.canvas.selection[0], self.text_edit.text())


def _to_qcolor(c: Color) -> QColor | None:
    rgb = c.to_rgb()
    if rgb is None:
        return None
    return QColor.fromRgbF(*rgb)


def _to_color(c: QColor) -> Color:
    return Color("DeviceRGB", (round(c.redF(), 4), round(c.greenF(), 4), round(c.blueF(), 4)))


def _kind_label(o: GObject) -> str:
    return {
        "path": "Path", "text": "Text", "image": "Image", "form": "Form XObject",
        "inline_image": "Inline image", "shading": "Shading",
    }.get(o.kind, o.kind)


def _describe(o: GObject) -> str:
    if isinstance(o, PathObject):
        n = sum(len(sp) for sp in o.subpaths)
        parts = []
        if o.fill:
            parts.append("filled")
        if o.stroke:
            parts.append("stroked")
        return f"{len(o.subpaths)} subpath(s), {n} segment(s), {' and '.join(parts) or 'invisible'}"
    if isinstance(o, TextRun):
        fi = o.font_info
        return f"“{o.text[:60]}” · {fi.display_name if fi else o.font} {o.state.font_size:g} pt"
    if isinstance(o, XObjectRef):
        return f"/{o.name} ({o.subtype})"
    if o.kind == "inline_image":
        return "Inline image"
    return o.kind
