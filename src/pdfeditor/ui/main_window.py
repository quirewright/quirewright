"""Main application window."""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QToolButton,
    QWidget,
    QSizePolicy,
)

from pdfeditor import APP_NAME, APP_ID
from pdfeditor.core.document import Document
from pdfeditor.ui import theme
from pdfeditor.ui.canvas import (
    TOOL_ELLIPSE,
    TOOL_FIELD,
    TOOL_HAND,
    TOOL_LINE,
    TOOL_NODE,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_SELECT,
    TOOL_TEXT,
    PageCanvas,
)
from pdfeditor.ui.dialogs import (
    AboutDialog,
    BlankPageDialog,
    CropDialog,
    ExtractPagesDialog,
    InsertPagesDialog,
    PasswordDialog,
    SplitDialog,
    parse_page_ranges,
)
from pdfeditor.ui.properties import PropertiesPanel
from pdfeditor.ui.thumbnails import PagesPanel

ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_ID, APP_ID)
        self.doc: Document | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 880)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)

        self.canvas = PageCanvas()
        self.setCentralWidget(self.canvas)
        self.pages = PagesPanel()
        self.properties = PropertiesPanel(self.canvas)

        self.pages_dock = QDockWidget("Pages", self)
        self.pages_dock.setObjectName("pagesDock")
        self.pages_dock.setWidget(self.pages)
        self.pages_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.pages_dock)
        self.props_dock = QDockWidget("Inspector", self)
        self.props_dock.setObjectName("inspectorDock")
        self.props_dock.setWidget(self.properties)
        self.props_dock.setMinimumWidth(270)
        self.props_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._connect()
        self._update_actions()
        self._restore_state()

    # -- construction ------------------------------------------------------
    def _act(self, text: str, icon: str | None = None, shortcut=None, slot=None, checkable: bool = False, tip: str | None = None) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(theme.icon(icon))
            a.setProperty("iconName", icon)
        if shortcut is not None:
            a.setShortcut(shortcut)
        if slot is not None:
            a.triggered.connect(slot)
        a.setCheckable(checkable)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        return a

    def _build_actions(self) -> None:
        S = QKeySequence
        self.act_new = self._act("&New", "new", S.StandardKey.New, self.new_document, tip="Create a new document with one blank page")
        self.act_open = self._act("&Open…", "open", S.StandardKey.Open, self.open_dialog, tip="Open a PDF")
        self.act_save = self._act("&Save", "save", S.StandardKey.Save, self.save, tip="Save the document")
        self.act_save_as = self._act("Save &As…", None, S.StandardKey.SaveAs, self.save_as)
        self.act_close = self._act("&Close", None, S.StandardKey.Close, self.close_document)
        self.act_quit = self._act("&Quit", None, S.StandardKey.Quit, self.close)
        self.act_insert_file = self._act("&Insert Pages from File…", "insert", "Ctrl+Shift+I", self.insert_from_file)
        self.act_extract = self._act("&Extract Pages…", "extract", "Ctrl+Shift+E", self.extract_pages)
        self.act_split = self._act("S&plit Document…", "split", None, self.split_document)

        self.act_undo = self._act("&Undo", "undo", S.StandardKey.Undo, self.undo)
        self.act_redo = self._act("&Redo", "redo", S.StandardKey.Redo, self.redo)
        self.act_delete = self._act("&Delete", "trash", None, self.canvas.delete_selection, tip="Delete selected objects")
        self.act_select_all = self._act("Select &All", None, S.StandardKey.SelectAll, self.canvas.select_all)
        self.act_deselect = self._act("D&eselect", None, "Ctrl+Shift+A", self.canvas.clear_selection)
        self.act_edit_text = self._act("Edit &Text", "edit", "F2", self.edit_selected_text)
        self.act_scale_stroke = self._act("Scale Stroke &Width with Objects", None, None, self._toggle_scale_stroke, checkable=True)
        self.act_scale_stroke.setChecked(True)

        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.act_tool_select = self._act("Select", "select", "S", lambda: self.canvas.set_tool(TOOL_SELECT), True, "Select and transform objects (S)")
        self.act_tool_node = self._act("Nodes", "node", "N", lambda: self.canvas.set_tool(TOOL_NODE), True, "Edit path nodes (N)")
        self.act_tool_text = self._act("Text", "text", "T", lambda: self.canvas.set_tool(TOOL_TEXT), True, "Edit text (T)")
        self.act_tool_hand = self._act("Pan", "hand", "H", lambda: self.canvas.set_tool(TOOL_HAND), True, "Pan the page (H)")
        self.act_tool_rect = self._act("Rectangle", "rect", "R", lambda: self.canvas.set_tool(TOOL_RECT), True, "Draw a rectangle (R)")
        self.act_tool_ellipse = self._act("Ellipse", "ellipse", "E", lambda: self.canvas.set_tool(TOOL_ELLIPSE), True, "Draw an ellipse (E)")
        self.act_tool_line = self._act("Line", "line", "L", lambda: self.canvas.set_tool(TOOL_LINE), True, "Draw a straight line (L)")
        self.act_tool_pen = self._act("Pen", "pen", "P", lambda: self.canvas.set_tool(TOOL_PEN), True, "Draw a polyline: click points, double-click or Enter to finish (P)")
        self.field_actions: list[QAction] = []
        self.field_types = [
            (7, "Text field", "field-text"), (2, "Checkbox", "field-check"), (5, "Radio button", "field-radio"),
            (3, "Dropdown", "field-combo"), (4, "List box", "field-list"), (1, "Push button", "field-button"),
        ]
        for ftype, label, icon_name in self.field_types:
            a = self._act(label, icon_name, None, lambda checked=False, t=ftype: self.canvas.set_tool(f"{TOOL_FIELD}:{t}"), True, f"Drag on the page to add a {label.lower()}")
            a.setProperty("fieldType", ftype)
            self.field_actions.append(a)
        self.act_tool_field = self._act("Form Field", "form", "F", lambda: self.canvas.set_tool(f"{TOOL_FIELD}:{self._last_field_type}"), True, "Add form fields (F)")
        self._last_field_type = 7
        for a in (self.act_tool_select, self.act_tool_node, self.act_tool_text, self.act_tool_hand,
                  self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen, self.act_tool_field, *self.field_actions):
            self.tool_group.addAction(a)
        self.act_tool_select.setChecked(True)
        self.act_insert_image = self._act("Insert &Image…", "image", "Ctrl+Shift+M", self.insert_image, tip="Place an image on the page")

        self.act_zoom_in = self._act("Zoom &In", "zoom-in", S.StandardKey.ZoomIn, self.canvas.zoom_in)
        self.act_zoom_out = self._act("Zoom &Out", "zoom-out", S.StandardKey.ZoomOut, self.canvas.zoom_out)
        self.act_zoom_fit = self._act("&Fit Page", "zoom-fit", "Ctrl+0", self.canvas.zoom_fit, tip="Fit the whole page")
        self.act_zoom_width = self._act("Fit &Width", "zoom-width", "Ctrl+2", self.canvas.zoom_width, tip="Fit page width")
        self.act_zoom_100 = self._act("&Actual Size", None, "Ctrl+1", self.canvas.zoom_actual)
        self.act_prev = self._act("&Previous Page", "chevron-left", "PgUp", lambda: self.go_to_page(self.canvas.page_index - 1))
        self.act_next = self._act("&Next Page", "chevron-right", "PgDown", lambda: self.go_to_page(self.canvas.page_index + 1))
        self.act_first = self._act("&First Page", None, "Ctrl+Home", lambda: self.go_to_page(0))
        self.act_last = self._act("&Last Page", None, "Ctrl+End", lambda: self.go_to_page(10**9))
        self.act_dark = self._act("&Dark Mode", "moon", None, self.toggle_dark, checkable=True)
        self.act_dark.setChecked(theme.current().dark)
        self.act_show_pages = self.pages_dock.toggleViewAction()
        self.act_show_pages.setText("Show &Pages Panel")
        self.act_show_pages.setIcon(theme.icon("pages"))
        self.act_show_props = self.props_dock.toggleViewAction()
        self.act_show_props.setText("Show &Inspector")
        self.act_show_props.setIcon(theme.icon("inspector"))

        self.act_rot_cw = self._act("Rotate &Clockwise", "rotate-right", "Ctrl+R", lambda: self.rotate_pages(90), tip="Rotate page(s) 90° clockwise")
        self.act_rot_ccw = self._act("Rotate Counter-cloc&kwise", "rotate-left", "Ctrl+Shift+R", lambda: self.rotate_pages(-90), tip="Rotate page(s) 90° counter-clockwise")
        self.act_rot_180 = self._act("Rotate &180°", None, None, lambda: self.rotate_pages(180))
        self.act_del_page = self._act("&Delete Page(s)", "trash", "Ctrl+Shift+Delete", self.delete_pages, tip="Delete the selected page(s)")
        self.act_dup_page = self._act("D&uplicate Page(s)", "duplicate", "Ctrl+D", self.duplicate_pages, tip="Duplicate the selected page(s)")
        self.act_blank = self._act("Insert &Blank Page…", "add-page", "Ctrl+Shift+N", self.insert_blank, tip="Insert a blank page")
        self.act_move_up = self._act("Move Page &Up", None, "Ctrl+Shift+Up", lambda: self.move_pages(-1))
        self.act_move_down = self._act("Move Page Do&wn", None, "Ctrl+Shift+Down", lambda: self.move_pages(1))
        self.act_reverse = self._act("&Reverse Page Order", "reverse", None, self.reverse_pages)
        self.act_crop = self._act("&Crop Pages…", "crop", None, self.crop_pages, tip="Crop page margins")
        self.act_uncrop = self._act("Reset Cr&op", None, None, self.reset_crop)
        self.act_about = self._act(f"&About {APP_NAME}", "info", None, lambda: AboutDialog(self).exec())

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addActions([self.act_new, self.act_open])
        self.recent_menu = m.addMenu("Open &Recent")
        m.addSeparator()
        m.addActions([self.act_save, self.act_save_as])
        m.addSeparator()
        m.addActions([self.act_insert_file, self.act_extract, self.act_split])
        m.addSeparator()
        m.addActions([self.act_close, self.act_quit])
        m = mb.addMenu("&Edit")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_delete, self.act_select_all, self.act_deselect])
        m.addSeparator()
        m.addAction(self.act_edit_text)
        m.addSeparator()
        m.addAction(self.act_scale_stroke)
        m = mb.addMenu("&Insert")
        m.addActions([self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen, self.act_tool_text])
        m.addSeparator()
        m.addAction(self.act_insert_image)
        m.addSeparator()
        fm = m.addMenu("Form &Field")
        fm.setIcon(theme.icon("form"))
        fm.addActions(self.field_actions)
        m = mb.addMenu("&View")
        m.addActions([self.act_tool_select, self.act_tool_node, self.act_tool_text, self.act_tool_hand])
        m.addSeparator()
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_zoom_width, self.act_zoom_100])
        m.addSeparator()
        m.addActions([self.act_first, self.act_prev, self.act_next, self.act_last])
        m.addSeparator()
        m.addActions([self.act_show_pages, self.act_show_props, self.act_dark])
        m = mb.addMenu("&Page")
        m.addActions([self.act_rot_cw, self.act_rot_ccw, self.act_rot_180])
        m.addSeparator()
        m.addActions([self.act_blank, self.act_dup_page, self.act_del_page])
        m.addSeparator()
        m.addActions([self.act_move_up, self.act_move_down, self.act_reverse])
        m.addSeparator()
        m.addActions([self.act_crop, self.act_uncrop])
        m = mb.addMenu("&Help")
        m.addAction(self.act_about)
        self._update_recent_menu()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(theme.icon_size())
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(tb)
        self.toolbar = tb
        tb.addActions([self.act_open, self.act_save])
        tb.addSeparator()
        tb.addActions([self.act_undo, self.act_redo])
        tb.addSeparator()
        tb.addActions([self.act_tool_select, self.act_tool_node, self.act_tool_text, self.act_tool_hand])
        tb.addSeparator()
        tb.addActions([self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen])
        self.field_button = QToolButton()
        self.field_button.setDefaultAction(self.act_tool_field)
        self.field_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        field_menu = QMenu(self.field_button)
        field_menu.addActions(self.field_actions)
        self.field_button.setMenu(field_menu)
        tb.addWidget(self.field_button)
        tb.addAction(self.act_insert_image)
        tb.addSeparator()
        tb.addActions([self.act_zoom_out, self.act_zoom_in, self.act_zoom_fit, self.act_zoom_width])
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setMinimumWidth(84)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for z in ZOOM_LEVELS:
            self.zoom_combo.addItem(f"{int(z * 100)}%", z)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_from_combo)
        self.zoom_combo.activated.connect(lambda i: self.canvas.set_zoom(self.zoom_combo.itemData(i) or 1.0))
        tb.addWidget(self.zoom_combo)
        tb.addSeparator()
        tb.addAction(self.act_prev)
        self.page_label = QLabel("")
        self.page_label.setMinimumWidth(90)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb.addWidget(self.page_label)
        tb.addAction(self.act_next)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addActions([self.act_rot_ccw, self.act_rot_cw, self.act_blank, self.act_dup_page, self.act_del_page])
        tb.addSeparator()
        tb.addActions([self.act_show_pages, self.act_show_props, self.act_dark])

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.status_msg = QLabel("")
        self.status_hint = QLabel("")
        self.status_hint.setProperty("role", "muted")
        sb.addWidget(self.status_msg, 1)
        sb.addPermanentWidget(self.status_hint)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self.status_msg.setText(""))

    def _connect(self) -> None:
        self.canvas.zoomChanged.connect(self._on_zoom)
        self.canvas.statusMessage.connect(self.show_message)
        self.canvas.selectionChanged.connect(lambda ids: self._update_actions())
        self.canvas.toolChanged.connect(self._on_tool_changed)
        self.pages.pageActivated.connect(self.go_to_page)
        self.pages.movePagesRequested.connect(self._move_pages_to)
        self.pages.contextMenuRequestedAt.connect(self._pages_context_menu)
        self.pages.itemSelectionChanged.connect(self._update_actions)

    # -- state -------------------------------------------------------------
    def _restore_state(self) -> None:
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        st = self.settings.value("window/state")
        if st:
            self.restoreState(st)
        self.canvas.scale_stroke = self.settings.value("edit/scaleStroke", True, type=bool)
        self.act_scale_stroke.setChecked(self.canvas.scale_stroke)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._maybe_save():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        event.accept()

    def _update_actions(self) -> None:
        has = self.doc is not None
        n = self.doc.page_count if self.doc else 0
        sel = bool(self.canvas.selection)
        for a in (self.act_save, self.act_save_as, self.act_close, self.act_insert_file, self.act_extract, self.act_split,
                  self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_zoom_width, self.act_zoom_100,
                  self.act_rot_cw, self.act_rot_ccw, self.act_rot_180, self.act_dup_page, self.act_blank, self.act_reverse,
                  self.act_crop, self.act_uncrop, self.act_select_all):
            a.setEnabled(has)
        self.act_undo.setEnabled(has and self.doc.undo_stack.can_undo)
        self.act_redo.setEnabled(has and self.doc.undo_stack.can_redo)
        self.act_undo.setText(f"&Undo {self.doc.undo_stack.undo_label}" if has and self.doc.undo_stack.can_undo else "&Undo")
        self.act_redo.setText(f"&Redo {self.doc.undo_stack.redo_label}" if has and self.doc.undo_stack.can_redo else "&Redo")
        sel = self.canvas.has_selection
        self.act_delete.setEnabled(sel)
        self.act_deselect.setEnabled(sel)
        self.act_insert_image.setEnabled(has)
        for a in (self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen, self.act_tool_field, *self.field_actions):
            a.setEnabled(has)
        self.act_edit_text.setEnabled(len(self.canvas.selection) == 1 and self.canvas.selected_objects()[0].kind == "text")
        self.act_del_page.setEnabled(has and n > 1)
        self.act_move_up.setEnabled(has and self.canvas.page_index > 0)
        self.act_move_down.setEnabled(has and self.canvas.page_index < n - 1)
        self.act_prev.setEnabled(has and self.canvas.page_index > 0)
        self.act_next.setEnabled(has and self.canvas.page_index < n - 1)
        self.act_first.setEnabled(has and self.canvas.page_index > 0)
        self.act_last.setEnabled(has and self.canvas.page_index < n - 1)
        self.page_label.setText(f"{self.canvas.page_index + 1} / {n}" if has else "–")
        title = APP_NAME
        if self.doc is not None:
            title = f"{'• ' if self.doc.is_modified else ''}{self.doc.title} — {APP_NAME}"
        self.setWindowTitle(title)
        self.act_save.setEnabled(has and self.doc.is_modified)

    def _on_zoom(self, z: float) -> None:
        self.zoom_combo.setEditText(f"{int(round(z * 100))}%")

    def _zoom_from_combo(self) -> None:
        text = self.zoom_combo.currentText().strip().rstrip("%")
        try:
            self.canvas.set_zoom(float(text) / 100.0)
        except ValueError:
            pass

    def _on_tool_changed(self, tool: str) -> None:
        mapping = {
            TOOL_SELECT: self.act_tool_select, TOOL_NODE: self.act_tool_node, TOOL_TEXT: self.act_tool_text, TOOL_HAND: self.act_tool_hand,
            TOOL_RECT: self.act_tool_rect, TOOL_ELLIPSE: self.act_tool_ellipse, TOOL_LINE: self.act_tool_line, TOOL_PEN: self.act_tool_pen,
        }
        if tool.startswith(TOOL_FIELD):
            ftype = self.canvas.field_tool_type()
            self._last_field_type = ftype
            for a in self.field_actions:
                if a.property("fieldType") == ftype:
                    a.setChecked(True)
                    self.act_tool_field.setIcon(a.icon())
                    self.act_tool_field.setToolTip(f"Add {a.text().lower()} (F)")
            self.field_button.setChecked(True)
            self.field_button.setDown(False)
        else:
            mapping[tool].setChecked(True)
            self.field_button.setChecked(False)
        hints = {
            TOOL_SELECT: "Click to select · drag to move · Shift+click to add · handles resize · double-click text to edit · Ctrl+wheel zooms",
            TOOL_NODE: "Drag anchors (squares) and control points (circles) · Esc returns to Select",
            TOOL_TEXT: "Click text to edit the line · click empty space to add new text · Enter applies · Esc cancels",
            TOOL_HAND: "Drag to pan · Ctrl+wheel zooms",
            TOOL_RECT: "Drag to draw a rectangle · Shift for a square",
            TOOL_ELLIPSE: "Drag to draw an ellipse · Shift for a circle",
            TOOL_LINE: "Drag to draw a line · Shift snaps to 45°",
            TOOL_PEN: "Click to add points · double-click or Enter to finish · click the first point to close · Esc cancels",
        }
        self.status_hint.setText(hints.get(tool, "Drag on the page to place the field · select a field to edit it in the Inspector"))

    def show_message(self, text: str, timeout_ms: int = 6000) -> None:
        self.status_msg.setText(text)
        self._msg_timer.start(timeout_ms)

    # -- document lifecycle -------------------------------------------------
    def _set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.remove_listener(self._on_doc_event)
            self.doc.undo_stack.listeners.remove(self._update_actions)
            self.doc.close()
        self.doc = doc
        self.canvas.set_document(doc)
        self.pages.set_document(doc)
        if doc is not None:
            doc.add_listener(self._on_doc_event)
            doc.undo_stack.listeners.append(self._update_actions)
            self.pages.set_current_page(0)
            QTimer.singleShot(0, self.canvas.zoom_fit)
        self.properties.refresh()
        self._update_actions()
        self._on_tool_changed(self.canvas.tool)

    def _on_doc_event(self, event: str, payload) -> None:
        self._update_actions()
        if event in ("pages", "page_content", "saved"):
            self.properties.refresh()
        if event == "pages":
            self.pages.set_current_page(self.canvas.page_index)

    def new_document(self) -> None:
        if not self._maybe_save():
            return
        self._set_document(Document())
        self.show_message("New document with one blank page")

    def open_dialog(self) -> None:
        start = self.settings.value("files/lastDir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", start, "PDF files (*.pdf);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        if not self._maybe_save():
            return
        try:
            doc = Document(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open", f"Could not open “{os.path.basename(path)}”.\n\n{exc}")
            return
        if doc.needs_password:
            while True:
                dlg = PasswordDialog(os.path.basename(path), self)
                if dlg.exec() != PasswordDialog.DialogCode.Accepted:
                    doc.close()
                    return
                if doc.authenticate(dlg.password()):
                    break
                QMessageBox.warning(self, "Wrong password", "The password was not accepted.")
        self._set_document(doc)
        self.settings.setValue("files/lastDir", os.path.dirname(path))
        self._add_recent(path)
        self.show_message(f"Opened {os.path.basename(path)} · {doc.page_count} page(s)")

    def close_document(self) -> None:
        if not self._maybe_save():
            return
        self._set_document(None)

    def _maybe_save(self) -> bool:
        if self.doc is None or not self.doc.is_modified:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"“{self.doc.title}” has unsaved changes.")
        box.setInformativeText("Do you want to save them?")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        r = box.exec()
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def save(self) -> bool:
        if self.doc is None:
            return False
        if not self.doc.path:
            return self.save_as()
        try:
            self.doc.save()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.show_message(f"Saved {self.doc.title}")
        self._update_actions()
        return True

    def save_as(self) -> bool:
        if self.doc is None:
            return False
        start = self.doc.path or os.path.join(self.settings.value("files/lastDir", ""), self.doc.title)
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF as", start, "PDF files (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.doc.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._add_recent(path)
        self.show_message(f"Saved as {os.path.basename(path)}")
        self._update_actions()
        return True

    # -- recent files -----------------------------------------------------------
    def _recent(self) -> list[str]:
        v = self.settings.value("files/recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if isinstance(p, str)]

    def _add_recent(self, path: str) -> None:
        rec = [p for p in self._recent() if p != path]
        rec.insert(0, path)
        self.settings.setValue("files/recent", rec[:10])
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self.recent_menu.clear()
        rec = self._recent()
        for p in rec:
            a = self.recent_menu.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda checked=False, p=p: self.open_file(p))
        if not rec:
            a = self.recent_menu.addAction("No recent files")
            a.setEnabled(False)

    # -- navigation -------------------------------------------------------------
    def go_to_page(self, index: int) -> None:
        if self.doc is None:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        self.canvas.set_page(index)
        self.pages.set_current_page(index)
        self.properties.refresh()
        self._update_actions()

    def _target_pages(self) -> list[int]:
        sel = self.pages.selected_pages() if self.pages_dock.isVisible() else []
        if self.canvas.page_index not in sel:
            sel = [self.canvas.page_index]
        return sel

    # -- page operations ----------------------------------------------------------
    def rotate_pages(self, delta: int) -> None:
        if self.doc:
            self.doc.rotate_pages(self._target_pages(), delta)

    def delete_pages(self) -> None:
        if not self.doc:
            return
        pages = self._target_pages()
        if len(pages) >= self.doc.page_count:
            QMessageBox.information(self, "Cannot delete", "A document must keep at least one page.")
            return
        if len(pages) > 1:
            r = QMessageBox.question(self, "Delete pages", f"Delete {len(pages)} pages?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.doc.delete_pages(pages)
        self.go_to_page(min(pages[0], self.doc.page_count - 1))

    def duplicate_pages(self) -> None:
        if self.doc:
            self.doc.duplicate_pages(self._target_pages())

    def insert_blank(self) -> None:
        if not self.doc:
            return
        r = self.doc.page_rect(self.canvas.page_index)
        dlg = BlankPageDialog((r.width, r.height), self.canvas.page_index, self)
        if dlg.exec() == BlankPageDialog.DialogCode.Accepted:
            at, w, h = dlg.values()
            self.doc.insert_blank_page(at, w, h)
            self.go_to_page(at)

    def move_pages(self, delta: int) -> None:
        if not self.doc:
            return
        pages = self._target_pages()
        if delta < 0 and pages[0] == 0:
            return
        if delta > 0 and pages[-1] >= self.doc.page_count - 1:
            return
        target = pages[0] - 1 if delta < 0 else pages[-1] + 2
        self.doc.move_pages(pages, target)
        new_first = pages[0] + delta
        self.go_to_page(new_first)
        self.pages.clearSelection()
        for i in range(len(pages)):
            self.pages.item(new_first + i).setSelected(True)

    def _move_pages_to(self, sources: list[int], target: int) -> None:
        if not self.doc:
            return
        self.doc.move_pages(sources, target)
        new_first = target - sum(1 for s in sources if s < target)
        self.go_to_page(new_first)
        self.pages.clearSelection()
        for i in range(len(sources)):
            if new_first + i < self.pages.count():
                self.pages.item(new_first + i).setSelected(True)

    def reverse_pages(self) -> None:
        if self.doc:
            self.doc.reverse_pages()

    def crop_pages(self) -> None:
        if not self.doc:
            return
        dlg = CropDialog(self.doc.page_count, self._target_pages(), self)
        if dlg.exec() != CropDialog.DialogCode.Accepted:
            return
        scope = dlg.scope_value()
        pages = list(range(self.doc.page_count)) if scope == "all" else (self._target_pages() if scope == "selected" else [self.canvas.page_index])
        left, top, right, bottom = dlg.margins()
        # cropbox is in unrotated PDF space with y up: top margin trims y1, bottom trims y0
        self.doc.set_cropbox_margins(pages, left, bottom, right, top)

    def reset_crop(self) -> None:
        if self.doc:
            self.doc.reset_cropbox(self._target_pages())

    def insert_from_file(self) -> None:
        if not self.doc:
            return
        dlg = InsertPagesDialog(self.doc.page_count, self.canvas.page_index, self)
        if dlg.exec() != InsertPagesDialog.DialogCode.Accepted:
            return
        path, pages, at = dlg.values()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Insert pages", "Please choose an existing PDF file.")
            return
        try:
            import pymupdf

            src = pymupdf.open(path)
            n = src.page_count
            src.close()
            idx = parse_page_ranges(pages, n)
        except Exception as exc:
            QMessageBox.critical(self, "Insert pages", f"Could not read the file.\n\n{exc}")
            return
        if not idx:
            QMessageBox.warning(self, "Insert pages", "No pages matched the given range.")
            return
        # insert contiguous runs to preserve the requested order
        runs: list[tuple[int, int]] = []
        for i in idx:
            if runs and runs[-1][1] == i - 1:
                runs[-1] = (runs[-1][0], i)
            else:
                runs.append((i, i))
        pos = at
        for a, b in runs:
            self.doc.insert_pages_from(path, pos, a, b)
            pos += b - a + 1
        self.go_to_page(at)
        self.show_message(f"Inserted {len(idx)} page(s) from {os.path.basename(path)}")

    def extract_pages(self) -> None:
        if not self.doc:
            return
        dlg = ExtractPagesDialog(self.doc.page_count, self._target_pages(), self)
        if dlg.exec() != ExtractPagesDialog.DialogCode.Accepted:
            return
        idx = dlg.indices()
        if not idx:
            QMessageBox.warning(self, "Extract pages", "No pages matched the given range.")
            return
        stem = os.path.splitext(self.doc.title)[0]
        start = os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}-extract.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Extract pages to", start, "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.doc.extract_pages(idx, path)
        except Exception as exc:
            QMessageBox.critical(self, "Extract pages", str(exc))
            return
        self.show_message(f"Extracted {len(idx)} page(s) to {os.path.basename(path)}")

    def split_document(self) -> None:
        if not self.doc:
            return
        dlg = SplitDialog(self.doc.page_count, self)
        if dlg.exec() != SplitDialog.DialogCode.Accepted:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder", os.path.dirname(self.doc.path or ""))
        if not out_dir:
            return
        stem = os.path.splitext(self.doc.title)[0]
        try:
            paths = self.doc.split_every(dlg.chunk_size(), out_dir, stem)
        except Exception as exc:
            QMessageBox.critical(self, "Split document", str(exc))
            return
        self.show_message(f"Wrote {len(paths)} file(s) to {out_dir}")

    def _pages_context_menu(self, pos: QPoint) -> None:
        if not self.doc:
            return
        menu = QMenu(self)
        menu.addActions([self.act_rot_cw, self.act_rot_ccw, self.act_rot_180])
        menu.addSeparator()
        menu.addActions([self.act_blank, self.act_dup_page, self.act_del_page])
        menu.addSeparator()
        menu.addActions([self.act_move_up, self.act_move_down])
        menu.addSeparator()
        menu.addActions([self.act_extract, self.act_crop, self.act_uncrop])
        menu.exec(self.pages.mapToGlobal(pos))

    # -- edit ---------------------------------------------------------------
    def undo(self) -> None:
        if self.doc:
            self.doc.undo_stack.undo()

    def redo(self) -> None:
        if self.doc:
            self.doc.undo_stack.redo()

    def insert_image(self) -> None:
        if not self.doc:
            return
        start = self.settings.value("files/lastImageDir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Insert image", start, "Images (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp *.svg);;All files (*)")
        if not path:
            return
        self.settings.setValue("files/lastImageDir", os.path.dirname(path))
        self.canvas.set_tool(TOOL_SELECT)
        self.canvas.insert_image(path)

    def edit_selected_text(self) -> None:
        if len(self.canvas.selection) == 1:
            self.canvas.begin_text_edit(self.canvas.selection[0])

    def _toggle_scale_stroke(self, on: bool) -> None:
        self.canvas.scale_stroke = on
        self.settings.setValue("edit/scaleStroke", on)

    # -- theme ---------------------------------------------------------------
    def toggle_dark(self, on: bool) -> None:
        app = QApplication.instance()
        theme.apply_theme(app, on)
        self.settings.setValue("ui/dark", on)
        self._refresh_icons()
        self.canvas.apply_theme()
        self.pages.refresh()
        self.properties.refresh()

    def _refresh_icons(self) -> None:
        for a in self.findChildren(QAction):
            name = a.property("iconName")
            if name:
                a.setIcon(theme.icon(name))
        self.act_show_pages.setIcon(theme.icon("pages"))
        self.act_show_props.setIcon(theme.icon("inspector"))

    # -- drag & drop ------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for u in event.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".pdf"):
                self.open_file(p)
                break
