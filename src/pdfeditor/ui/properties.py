"""Inspector panel: page info, drawing defaults, selected objects, form fields."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pdfeditor.core.content.model import Color, GObject, PathObject, TextRun, XObjectRef
from pdfeditor.core.document import WIDGET_TYPES, WidgetInfo
from pdfeditor.core.geometry import Matrix
from pdfeditor.ui import theme
from pdfeditor.ui.canvas import DRAW_TOOLS, TOOL_TEXT, PageCanvas

FONT_CHOICES = [
    ("Helvetica", "helv"), ("Helvetica Bold", "hebo"), ("Helvetica Italic", "heit"), ("Helvetica Bold Italic", "hebi"),
    ("Times", "tiro"), ("Times Bold", "tibo"), ("Times Italic", "tiit"), ("Times Bold Italic", "tibi"),
    ("Courier", "cour"), ("Courier Bold", "cobo"), ("Courier Italic", "coit"), ("Courier Bold Italic", "cobi"),
]

FLAG_READONLY = 1
FLAG_REQUIRED = 2
FLAG_MULTILINE = 4096


class ColorButton(QPushButton):
    colorChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color: QColor | None = None
        self.setFixedSize(36, 24)
        self.clicked.connect(self._pick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def color(self) -> QColor | None:
        return self._color

    def set_color(self, color: QColor | None) -> None:
        self._color = color
        t = theme.current()
        if color is None:
            self.setStyleSheet(f"QPushButton {{ background: {t.panel_alt}; border: 1px dashed {t.text_muted}; border-radius: 4px; }}")
            self.setToolTip("No colour / unknown colour space")
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


def _section(title: str) -> tuple[QWidget, QVBoxLayout]:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setProperty("role", "title")
    lay.addWidget(t)
    return box, lay


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
        self.layout_.setSpacing(12)

        self._build_page_section()
        self._build_defaults_section()
        self._build_selection_section()
        self._build_widget_section()
        self.layout_.addStretch()

        canvas.selectionChanged.connect(lambda ids: self.refresh())
        canvas.pageEdited.connect(lambda i: self.refresh())
        canvas.toolChanged.connect(lambda t: self.refresh())
        self.refresh()

    # -- sections -------------------------------------------------------------
    def _build_page_section(self) -> None:
        self.page_box, pl = _section("Page")
        self.page_title = self.page_box.findChild(QLabel)
        self.page_info = QLabel("")
        self.page_info.setProperty("role", "muted")
        self.page_info.setWordWrap(True)
        self.doc_info = QLabel("")
        self.doc_info.setProperty("role", "muted")
        self.doc_info.setWordWrap(True)
        pl.addWidget(self.page_info)
        pl.addWidget(_hline())
        pl.addWidget(_heading("Document"))
        pl.addWidget(self.doc_info)
        hint = QLabel(
            "Click an object to inspect and edit it. Drag to move, use the handles to resize, double-click text "
            "to edit a line, double-click a shape to edit its nodes. Use the drawing tools to add shapes, text and form fields."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        pl.addWidget(_hline())
        pl.addWidget(hint)
        self.layout_.addWidget(self.page_box)

    def _build_defaults_section(self) -> None:
        self.defaults_box, dl = _section("New object style")
        sub = QLabel("Used for shapes, lines and text you create.")
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        dl.addWidget(sub)
        row = QHBoxLayout()
        self.d_fill_check = QCheckBox("Fill")
        self.d_fill_color = ColorButton()
        self.d_stroke_check = QCheckBox("Stroke")
        self.d_stroke_color = ColorButton()
        row.addWidget(self.d_fill_check)
        row.addWidget(self.d_fill_color)
        row.addStretch()
        row.addWidget(self.d_stroke_check)
        row.addWidget(self.d_stroke_color)
        dl.addLayout(row)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        self.d_width = _spin(0, 1e3, 2, 0.5, " pt")
        form.addRow("Stroke width", self.d_width)
        self.d_font = QComboBox()
        for label, name in FONT_CHOICES:
            self.d_font.addItem(label, name)
        form.addRow("Font", self.d_font)
        self.d_size = _spin(1, 500, 1, 1, " pt")
        form.addRow("Text size", self.d_size)
        self.d_text_color = ColorButton()
        form.addRow("Text colour", self.d_text_color)
        dl.addLayout(form)
        self.layout_.addWidget(self.defaults_box)
        self.d_fill_check.toggled.connect(self._defaults_changed)
        self.d_stroke_check.toggled.connect(self._defaults_changed)
        self.d_fill_color.colorChanged.connect(lambda c: (self.d_fill_check.setChecked(True), self._defaults_changed()))
        self.d_stroke_color.colorChanged.connect(lambda c: (self.d_stroke_check.setChecked(True), self._defaults_changed()))
        self.d_width.editingFinished.connect(self._defaults_changed)
        self.d_font.currentIndexChanged.connect(self._defaults_changed)
        self.d_size.editingFinished.connect(self._defaults_changed)
        self.d_text_color.colorChanged.connect(lambda c: self._defaults_changed())
        self._load_defaults()

    def _build_selection_section(self) -> None:
        self.sel_box, sl = _section("Selection")
        self.sel_title = self.sel_box.findChild(QLabel)
        self.sel_sub = QLabel("")
        self.sel_sub.setProperty("role", "muted")
        self.sel_sub.setWordWrap(True)
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
        for w in (self.x, self.y, self.w, self.h):
            w.editingFinished.connect(self._apply_geometry)
        self.rot.editingFinished.connect(self._apply_rotation)

        self.style_box = QWidget()
        st = QVBoxLayout(self.style_box)
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(6)
        st.addWidget(_heading("Fill & Stroke"))
        row = QHBoxLayout()
        self.fill_check = QCheckBox("Fill")
        self.fill_color = ColorButton()
        self.stroke_check = QCheckBox("Stroke")
        self.stroke_color = ColorButton()
        row.addWidget(self.fill_check)
        row.addWidget(self.fill_color)
        row.addStretch()
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

        self.text_box = QWidget()
        tl = QVBoxLayout(self.text_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tl.addWidget(_heading("Text"))
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text content (Enter applies)")
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

    def _build_widget_section(self) -> None:
        self.widget_box, wl = _section("Form field")
        self.widget_title = self.widget_box.findChild(QLabel)
        self.w_sub = QLabel("")
        self.w_sub.setProperty("role", "muted")
        self.w_sub.setWordWrap(True)
        wl.addWidget(self.w_sub)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        self.w_name = QLineEdit()
        form.addRow("Name", self.w_name)
        self.w_value = QLineEdit()
        self.w_value_row = form.rowCount()
        form.addRow("Value", self.w_value)
        self.w_checked = QCheckBox("Checked")
        form.addRow("", self.w_checked)
        self.w_choice = QComboBox()
        form.addRow("Selected", self.w_choice)
        self.w_choices = QPlainTextEdit()
        self.w_choices.setPlaceholderText("One option per line")
        self.w_choices.setMaximumHeight(90)
        form.addRow("Options", self.w_choices)
        self.w_caption = QLineEdit()
        form.addRow("Caption", self.w_caption)
        self.w_font_size = _spin(0, 200, 1, 1, " pt")
        form.addRow("Font size", self.w_font_size)
        self.w_text_color = ColorButton()
        form.addRow("Text colour", self.w_text_color)
        self.w_fill_color = ColorButton()
        form.addRow("Background", self.w_fill_color)
        self.w_border_color = ColorButton()
        form.addRow("Border", self.w_border_color)
        self.w_border_width = _spin(0, 20, 1, 0.5, " pt")
        form.addRow("Border width", self.w_border_width)
        wl.addLayout(form)
        flags = QHBoxLayout()
        self.w_readonly = QCheckBox("Read-only")
        self.w_required = QCheckBox("Required")
        self.w_multiline = QCheckBox("Multiline")
        flags.addWidget(self.w_readonly)
        flags.addWidget(self.w_required)
        flags.addWidget(self.w_multiline)
        wl.addLayout(flags)
        self.w_form_labels = {}
        for i in range(form.rowCount()):
            lbl = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            fld = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if fld is not None and fld.widget() is not None:
                self.w_form_labels[fld.widget()] = lbl.widget() if lbl is not None else None
        wl.addWidget(_hline())
        btns = QHBoxLayout()
        self.w_apply = QPushButton("Apply")
        self.w_apply.setProperty("primary", "true")
        self.w_delete = QPushButton("Delete")
        self.w_delete.setProperty("danger", "true")
        btns.addStretch()
        btns.addWidget(self.w_delete)
        btns.addWidget(self.w_apply)
        wl.addLayout(btns)
        self.layout_.addWidget(self.widget_box)
        self.w_apply.clicked.connect(self._apply_widget)
        self.w_delete.clicked.connect(self.canvas.delete_selection)
        self.w_value.returnPressed.connect(self._apply_widget)
        self.w_name.returnPressed.connect(self._apply_widget)
        self.w_checked.toggled.connect(lambda on: None if self._updating else self._apply_widget())
        self.w_choice.activated.connect(lambda i: None if self._updating else self._apply_widget())

    # -- refresh --------------------------------------------------------------
    def refresh(self) -> None:
        self._updating = True
        try:
            doc = self.canvas.doc
            objs = self.canvas.selected_objects()
            widgets = self.canvas.selected_widgets()
            tool = self.canvas.tool
            show_defaults = doc is not None and (tool in DRAW_TOOLS or tool == TOOL_TEXT)
            self.defaults_box.setVisible(show_defaults and not objs and not widgets)
            self.widget_box.setVisible(bool(widgets))
            self.sel_box.setVisible(bool(objs) and not widgets)
            self.page_box.setVisible(not objs and not widgets and not show_defaults)
            if doc is None:
                self.page_title.setText("No document")
                self.page_info.setText("Open a PDF to get started.")
                self.doc_info.setText("")
                return
            if widgets:
                self._refresh_widget(widgets)
                return
            if not objs:
                i = self.canvas.page_index
                r = doc.page_rect(i)
                rot = doc.page_rotation(i)
                self.page_title.setText(f"Page {i + 1} of {doc.page_count}")
                self.page_info.setText(
                    f"{r.width:.1f} × {r.height:.1f} pt  ({r.width / 72 * 25.4:.0f} × {r.height / 72 * 25.4:.0f} mm)"
                    + (f"\nRotation {rot}°" if rot else "")
                )
                n_obj = len(doc.content(i).selectable_objects())
                n_w = len(doc.widgets(i))
                self.doc_info.setText(
                    f"{doc.title}\n{doc.page_count} page(s) · {n_obj} editable object(s)"
                    + (f" · {n_w} form field(s)" if n_w else "") + " on this page"
                )
                return
            if len(objs) == 1:
                self.sel_title.setText(_kind_label(objs[0]))
                self.sel_sub.setText(_describe(objs[0]))
            else:
                self.sel_title.setText(f"{len(objs)} objects")
                self.sel_sub.setText(", ".join(sorted({_kind_label(o) for o in objs})))
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
                ids = [o.id for o in texts]
                self.text_edit.setText(self.canvas._line_text(ids) if len(texts) >= 1 else "")
                fi = t.font_info
                self.font_label.setText(fi.display_name if fi else t.font)
                self.font_size.setValue(t.state.font_size)
                self.text_color.set_color(_to_qcolor(t.state.fill_color))
                notes = []
                if len(texts) > 1:
                    notes.append(f"{len(texts)} runs selected; applying text merges them into one.")
                if fi is not None and fi.is_subset:
                    notes.append("Subset font: characters not already used in the document fall back to a built-in font.")
                if t.invisible:
                    notes.append("Invisible text (e.g. OCR layer).")
                self.text_note.setText(" ".join(notes))
            others = [o for o in objs if o.kind in ("image", "form", "inline_image", "shading")]
            self.other_info.setVisible(bool(others) and not paths and not texts)
            if others:
                self.other_info.setText("\n".join(_describe(o) for o in others[:5]))
        finally:
            self._updating = False

    def _refresh_widget(self, widgets: list[WidgetInfo]) -> None:
        w = widgets[0]
        multi = len(widgets) > 1
        self.widget_title.setText(w.type_name if not multi else f"{len(widgets)} form fields")
        self.w_sub.setText(f"{w.rect.width:.0f} × {w.rect.height:.0f} pt" + (" · editing the first one" if multi else ""))
        self.w_name.setText(w.field_name)
        ft = w.field_type
        is_text = ft == 7
        is_check = ft in (2, 5)
        is_choice = ft in (3, 4)
        is_button = ft == 1
        self._show_row(self.w_value, is_text)
        self._show_row(self.w_checked, is_check)
        self._show_row(self.w_choice, is_choice)
        self._show_row(self.w_choices, is_choice)
        self._show_row(self.w_caption, is_button)
        self._show_row(self.w_font_size, not is_check)
        self._show_row(self.w_text_color, not is_check)
        self.w_multiline.setVisible(is_text)
        if is_text:
            self.w_value.setText(str(w.value or ""))
        if is_check:
            self.w_checked.setChecked(bool(w.value) and str(w.value) not in ("Off", "False", ""))
        if is_choice:
            self.w_choices.setPlainText("\n".join(w.choices))
            self.w_choice.clear()
            self.w_choice.addItems(w.choices)
            val = str(w.value or "")
            idx = self.w_choice.findText(val)
            self.w_choice.setCurrentIndex(max(idx, 0))
        if is_button:
            self.w_caption.setText(w.label or "")
        self.w_font_size.setValue(w.font_size)
        self.w_text_color.set_color(_tuple_to_qcolor(w.text_color))
        self.w_fill_color.set_color(_tuple_to_qcolor(w.fill_color))
        self.w_border_color.set_color(_tuple_to_qcolor(w.border_color))
        self.w_border_width.setValue(w.border_width)
        self.w_readonly.setChecked(bool(w.flags & FLAG_READONLY))
        self.w_required.setChecked(bool(w.flags & FLAG_REQUIRED))
        self.w_multiline.setChecked(bool(w.flags & FLAG_MULTILINE))

    def _show_row(self, widget: QWidget, on: bool) -> None:
        widget.setVisible(on)
        lbl = self.w_form_labels.get(widget)
        if lbl is not None:
            lbl.setVisible(on)

    # -- apply -----------------------------------------------------------------
    def _apply_widget(self) -> None:
        if self._updating:
            return
        widgets = self.canvas.selected_widgets()
        doc = self.canvas.doc
        if not widgets or doc is None:
            return
        w = widgets[0]
        props: dict = {}
        if self.w_name.text().strip() and self.w_name.text().strip() != w.field_name:
            props["field_name"] = self.w_name.text().strip()
        ft = w.field_type
        if ft == 7:
            props["value"] = self.w_value.text()
        elif ft in (2, 5):
            props["value"] = bool(self.w_checked.isChecked())
        elif ft in (3, 4):
            choices = [c.strip() for c in self.w_choices.toPlainText().splitlines() if c.strip()]
            if choices and choices != w.choices:
                props["choices"] = choices
            sel = self.w_choice.currentText()
            if sel:
                props["value"] = sel
        elif ft == 1:
            props["label"] = self.w_caption.text()
        if ft not in (2, 5):
            props["font_size"] = self.w_font_size.value()
            c = self.w_text_color.color()
            if c is not None:
                props["text_color"] = (c.redF(), c.greenF(), c.blueF())
        c = self.w_fill_color.color()
        if c is not None:
            props["fill_color"] = (c.redF(), c.greenF(), c.blueF())
        c = self.w_border_color.color()
        if c is not None:
            props["border_color"] = (c.redF(), c.greenF(), c.blueF())
        props["border_width"] = self.w_border_width.value()
        flags = w.flags & ~(FLAG_READONLY | FLAG_REQUIRED | FLAG_MULTILINE)
        if self.w_readonly.isChecked():
            flags |= FLAG_READONLY
        if self.w_required.isChecked():
            flags |= FLAG_REQUIRED
        if ft == 7 and self.w_multiline.isChecked():
            flags |= FLAG_MULTILINE
        props["flags"] = flags
        doc.update_widget(self.canvas.page_index, w.xref, **props)
        self.canvas.pageEdited.emit(self.canvas.page_index)

    def _load_defaults(self) -> None:
        s = self.canvas.draw_style
        self._updating = True
        try:
            self.d_fill_check.setChecked(s.fill is not None)
            self.d_fill_color.set_color(_to_qcolor(s.fill) if s.fill else QColor("#d9e6ff"))
            self.d_stroke_check.setChecked(s.stroke is not None)
            self.d_stroke_color.set_color(_to_qcolor(s.stroke) if s.stroke else QColor("#2659cc"))
            self.d_width.setValue(s.line_width)
            idx = self.d_font.findData(s.font)
            self.d_font.setCurrentIndex(max(idx, 0))
            self.d_size.setValue(s.font_size)
            self.d_text_color.set_color(_to_qcolor(s.text_color))
        finally:
            self._updating = False

    def _defaults_changed(self, *args) -> None:
        if self._updating:
            return
        s = self.canvas.draw_style
        fc = self.d_fill_color.color()
        sc = self.d_stroke_color.color()
        s.fill = _to_color(fc) if self.d_fill_check.isChecked() and fc is not None else None
        s.stroke = _to_color(sc) if self.d_stroke_check.isChecked() and sc is not None else None
        s.line_width = self.d_width.value()
        s.font = self.d_font.currentData() or "helv"
        s.font_size = self.d_size.value()
        tc = self.d_text_color.color()
        if tc is not None:
            s.text_color = _to_color(tc)

    def _apply_geometry(self) -> None:
        if self._updating or not self.canvas.has_selection:
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
        if self._updating or not self.canvas.selection:
            return
        ids = [o.id for o in self.canvas.selected_objects() if isinstance(o, TextRun)]
        if ids:
            self.canvas.set_line_text(ids, self.text_edit.text())


def _to_qcolor(c: Color | None) -> QColor | None:
    if c is None:
        return None
    rgb = c.to_rgb()
    if rgb is None:
        return None
    return QColor.fromRgbF(*rgb)


def _tuple_to_qcolor(t: tuple | None) -> QColor | None:
    if t is None:
        return None
    try:
        return QColor.fromRgbF(*[max(0.0, min(1.0, float(v))) for v in t[:3]])
    except Exception:
        return None


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
