"""Main application window."""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QIntValidator,
    QKeySequence,
    QPainter,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from quirewright import APP_ID, APP_NAME
from quirewright.core.document import Document
from quirewright.core.geometry import Rect
from quirewright.i18n import N_, tr
from quirewright.ui import theme
from quirewright.ui.canvas import (
    TOOL_CROP,
    TOOL_ELLIPSE,
    TOOL_FIELD,
    TOOL_HAND,
    TOOL_LINE,
    TOOL_MARKUP,
    TOOL_NODE,
    TOOL_NOTE,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_REDACT,
    TOOL_SELECT,
    TOOL_TEXT,
    PageCanvas,
)
from quirewright.ui.dialogs import (
    AboutDialog,
    BlankPageDialog,
    CropDialog,
    ExtractPagesDialog,
    InsertPagesDialog,
    PasswordDialog,
    SplitDialog,
    parse_page_ranges,
)
from quirewright.ui.doc_dialogs import (
    ExportImageDialog,
    OcrDialog,
    PageLabelsDialog,
    PageNumbersDialog,
    PreferencesDialog,
    PropertiesDialog,
    ResourcesDialog,
    SecurityDialog,
    ShortcutsDialog,
    WatermarkDialog,
    _human_size,
)
from quirewright.ui.docview import DocumentView
from quirewright.ui.help import HelpWindow
from quirewright.ui.outline import OutlinePanel
from quirewright.ui.properties import PropertiesPanel
from quirewright.ui.render import pixmap_to_qimage
from quirewright.ui.sign_dialogs import SignaturesDialog, SignDialog
from quirewright.ui.thumbnails import PagesPanel
from quirewright.ui.welcome import WelcomePage

ZOOM_LEVELS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
DOCS_URL = "https://github.com/"  # placeholder until the project has a home


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(APP_ID, APP_ID)
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 880)
        self.setAcceptDrops(True)
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)

        # central: welcome page <-> document tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().setExpanding(False)
        self._placeholder_view = DocumentView(Document())  # keeps a canvas available when no tab is open
        self._placeholder_view.hide()
        self.welcome = WelcomePage()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)
        self._current_view: DocumentView | None = None

        self.pages = PagesPanel()
        self.outline = OutlinePanel()
        self.properties = PropertiesPanel(self.canvas)

        self.left_tabs = QTabWidget()
        self.left_tabs.setDocumentMode(True)
        self.left_tabs.addTab(self.pages, tr("Pages"))
        self.left_tabs.addTab(self.outline, tr("Bookmarks"))
        self.pages_dock = QDockWidget(tr("Navigation"), self)
        self.pages_dock.setObjectName("pagesDock")
        self.pages_dock.setWidget(self.left_tabs)
        self.pages_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.pages_dock)
        self.props_dock = QDockWidget(tr("Inspector"), self)
        self.props_dock.setObjectName("inspectorDock")
        self.props_dock.setWidget(self.properties)
        self.props_dock.setMinimumWidth(340)
        self.props_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._connect()
        self._update_actions()
        self._restore_state()
        self.welcome.set_recent(self._recent())

    # -- current document --------------------------------------------------
    @property
    def view(self) -> DocumentView:
        return self._current_view if self._current_view is not None else self._placeholder_view

    @property
    def canvas(self) -> PageCanvas:
        return self.view.canvas

    @property
    def findbar(self):
        return self.view.findbar

    @property
    def doc(self) -> Document | None:
        return self._current_view.doc if self._current_view is not None else None

    def views(self) -> list[DocumentView]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

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

    def _tool_act(self, text: str, icon: str, shortcut, tool: str, tip: str) -> QAction:
        a = self._act(text, icon, shortcut, lambda checked=False, t=tool: self.canvas.set_tool(t), True, tip)
        a.setProperty("tool", tool)
        self.tool_group.addAction(a)
        return a

    def _build_actions(self) -> None:
        S = QKeySequence
        # file
        self.act_new = self._act(tr("&New"), "new", S.StandardKey.New, self.new_document, tip=tr("Create a new document with one blank page"))
        self.act_open = self._act(tr("&Open…"), "open", S.StandardKey.Open, self.open_dialog, tip=tr("Open a PDF"))
        self.act_save = self._act(tr("&Save"), "save", S.StandardKey.Save, self.save, tip=tr("Save the document"))
        self.act_save_as = self._act(tr("Save &As…"), None, S.StandardKey.SaveAs, self.save_as)
        self.act_reduce = self._act(tr("Save &Reduced Size Copy…"), "shrink", None, self.save_reduced, tip=tr("Write a smaller copy with recompressed images"))
        self.act_export_image = self._act(tr("Export Page as &Image…"), "export", None, self.export_image)
        self.act_export_text = self._act(tr("Export &Text…"), None, None, self.export_text)
        self.act_print = self._act(tr("&Print…"), "print", S.StandardKey.Print, self.print_document, tip=tr("Print the document"))
        self.act_close = self._act(tr("&Close"), None, S.StandardKey.Close, self.close_document)
        self.act_next_tab = self._act(tr("Next &Tab"), None, "Ctrl+Tab", lambda: self._cycle_tab(1))
        self.act_prev_tab = self._act(tr("Previous Ta&b"), None, "Ctrl+Shift+Tab", lambda: self._cycle_tab(-1))
        self.act_quit = self._act(tr("&Quit"), None, S.StandardKey.Quit, self.close)
        self.act_insert_file = self._act(tr("&Insert Pages from File…"), "insert", "Ctrl+Shift+I", self.insert_from_file)
        self.act_extract = self._act(tr("&Extract Pages…"), "extract", "Ctrl+Shift+E", self.extract_pages)
        self.act_split = self._act(tr("S&plit Document…"), "split", None, self.split_document)
        # edit
        self.act_undo = self._act(tr("&Undo"), "undo", S.StandardKey.Undo, self.undo)
        self.act_redo = self._act(tr("&Redo"), "redo", S.StandardKey.Redo, self.redo)
        self.act_delete = self._act(tr("&Delete"), "trash", None, lambda: self.canvas.delete_selection(), tip=tr("Delete selected objects"))
        self.act_select_all = self._act(tr("Select &All"), None, S.StandardKey.SelectAll, lambda: self.canvas.select_all())
        self.act_deselect = self._act(tr("D&eselect"), None, "Ctrl+Shift+A", lambda: self.canvas.clear_selection())
        self.act_copy_text = self._act(tr("&Copy Text"), "copy", S.StandardKey.Copy, self.copy_text, tip=tr("Copy the selected text to the clipboard"))
        self.act_duplicate = self._act(tr("D&uplicate"), "duplicate", "Ctrl+Shift+D", lambda: self.canvas.duplicate_selection(), tip=tr("Duplicate the selected objects"))
        self.act_edit_text = self._act(tr("Edit &Text Line"), "edit", "F2", self.edit_selected_text)
        self.act_edit_para = self._act(tr("Edit &Paragraph"), None, "Ctrl+E", self.edit_selected_paragraph, tip=tr("Edit the whole paragraph around the selected text with word wrapping"))
        self.act_find = self._act(tr("&Find…"), "find", S.StandardKey.Find, self.show_find, tip=tr("Find text in the document"))
        self.act_find_next = self._act(tr("Find &Next"), None, S.StandardKey.FindNext, lambda: self.findbar.next())
        self.act_find_prev = self._act(tr("Find &Previous"), None, S.StandardKey.FindPrevious, lambda: self.findbar.previous())
        self.act_prefs = self._act(tr("&Preferences…"), "settings", S.StandardKey.Preferences, self.show_preferences)
        self.act_scale_stroke = self._act(tr("Scale Stroke &Width with Objects"), None, None, self._toggle_scale_stroke, checkable=True)
        self.act_scale_stroke.setChecked(True)
        # arrange
        self.act_group = self._act(tr("&Group"), None, "Ctrl+G", lambda: self.canvas.group_selection(), tip=tr("Combine the selected objects into a group (a form XObject)"))
        self.act_ungroup = self._act(tr("&Ungroup"), None, "Ctrl+Shift+G", lambda: self.canvas.ungroup_selection(), tip=tr("Split the selected group back into its objects"))
        self.act_enter_group = self._act(tr("&Enter Group"), None, "Ctrl+Return", lambda: self.canvas.enter_form(), tip=tr("Edit the objects inside the selected group or form XObject"))
        self.act_exit_group = self._act(tr("E&xit Group"), None, "Ctrl+Shift+Return", lambda: self.canvas.exit_form())
        self.act_front = self._act(tr("Bring to &Front"), "front", "Ctrl+Shift+]", lambda: self.canvas.bring_to_front())
        self.act_back = self._act(tr("Send to &Back"), "back", "Ctrl+Shift+[", lambda: self.canvas.send_to_back())
        self.act_flip_h = self._act(tr("Flip &Horizontal"), "flip-h", None, lambda: self.canvas.flip_selection(True))
        self.act_flip_v = self._act(tr("Flip &Vertical"), "flip-v", None, lambda: self.canvas.flip_selection(False))
        self.act_rot_sel_cw = self._act(tr("Rotate Selection 90° CW"), None, "Ctrl+]", lambda: self.canvas.rotate_selection(90))
        self.act_rot_sel_ccw = self._act(tr("Rotate Selection 90° CCW"), None, "Ctrl+[", lambda: self.canvas.rotate_selection(-90))
        self.align_actions = []
        for label, icon_name, mode in (
            ("Align &Left", "align-left", "left"), ("Align &Centre", "align-center-h", "hcenter"), ("Align &Right", "align-right", "right"),
            ("Align &Top", "align-top", "top"), ("Align &Middle", "align-center-v", "vcenter"), ("Align &Bottom", "align-bottom", "bottom"),
        ):
            self.align_actions.append(self._act(tr(label), icon_name, None, lambda checked=False, m=mode: self.canvas.align_selection(m)))
        self.act_dist_h = self._act(tr("Distribute Hori&zontally"), None, None, lambda: self.canvas.distribute_selection(True))
        self.act_dist_v = self._act(tr("Distribute &Vertically"), None, None, lambda: self.canvas.distribute_selection(False))
        # tools
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.act_tool_select = self._tool_act(tr("Select"), "select", "S", TOOL_SELECT, tr("Select and transform objects (S)"))
        self.act_tool_node = self._tool_act(tr("Nodes"), "node", "N", TOOL_NODE, tr("Edit path nodes (N)"))
        self.act_tool_text = self._tool_act(tr("Text"), "text", "T", TOOL_TEXT, tr("Edit or add text (T)"))
        self.act_tool_hand = self._tool_act(tr("Pan"), "hand", "H", TOOL_HAND, tr("Pan the page (H)"))
        self.act_tool_rect = self._tool_act(tr("Rectangle"), "rect", "R", TOOL_RECT, tr("Draw a rectangle (R)"))
        self.act_tool_ellipse = self._tool_act(tr("Ellipse"), "ellipse", "E", TOOL_ELLIPSE, tr("Draw an ellipse (E)"))
        self.act_tool_line = self._tool_act(tr("Line"), "line", "L", TOOL_LINE, tr("Draw a straight line (L)"))
        self.act_tool_pen = self._tool_act(tr("Pen"), "pen", "P", TOOL_PEN, tr("Draw a polyline: click points, Enter or double-click to finish (P)"))
        self.field_types = [
            (7, N_("Text field"), "field-text"), (2, "Checkbox", "field-check"), (5, "Radio button", "field-radio"),
            (3, N_("Dropdown"), "field-combo"), (4, "List box", "field-list"), (1, "Push button", "field-button"),
        ]
        self.field_actions: list[QAction] = []
        for ftype, label, icon_name in self.field_types:
            a = self._tool_act(tr(label), icon_name, None, f"{TOOL_FIELD}:{ftype}", tr("Drag on the page to add a {field}").format(field=tr(label).lower()))
            a.setProperty("fieldType", ftype)
            self.field_actions.append(a)
        self._last_field_type = 7
        self.act_tool_field = self._act(tr("Form Field"), "form", "F", lambda: self.canvas.set_tool(f"{TOOL_FIELD}:{self._last_field_type}"), True, "Add form fields (F)")
        self.tool_group.addAction(self.act_tool_field)
        self.act_tool_signature = self._tool_act(tr("Signature Field"), "signature", "G", f"{TOOL_FIELD}:6",
                                                 tr("Drag or click on the page to add a visible signature field (G)"))
        self.act_tool_highlight = self._tool_act(tr("Highlight"), "highlight", "Ctrl+Alt+H", f"{TOOL_MARKUP}:highlight", tr("Drag over text to highlight it"))
        self.act_tool_underline = self._tool_act(tr("Underline"), "underline", "Ctrl+Alt+U", f"{TOOL_MARKUP}:underline", tr("Drag over text to underline it"))
        self.act_tool_strike = self._tool_act(tr("Strike Out"), "strikeout", "Ctrl+Alt+K", f"{TOOL_MARKUP}:strikeout", tr("Drag over text to strike it out"))
        self.act_tool_note = self._tool_act(tr("Sticky Note"), "note", "Ctrl+Alt+N", TOOL_NOTE, tr("Click to add a comment"))
        self.act_tool_crop = self._tool_act(tr("Crop Tool"), "crop", "C", TOOL_CROP, tr("Drag a rectangle to crop the page to it (C)"))
        self.act_tool_redact = self._tool_act(tr("Redact Area"), "redact", None, TOOL_REDACT, tr("Drag a rectangle to permanently remove its content"))
        self.act_tool_select.setChecked(True)
        self.act_insert_image = self._act(tr("Insert &Image…"), "image", "Ctrl+Shift+M", self.insert_image, tip=tr("Place an image on the page"))
        # view
        self.act_zoom_in = self._act(tr("Zoom &In"), "zoom-in", S.StandardKey.ZoomIn, lambda: self.canvas.zoom_in())
        self.act_zoom_out = self._act(tr("Zoom &Out"), "zoom-out", S.StandardKey.ZoomOut, lambda: self.canvas.zoom_out())
        self.act_zoom_fit = self._act(tr("&Fit Page"), "zoom-fit", "Ctrl+0", lambda: self.canvas.zoom_fit(), tip=tr("Fit the whole page"))
        self.act_zoom_width = self._act(tr("Fit &Width"), "zoom-width", "Ctrl+2", lambda: self.canvas.zoom_width(), tip=tr("Fit page width"))
        self.act_zoom_100 = self._act(tr("&Actual Size"), None, "Ctrl+1", lambda: self.canvas.zoom_actual())
        self.act_prev = self._act(tr("&Previous Page"), "chevron-left", "PgUp", lambda: self.go_to_page(self.canvas.page_index - 1))
        self.act_next = self._act(tr("&Next Page"), "chevron-right", "PgDown", lambda: self.go_to_page(self.canvas.page_index + 1))
        self.act_first = self._act(tr("&First Page"), None, "Ctrl+Home", lambda: self.go_to_page(0))
        self.act_last = self._act(tr("&Last Page"), None, "Ctrl+End", lambda: self.go_to_page(10**9))
        self.act_goto = self._act(tr("&Go to Page…"), None, "Ctrl+J", self.focus_page_entry)
        self.act_continuous = self._act(tr("&Continuous Scrolling"), None, "Ctrl+Shift+C", self._toggle_continuous, checkable=True, tip=tr("Show all pages in one scrolling column"))
        self.act_continuous.setChecked(True)
        self.act_rulers = self._act(tr("Show &Rulers"), None, "Ctrl+Shift+U", lambda on: self._apply_view_option("rulers", on), checkable=True, tip=tr("Rulers in your preferred units; drag from a ruler to add a guide"))
        self.act_guides = self._act(tr("Show &Guides"), None, None, lambda on: self._apply_view_option("guides", on), checkable=True)
        self.act_grid = self._act(tr("Show Gr&id"), None, "Ctrl+'", lambda on: self._apply_view_option("grid", on), checkable=True)
        self.act_snap = self._act(tr("&Snap"), None, "Ctrl+Shift+;", lambda on: self._apply_view_option("snap", on), checkable=True, tip=tr("Snap to page edges, guides and other objects while dragging (hold Alt to disable temporarily)"))
        self.act_snap_objects = self._act(tr("Snap to &Objects"), None, None, lambda on: self._apply_view_option("snap_objects", on), checkable=True)
        self.act_snap_grid = self._act(tr("Snap to Gri&d"), None, None, lambda on: self._apply_view_option("snap_grid", on), checkable=True)
        self.act_clear_guides = self._act(tr("Clear Guides on This Page"), None, None, lambda: self.canvas.clear_guides(False))
        self.act_clear_all_guides = self._act(tr("Clear All Guides"), None, None, lambda: self.canvas.clear_guides(True))
        for a, key, default in ((self.act_rulers, "view/rulers", True), (self.act_guides, "view/guides", True), (self.act_grid, "view/grid", False),
                                (self.act_snap, "view/snap", True), (self.act_snap_objects, "view/snapObjects", True), (self.act_snap_grid, "view/snapGrid", False)):
            a.setChecked(self.settings.value(key, default, type=bool))
        self.act_dark = self._act(tr("&Dark Mode"), "moon", None, self.toggle_dark, checkable=True)
        self.act_dark.setChecked(theme.current().dark)
        self.act_show_pages = self.pages_dock.toggleViewAction()
        self.act_show_pages.setText(tr("Show &Navigation Panel"))
        self.act_show_pages.setIcon(theme.icon("pages"))
        self.act_show_props = self.props_dock.toggleViewAction()
        self.act_show_props.setText(tr("Show &Inspector"))
        self.act_show_props.setIcon(theme.icon("inspector"))
        # page
        self.act_rot_cw = self._act(tr("Rotate &Clockwise"), "rotate-right", "Ctrl+R", lambda: self.rotate_pages(90), tip=tr("Rotate page(s) 90° clockwise"))
        self.act_rot_ccw = self._act(tr("Rotate Counter-cloc&kwise"), "rotate-left", "Ctrl+Shift+R", lambda: self.rotate_pages(-90), tip=tr("Rotate page(s) 90° counter-clockwise"))
        self.act_rot_180 = self._act(tr("Rotate &180°"), None, None, lambda: self.rotate_pages(180))
        self.act_del_page = self._act(tr("&Delete Page(s)"), "trash", "Ctrl+Shift+Delete", self.delete_pages, tip=tr("Delete the selected page(s)"))
        self.act_dup_page = self._act(tr("D&uplicate Page(s)"), "duplicate", "Ctrl+D", self.duplicate_pages, tip=tr("Duplicate the selected page(s)"))
        self.act_blank = self._act(tr("Insert &Blank Page…"), "add-page", "Ctrl+Shift+N", self.insert_blank, tip=tr("Insert a blank page"))
        self.act_move_up = self._act(tr("Move Page &Up"), None, "Ctrl+Shift+Up", lambda: self.move_pages(-1))
        self.act_move_down = self._act(tr("Move Page Do&wn"), None, "Ctrl+Shift+Down", lambda: self.move_pages(1))
        self.act_reverse = self._act(tr("&Reverse Page Order"), "reverse", None, self.reverse_pages)
        self.act_crop = self._act(tr("Crop by &Margins…"), "crop", None, self.crop_pages, tip=tr("Crop page margins"))
        self.act_uncrop = self._act(tr("Reset Cr&op"), None, None, self.reset_crop)
        self.act_numbers = self._act(tr("Add Page &Numbers…"), "page-number", None, self.add_page_numbers)
        self.act_labels = self._act(tr("Page &Labels…"), None, None, self.edit_page_labels, tip=tr("How pages are numbered in viewers (i, ii, 1, 2, A-1 …)"))
        self.act_watermark = self._act(tr("Add &Watermark…"), "watermark", None, self.add_watermark)
        # document
        self.act_properties = self._act(tr("&Properties…"), "info", "Ctrl+I", self.show_properties, tip=tr("Title, author, keywords and file details"))
        self.act_security = self._act(tr("&Security…"), "lock", None, self.show_security, tip=tr("Passwords and permissions"))
        self.act_resources = self._act(tr("&Resources (Images, Fonts, Attachments)…"), "resources", "Ctrl+Shift+O", self.show_resources, tip=tr("Browse and extract images, fonts and attachments"))
        self.act_attach = self._act(tr("&Attach File…"), "attach", None, self.attach_file)
        self.act_flatten = self._act(tr("&Flatten Forms and Comments"), "flatten", None, self.flatten)
        self.act_ocr = self._act(tr("Recognize &Text (OCR)…"), "search", None, self.run_ocr, tip=tr("Make scanned pages searchable and selectable"))
        self.act_sign = self._act(tr("Si&gn Document…"), "edit", None, self.sign_document, tip=tr("Add a digital signature with a certificate"))
        self.act_signatures = self._act(tr("Si&gnatures…"), "check", None, self.show_signatures, tip=tr("Show and verify the document's signatures"))
        # help
        self.act_about = self._act(f"&About {APP_NAME}", "info", None, lambda: AboutDialog(self).exec())
        self.act_shortcuts = self._act(tr("&Keyboard Shortcuts"), "keyboard", "Ctrl+/", self.show_shortcuts)
        self.act_guide = self._act(tr("&User Guide"), None, "F1", self.open_guide)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addActions([self.act_new, self.act_open])
        self.recent_menu = m.addMenu(tr("Open &Recent"))
        m.addSeparator()
        m.addActions([self.act_save, self.act_save_as, self.act_reduce])
        m.addSeparator()
        ex = m.addMenu(tr("&Export"))
        ex.addActions([self.act_export_image, self.act_export_text])
        m.addActions([self.act_insert_file, self.act_extract, self.act_split])
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addActions([self.act_close, self.act_quit])

        m = mb.addMenu(tr("&Edit"))
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_copy_text, self.act_duplicate, self.act_delete, self.act_select_all, self.act_deselect])
        m.addSeparator()
        m.addActions([self.act_edit_text, self.act_edit_para])
        m.addSeparator()
        m.addActions([self.act_find, self.act_find_next, self.act_find_prev])
        m.addSeparator()
        m.addAction(self.act_scale_stroke)
        m.addAction(self.act_prefs)

        m = mb.addMenu(tr("&Object"))
        m.addActions([self.act_group, self.act_ungroup, self.act_enter_group, self.act_exit_group])
        m.addSeparator()
        m.addActions([self.act_front, self.act_back])
        m.addSeparator()
        m.addActions([self.act_flip_h, self.act_flip_v, self.act_rot_sel_cw, self.act_rot_sel_ccw])
        m.addSeparator()
        al = m.addMenu(tr("&Align"))
        al.addActions(self.align_actions)
        al.addSeparator()
        al.addActions([self.act_dist_h, self.act_dist_v])

        m = mb.addMenu(tr("&Insert"))
        m.addActions([self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen, self.act_tool_text])
        m.addSeparator()
        m.addAction(self.act_insert_image)
        m.addSeparator()
        fm = m.addMenu(tr("Form &Field"))
        fm.setIcon(theme.icon("form"))
        fm.addActions(self.field_actions)
        cm = m.addMenu(tr("&Comment"))
        cm.setIcon(theme.icon("note"))
        cm.addActions([self.act_tool_highlight, self.act_tool_underline, self.act_tool_strike, self.act_tool_note])

        m = mb.addMenu(tr("&View"))
        m.addActions([self.act_tool_select, self.act_tool_node, self.act_tool_text, self.act_tool_hand])
        m.addSeparator()
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_zoom_width, self.act_zoom_100])
        m.addSeparator()
        m.addActions([self.act_first, self.act_prev, self.act_next, self.act_last, self.act_goto])
        m.addSeparator()
        m.addAction(self.act_continuous)
        m.addActions([self.act_rulers, self.act_guides, self.act_grid])
        sn = m.addMenu(tr("S&napping"))
        sn.addActions([self.act_snap, self.act_snap_objects, self.act_snap_grid])
        sn.addSeparator()
        sn.addActions([self.act_clear_guides, self.act_clear_all_guides])
        m.addSeparator()
        m.addActions([self.act_show_pages, self.act_show_props, self.act_dark])
        m.addSeparator()
        m.addActions([self.act_next_tab, self.act_prev_tab])

        m = mb.addMenu(tr("&Page"))
        m.addActions([self.act_rot_cw, self.act_rot_ccw, self.act_rot_180])
        m.addSeparator()
        m.addActions([self.act_blank, self.act_dup_page, self.act_del_page])
        m.addSeparator()
        m.addActions([self.act_move_up, self.act_move_down, self.act_reverse])
        m.addSeparator()
        m.addActions([self.act_tool_crop, self.act_crop, self.act_uncrop])
        m.addSeparator()
        m.addActions([self.act_numbers, self.act_watermark, self.act_labels])

        m = mb.addMenu(tr("&Document"))
        m.addActions([self.act_properties, self.act_security, self.act_resources, self.act_attach])
        m.addSeparator()
        m.addActions([self.act_tool_signature, self.act_sign, self.act_signatures])
        m.addSeparator()
        m.addActions([self.act_ocr, self.act_tool_redact, self.act_flatten])

        m = mb.addMenu(tr("&Help"))
        m.addActions([self.act_guide, self.act_shortcuts])
        m.addSeparator()
        m.addAction(self.act_about)
        self._update_recent_menu()

    def _build_toolbar(self) -> None:
        tb = QToolBar(tr("Main"))
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
        self.field_button = self._menu_button(self.act_tool_field, self.field_actions)
        tb.addWidget(self.field_button)
        self.comment_button = self._menu_button(self.act_tool_highlight, [self.act_tool_highlight, self.act_tool_underline, self.act_tool_strike, self.act_tool_note])
        tb.addWidget(self.comment_button)
        tb.addAction(self.act_tool_signature)
        tb.addAction(self.act_insert_image)
        tb.addSeparator()
        tb.addActions([self.act_zoom_fit, self.act_zoom_width])
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
        self.page_entry = QLineEdit()
        self.page_entry.setFixedWidth(44)
        self.page_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_entry.setValidator(QIntValidator(1, 999999))
        self.page_entry.setToolTip(tr("Page number (Ctrl+G)"))
        self.page_entry.returnPressed.connect(self._page_from_entry)
        tb.addWidget(self.page_entry)
        self.page_total = QLabel("/ –")
        self.page_total.setMinimumWidth(40)
        tb.addWidget(self.page_total)
        tb.addAction(self.act_next)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addActions([self.act_rot_ccw, self.act_rot_cw, self.act_blank, self.act_dup_page, self.act_del_page])
        tb.addSeparator()
        tb.addActions([self.act_show_pages, self.act_show_props, self.act_dark])

    def _menu_button(self, default: QAction, actions: list[QAction]) -> QToolButton:
        btn = QToolButton()
        btn.setDefaultAction(default)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(btn)
        menu.addActions(actions)
        btn.setMenu(menu)
        return btn

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

    def _connect_view(self, view: DocumentView) -> None:
        c = view.canvas
        c.author = self.settings.value("user/author", "", type=str)
        c.confirm_area = self._confirm_area_tool
        c.scale_stroke = self.settings.value("edit/scaleStroke", True, type=bool)
        c.continuous = self.act_continuous.isChecked()
        c.set_snapping(enabled=self.act_snap.isChecked(), objects=self.act_snap_objects.isChecked(), grid=self.act_snap_grid.isChecked(),
                       show_grid=self.act_grid.isChecked(), show_guides=self.act_guides.isChecked(),
                       grid_size=self.settings.value("view/gridSize", 10.0, type=float))
        c.snap_tolerance_px = self.settings.value("view/snapTolerance", 6.0, type=float)
        view.set_rulers_visible(self.act_rulers.isChecked())
        c.zoomChanged.connect(self._on_zoom)
        c.statusMessage.connect(self.show_message)
        c.selectionChanged.connect(lambda ids: self._update_actions())
        c.toolChanged.connect(self._on_tool_changed)
        c.pageChanged.connect(self._on_canvas_page_changed)
        view.findbar.hitChanged.connect(self._on_find_hit)
        view.findbar.highlightsChanged.connect(self._on_find_highlights)
        view.findbar.closed.connect(lambda: self.canvas.setFocus())
        view.doc.add_listener(self._on_doc_event)
        view.doc.undo_stack.listeners.append(self._update_actions)

    def _connect(self) -> None:
        self.pages.pageActivated.connect(self.go_to_page)
        self.pages.movePagesRequested.connect(self._move_pages_to)
        self.pages.contextMenuRequestedAt.connect(self._pages_context_menu)
        self.pages.itemSelectionChanged.connect(self._update_actions)
        self.outline.pageActivated.connect(self.go_to_page)
        self.welcome.openRequested.connect(self.open_dialog)
        self.welcome.newRequested.connect(self.new_document)
        self.welcome.fileRequested.connect(self.open_file)

    # -- state -------------------------------------------------------------
    def _restore_state(self) -> None:
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        st = self.settings.value("window/state")
        if st:
            self.restoreState(st)
        self.act_scale_stroke.setChecked(self.settings.value("edit/scaleStroke", True, type=bool))
        self.act_continuous.setChecked(self.settings.value("view/continuous", True, type=bool))

    def closeEvent(self, event: QCloseEvent) -> None:
        for view in self.views():
            self.tabs.setCurrentWidget(view)
            if not self._maybe_save():
                event.ignore()
                return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        event.accept()

    def _update_actions(self) -> None:
        has = self.doc is not None
        n = self.doc.page_count if self.doc else 0
        objs = self.canvas.selected_objects() if has else []
        sel = self.canvas.has_selection if has else False
        for a in (self.act_save_as, self.act_reduce, self.act_export_image, self.act_export_text, self.act_print, self.act_close,
                  self.act_insert_file, self.act_extract, self.act_split, self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit,
                  self.act_zoom_width, self.act_zoom_100, self.act_rot_cw, self.act_rot_ccw, self.act_rot_180, self.act_dup_page,
                  self.act_blank, self.act_reverse, self.act_crop, self.act_uncrop, self.act_select_all, self.act_find, self.act_find_next,
                  self.act_find_prev, self.act_numbers, self.act_watermark, self.act_properties, self.act_security, self.act_resources,
                  self.act_attach, self.act_flatten, self.act_ocr, self.act_sign, self.act_signatures, self.act_insert_image, self.act_goto, self.act_tool_field, self.act_tool_crop,
                  self.act_tool_redact, self.act_tool_highlight, self.act_tool_underline, self.act_tool_strike, self.act_tool_note,
                  self.act_tool_rect, self.act_tool_ellipse, self.act_tool_line, self.act_tool_pen, self.act_tool_signature, *self.field_actions):
            a.setEnabled(has)
        self.act_undo.setEnabled(has and self.doc.undo_stack.can_undo)
        self.act_redo.setEnabled(has and self.doc.undo_stack.can_redo)
        self.act_undo.setText(f"&Undo {self.doc.undo_stack.undo_label}" if has and self.doc.undo_stack.can_undo else "&Undo")
        self.act_redo.setText(f"&Redo {self.doc.undo_stack.redo_label}" if has and self.doc.undo_stack.can_redo else "&Redo")
        self.act_delete.setEnabled(sel)
        self.act_deselect.setEnabled(sel)
        content_sel = bool(objs)
        for a in (self.act_duplicate, self.act_front, self.act_back, self.act_flip_h, self.act_flip_v, self.act_rot_sel_cw, self.act_rot_sel_ccw, *self.align_actions):
            a.setEnabled(content_sel)
        self.act_group.setEnabled(bool(objs))
        self.act_ungroup.setEnabled(len(objs) == 1 and objs[0].kind == "form")
        self.act_enter_group.setEnabled(len(objs) == 1 and objs[0].kind == "form")
        self.act_exit_group.setEnabled(has and self.canvas.in_group)
        self.act_dist_h.setEnabled(len(objs) >= 3)
        self.act_dist_v.setEnabled(len(objs) >= 3)
        self.act_copy_text.setEnabled(any(o.kind == "text" for o in objs))
        self.act_edit_text.setEnabled(len(objs) >= 1 and all(o.kind == "text" for o in objs))
        self.act_edit_para.setEnabled(len(objs) >= 1 and all(o.kind == "text" for o in objs))
        self.act_labels.setEnabled(has)
        self.act_del_page.setEnabled(has and n > 1)
        self.act_move_up.setEnabled(has and self.canvas.page_index > 0)
        self.act_move_down.setEnabled(has and self.canvas.page_index < n - 1)
        self.act_prev.setEnabled(has and self.canvas.page_index > 0)
        self.act_next.setEnabled(has and self.canvas.page_index < n - 1)
        self.act_first.setEnabled(has and self.canvas.page_index > 0)
        self.act_last.setEnabled(has and self.canvas.page_index < n - 1)
        self.page_entry.setEnabled(has)
        if has and not self.page_entry.hasFocus():
            self.page_entry.setText(str(self.canvas.page_index + 1))
        self.page_total.setText(f"/ {n}" if has else "/ –")
        title = APP_NAME
        if self.doc is not None:
            title = f"{'• ' if self.doc.is_modified else ''}{self.doc.title} — {APP_NAME}"
        self.setWindowTitle(title)
        self.act_save.setEnabled(has and self.doc.is_modified)
        for i, view in enumerate(self.views()):
            if self.tabs.tabText(i) != view.title():
                self.tabs.setTabText(i, view.title())
                self.tabs.setTabToolTip(i, view.tooltip())
        self.act_next_tab.setEnabled(self.tabs.count() > 1)
        self.act_prev_tab.setEnabled(self.tabs.count() > 1)

    def _on_zoom(self, z: float, force: bool = False) -> None:
        if not force and self.sender() is not None and self.sender() is not self.canvas:
            return
        self.zoom_combo.setEditText(f"{int(round(z * 100))}%")

    def _zoom_from_combo(self) -> None:
        text = self.zoom_combo.currentText().strip().rstrip("%")
        try:
            self.canvas.set_zoom(float(text) / 100.0)
        except ValueError:
            pass
        self.canvas.setFocus()

    def _page_from_entry(self) -> None:
        try:
            self.go_to_page(int(self.page_entry.text()) - 1)
        except ValueError:
            pass
        self.canvas.setFocus()

    def focus_page_entry(self) -> None:
        self.page_entry.setFocus()
        self.page_entry.selectAll()

    def _on_tool_changed(self, tool: str, force: bool = False) -> None:
        if not force and self.sender() is not None and self.sender() is not self.canvas:
            return
        for a in self.tool_group.actions():
            if a.property("tool") == tool:
                a.setChecked(True)
                if tool.startswith(TOOL_FIELD) and a is not self.act_tool_signature:
                    self.field_button.setDefaultAction(a)
                    self._last_field_type = self.canvas.field_tool_type()
                elif tool.startswith(TOOL_MARKUP) or tool == TOOL_NOTE:
                    self.comment_button.setDefaultAction(a)
        self.act_tool_field.setChecked(tool.startswith(TOOL_FIELD) and tool != f"{TOOL_FIELD}:6")
        hints = {
            TOOL_SELECT: tr("Click to select · drag to move · Shift+click to add · handles resize · double-click text to edit, a shape for nodes, a group to enter it"),
            TOOL_NODE: tr("Drag anchors (squares) and control points (circles) · Esc returns to Select"),
            TOOL_TEXT: tr("Click text to edit the line · Ctrl+E edits the paragraph · click or drag on empty space for new text · Enter applies · Esc cancels"),
            TOOL_HAND: tr("Drag to pan · Ctrl+wheel zooms"),
            TOOL_RECT: tr("Drag to draw a rectangle · Shift for a square"),
            TOOL_ELLIPSE: tr("Drag to draw an ellipse · Shift for a circle"),
            TOOL_LINE: tr("Drag to draw a line · Shift snaps to 45°"),
            TOOL_PEN: tr("Click for corners, click-and-drag for curves · double-click or Enter finishes · click the first point to close · Esc cancels"),
            TOOL_NOTE: tr("Click on the page to add a sticky note, then type its text in the Inspector"),
            TOOL_CROP: tr("Drag a rectangle to crop the page to that area (content outside is hidden, not deleted)"),
            TOOL_REDACT: tr("Drag a rectangle to permanently remove everything inside it"),
        }
        if tool.startswith(TOOL_MARKUP):
            hint = tr("Drag over words to mark them up · select a comment to edit it in the Inspector")
        elif tool == f"{TOOL_FIELD}:6":
            hint = tr("Drag or click to place a signature field · then Document › Sign Document, or the Inspector's Sign this field…")
        elif tool.startswith(TOOL_FIELD):
            hint = tr("Drag on the page to place the field · select a field to edit it in the Inspector")
        else:
            hint = hints.get(tool, "")
        self.status_hint.setText(hint)

    def show_message(self, text: str, timeout_ms: int = 6000) -> None:
        self.status_msg.setText(text)
        self._msg_timer.start(timeout_ms)

    # -- document lifecycle -------------------------------------------------
    def _add_document(self, doc: Document) -> DocumentView:
        """Open ``doc`` in a new tab and make it current."""
        view = DocumentView(doc)
        self._connect_view(view)
        idx = self.tabs.addTab(view, view.title())
        self.tabs.setTabToolTip(idx, view.tooltip())
        self.tabs.setCurrentIndex(idx)
        self.stack.setCurrentIndex(1)
        mode = self.settings.value("view/fitOnOpen", "page")
        c = view.canvas
        QTimer.singleShot(0, {"width": c.zoom_width, "100": c.zoom_actual}.get(mode, c.zoom_fit))
        c.setFocus()
        return view

    def _on_tab_changed(self, index: int) -> None:
        view = self.tabs.widget(index) if index >= 0 else None
        self._current_view = view
        if view is None:
            self.stack.setCurrentIndex(0)
            self.welcome.set_recent(self._recent())
            self.pages.set_document(None)
            self.outline.set_document(None)
            self.properties.set_canvas(self._placeholder_view.canvas)
        else:
            self.stack.setCurrentIndex(1)
            self.pages.set_document(view.doc)
            self.outline.set_document(view.doc)
            self.outline.current_page = view.canvas.page_index
            self.pages.set_current_page(view.canvas.page_index)
            self.properties.set_canvas(view.canvas)
            self._on_zoom(view.canvas.zoom, force=True)
            view.canvas.setFocus()
        self._on_tool_changed(self.canvas.tool, force=True)
        self.properties.refresh()
        self._update_actions()

    def _set_document(self, doc: Document | None) -> None:
        """Compatibility helper: replace the current tab (or open one) with ``doc``."""
        if self._current_view is not None:
            self._remove_view(self._current_view)
        if doc is not None:
            self._add_document(doc)
        else:
            self._on_tab_changed(self.tabs.currentIndex())

    def _remove_view(self, view: DocumentView) -> None:
        idx = self.tabs.indexOf(view)
        try:
            view.doc.remove_listener(self._on_doc_event)
            if self._update_actions in view.doc.undo_stack.listeners:
                view.doc.undo_stack.listeners.remove(self._update_actions)
        except Exception:
            pass
        if idx >= 0:
            self.tabs.removeTab(idx)
        view.close_document()
        view.deleteLater()
        if self.tabs.count() == 0:
            self._on_tab_changed(-1)

    def close_tab(self, index: int) -> None:
        view = self.tabs.widget(index)
        if view is None:
            return
        self.tabs.setCurrentIndex(index)
        if not self._maybe_save():
            return
        self._remove_view(view)

    def _cycle_tab(self, step: int) -> None:
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def _find_open(self, path: str) -> DocumentView | None:
        ap = os.path.abspath(path)
        for v in self.views():
            if v.doc.path and os.path.abspath(v.doc.path) == ap:
                return v
        return None

    def _on_doc_event(self, event: str, payload) -> None:
        self._update_actions()
        if event in ("pages", "page_content", "saved", "security"):
            self.properties.refresh()
        if event == "pages":
            self.pages.set_current_page(self.canvas.page_index)
            self.outline.current_page = self.canvas.page_index

    def new_document(self) -> None:
        self._add_document(Document())
        self.show_message(tr("New document with one blank page"))

    def open_dialog(self) -> None:
        start = self.settings.value("files/lastDir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("Open PDF"), start, "PDF files (*.pdf);;All files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        existing = self._find_open(path)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
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
                    doc.security.user_password = dlg.password()
                    break
                QMessageBox.warning(self, tr("Wrong password"), tr("The password was not accepted."))
        self._add_document(doc)
        self.settings.setValue("files/lastDir", os.path.dirname(path))
        self._add_recent(path)
        try:
            from quirewright.core import signing

            doc.signed = signing.has_signatures(open(path, "rb").read())
        except Exception:
            doc.signed = False
        if getattr(doc, "signed", False):
            self.show_message(tr("This document is digitally signed. Saving any edit will invalidate the signature (Document › Signatures to verify)."), 12000)
        else:
            self.show_message(f"Opened {os.path.basename(path)} · {doc.page_count} page(s)")

    def close_document(self) -> None:
        if self._current_view is None:
            return
        self.close_tab(self.tabs.currentIndex())

    def _maybe_save(self) -> bool:
        if self.doc is None or not self.doc.is_modified:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Unsaved changes"))
        box.setText(f"“{self.doc.title}” has unsaved changes.")
        box.setInformativeText(tr("Do you want to save them?"))
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        r = box.exec()
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return r == QMessageBox.StandardButton.Discard

    def save(self) -> bool:
        if self.doc is None:
            return False
        if getattr(self.doc, "signed", False) and self.doc.is_modified:
            r = QMessageBox.warning(self, tr("Signed document"), tr("This document is digitally signed. Saving your changes will invalidate the signature. Save anyway?"),
                                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
            if r != QMessageBox.StandardButton.Save:
                return False
            self.doc.signed = False
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
        path, _ = QFileDialog.getSaveFileName(self, tr("Save PDF as"), start, "PDF files (*.pdf)")
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

    def save_reduced(self) -> None:
        if self.doc is None:
            return
        stem = os.path.splitext(self.doc.title)[0]
        start = os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}-small.pdf")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save reduced size copy"), start, "PDF files (*.pdf)")
        if not path:
            return
        try:
            size = self.doc.save_optimized(path)
        except Exception as exc:
            QMessageBox.critical(self, "Reduce file size", str(exc))
            return
        before = self.doc.document_info()["file_size"]
        msg = f"Wrote {os.path.basename(path)} ({_human_size(size)}"
        if before:
            msg += f", was {_human_size(before)}"
        self.show_message(msg + ")")

    def export_image(self) -> None:
        if self.doc is None:
            return
        dlg = ExportImageDialog(self.doc.page_count, self.canvas.page_index, self)
        if dlg.exec() != ExportImageDialog.DialogCode.Accepted:
            return
        ext = dlg.format.currentData()
        stem = os.path.splitext(self.doc.title)[0]
        if dlg.scope.currentData() == "current":
            start = os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}-page{self.canvas.page_index + 1}.{ext}")
            path, _ = QFileDialog.getSaveFileName(self, tr("Export page"), start, f"{ext.upper()} (*.{ext})")
            if not path:
                return
            try:
                self.doc.export_page_image(self.canvas.page_index, path, dlg.dpi.value(), dlg.annots.isChecked())
            except Exception as exc:
                QMessageBox.critical(self, "Export", str(exc))
                return
            self.show_message(f"Exported {os.path.basename(path)}")
        else:
            folder = QFileDialog.getExistingDirectory(self, tr("Choose folder for page images"), os.path.dirname(self.doc.path or ""))
            if not folder:
                return
            for i in range(self.doc.page_count):
                self.doc.export_page_image(i, os.path.join(folder, f"{stem}-page{i + 1:03d}.{ext}"), dlg.dpi.value(), dlg.annots.isChecked())
            self.show_message(f"Exported {self.doc.page_count} page image(s) to {folder}")

    def export_text(self) -> None:
        if self.doc is None:
            return
        stem = os.path.splitext(self.doc.title)[0]
        path, _ = QFileDialog.getSaveFileName(self, tr("Export text"), os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}.txt"), "Text (*.txt)")
        if path:
            self.doc.export_text(path)
            self.show_message(f"Exported text to {os.path.basename(path)}")

    def print_document(self) -> None:
        if self.doc is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.doc.title)
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setMinMax(1, self.doc.page_count)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0:
            first, last = 1, self.doc.page_count
        painter = QPainter(printer)
        try:
            for i in range(first - 1, last):
                if i > first - 1:
                    printer.newPage()
                page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                pr = self.doc.page_rect(i)
                scale = min(page_rect.width() / pr.width, page_rect.height() / pr.height)
                pix = self.doc.render(i, scale * 1.0)
                img = pixmap_to_qimage(pix)
                x = page_rect.x() + (page_rect.width() - img.width()) / 2
                y = page_rect.y() + (page_rect.height() - img.height()) / 2
                painter.drawImage(int(x), int(y), img)
        finally:
            painter.end()
        self.show_message(tr("Sent to printer"))

    # -- recent files -----------------------------------------------------------
    def _recent(self) -> list[str]:
        v = self.settings.value("files/recent", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if isinstance(p, str) and os.path.exists(p)]

    def _add_recent(self, path: str) -> None:
        rec = [p for p in self._recent() if p != path]
        rec.insert(0, path)
        self.settings.setValue("files/recent", rec[:10])
        self._update_recent_menu()
        self.welcome.set_recent(rec[:10])

    def _update_recent_menu(self) -> None:
        self.recent_menu.clear()
        rec = self._recent()
        for p in rec:
            a = self.recent_menu.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda checked=False, p=p: self.open_file(p))
        if not rec:
            a = self.recent_menu.addAction(tr("No recent files"))
            a.setEnabled(False)

    # -- navigation -------------------------------------------------------------
    def go_to_page(self, index: int) -> None:
        if self.doc is None:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        self.canvas.set_page(index)
        self.pages.set_current_page(index)
        self.outline.current_page = index
        if self.findbar.isVisible():
            self.canvas.set_highlights(self.findbar.page_highlights(index))
        self.properties.refresh()
        self._update_actions()

    def _on_canvas_page_changed(self, index: int) -> None:
        if self.sender() is not None and self.sender() is not self.canvas:
            return
        self.pages.set_current_page(index)
        self.outline.current_page = index
        if self.findbar.isVisible():
            self.canvas.set_highlights(self.findbar.page_highlights(index))
        self.properties.refresh()
        self._update_actions()

    def _toggle_continuous(self, on: bool) -> None:
        self.settings.setValue("view/continuous", on)
        for v in self.views():
            v.canvas.set_continuous(on)

    def _apply_view_option(self, key: str, on: bool) -> None:
        names = {"rulers": "view/rulers", "guides": "view/guides", "grid": "view/grid", "snap": "view/snap",
                 "snap_objects": "view/snapObjects", "snap_grid": "view/snapGrid"}
        self.settings.setValue(names[key], on)
        for v in self.views():
            if key == "rulers":
                v.set_rulers_visible(on)
            elif key == "guides":
                v.canvas.set_snapping(show_guides=on)
            elif key == "grid":
                v.canvas.set_snapping(show_grid=on)
            elif key == "snap":
                v.canvas.set_snapping(enabled=on)
            elif key == "snap_objects":
                v.canvas.set_snapping(objects=on)
            elif key == "snap_grid":
                v.canvas.set_snapping(grid=on)

    def _target_pages(self) -> list[int]:
        sel = self.pages.selected_pages() if self.pages_dock.isVisible() else []
        if self.canvas.page_index not in sel:
            sel = [self.canvas.page_index]
        return sel

    # -- find --------------------------------------------------------------------
    def show_find(self) -> None:
        if self.doc is None:
            return
        self.findbar.show_bar()

    def _on_find_hit(self, page: int, rect) -> None:
        if page != self.canvas.page_index:
            self.go_to_page(page)
        self.canvas.set_highlights(self.findbar.page_highlights(page), rect)

    def _on_find_highlights(self, page: int, rects: list) -> None:
        if page < 0:
            self.canvas.set_highlights([])

    # -- page operations ----------------------------------------------------------
    def rotate_pages(self, delta: int) -> None:
        if self.doc:
            self.doc.rotate_pages(self._target_pages(), delta)

    def delete_pages(self) -> None:
        if not self.doc:
            return
        pages = self._target_pages()
        if len(pages) >= self.doc.page_count:
            QMessageBox.information(self, tr("Cannot delete"), tr("A document must keep at least one page."))
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
        self.doc.set_cropbox_margins(pages, left, top, right, bottom)

    def reset_crop(self) -> None:
        if self.doc:
            self.doc.reset_cropbox(self._target_pages())

    def add_page_numbers(self) -> None:
        if not self.doc:
            return
        dlg = PageNumbersDialog(self.doc.page_count, self._target_pages(), self.canvas.page_index, self)
        if dlg.exec() != PageNumbersDialog.DialogCode.Accepted:
            return
        pages = dlg.pages(dlg.scope)
        if not pages:
            return
        self.doc.add_page_numbers(pages, dlg.position.currentData(), dlg.fmt.currentText() or "{n}", dlg.start.value(), dlg.size.value(), dlg.margin.value())
        self.show_message(f"Numbered {len(pages)} page(s)")

    def add_watermark(self) -> None:
        if not self.doc:
            return
        dlg = WatermarkDialog(self.doc.page_count, self._target_pages(), self.canvas.page_index, self)
        if dlg.exec() != WatermarkDialog.DialogCode.Accepted:
            return
        pages = dlg.pages(dlg.scope)
        text = dlg.text.text().strip()
        if not pages or not text:
            return
        self.doc.add_watermark(pages, text, dlg.size.value(), dlg.color.currentData(), dlg.opacity.value() / 100.0, dlg.rotation.value())
        self.show_message(f"Watermarked {len(pages)} page(s)")

    def insert_from_file(self) -> None:
        if not self.doc:
            return
        dlg = InsertPagesDialog(self.doc.page_count, self.canvas.page_index, self)
        if dlg.exec() != InsertPagesDialog.DialogCode.Accepted:
            return
        path, pages, at = dlg.values()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, tr("Insert pages"), tr("Please choose an existing PDF file."))
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
            QMessageBox.warning(self, tr("Insert pages"), tr("No pages matched the given range."))
            return
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
            QMessageBox.warning(self, tr("Extract pages"), tr("No pages matched the given range."))
            return
        stem = os.path.splitext(self.doc.title)[0]
        start = os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}-extract.pdf")
        path, _ = QFileDialog.getSaveFileName(self, tr("Extract pages to"), start, "PDF files (*.pdf)")
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
        out_dir = QFileDialog.getExistingDirectory(self, tr("Choose output folder"), os.path.dirname(self.doc.path or ""))
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
        menu.addActions([self.act_extract, self.act_crop, self.act_uncrop, self.act_numbers, self.act_watermark])
        menu.exec(self.pages.mapToGlobal(pos))

    # -- document ------------------------------------------------------------------
    def show_properties(self) -> None:
        if not self.doc:
            return
        dlg = PropertiesDialog(self.doc, self)
        if dlg.exec() == PropertiesDialog.DialogCode.Accepted:
            self.doc.set_metadata(dlg.values())

    def show_security(self) -> None:
        if not self.doc:
            return
        dlg = SecurityDialog(self.doc, self)
        if dlg.exec() == SecurityDialog.DialogCode.Accepted:
            st = dlg.settings()
            self.doc.set_security(st)
            if st.method == "none":
                self.show_message(tr("Security will be removed when you save."))
            elif st.method != "keep":
                self.show_message(tr("Encryption will be applied when you save. Keep the password somewhere safe."))

    def show_resources(self) -> None:
        if not self.doc:
            return
        ResourcesDialog(self.doc, self, on_change=self._update_actions).exec()

    def attach_file(self) -> None:
        if not self.doc:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Attach files"))
        for p in paths:
            self.doc.add_attachment(p)
        if paths:
            self.show_message(f"Attached {len(paths)} file(s)")

    def flatten(self) -> None:
        if not self.doc:
            return
        r = QMessageBox.question(
            self, tr("Flatten"), tr("Convert all form fields and comments into fixed page content? They can no longer be edited afterwards (undo is available)."),
        )
        if r == QMessageBox.StandardButton.Yes:
            self.doc.flatten()

    def run_ocr(self) -> None:
        if not self.doc:
            return
        from quirewright.core import ocr

        if not ocr.tesseract_available():
            QMessageBox.information(self, "Recognize text", ocr.INSTALL_HINT)
            return
        dlg = OcrDialog(self.doc.page_count, self._target_pages(), self.canvas.page_index, ocr.languages(), self)
        if dlg.exec() != OcrDialog.DialogCode.Accepted:
            return
        pages = dlg.pages(dlg.scope)
        lang = dlg.language.currentText().strip() or "eng"
        done = skipped = 0
        words_total = 0
        for i in pages:
            if dlg.skip_text.isChecked() and ocr.page_has_text(self.doc, i):
                skipped += 1
                continue
            try:
                words = ocr.recognize(self.doc, i, lang, dlg.dpi.value())
            except Exception as exc:
                QMessageBox.critical(self, "Recognize text", f"OCR failed on page {i + 1}:\n\n{exc}")
                return
            words_total += ocr.add_text_layer(self.doc, i, words)
            done += 1
        self.show_message(f"OCR: {words_total} word(s) recognized on {done} page(s)" + (f", {skipped} skipped" if skipped else ""))

    def _signature_bytes(self) -> bytes:
        return self.doc.pdf.tobytes(garbage=0, deflate=False) if self.doc else b""

    def _trust_roots(self) -> list[str]:
        from quirewright.core import signing

        d = os.path.join(signing.default_cert_dir(), "trusted")
        if not os.path.isdir(d):
            return []
        return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith((".pem", ".cer", ".crt", ".der"))]

    def sign_document(self, field_name: str | None = None) -> None:
        if not self.doc:
            return
        from quirewright.core import signing

        if self.doc.is_modified:
            r = QMessageBox.question(self, tr("Sign document"), tr("The document has unsaved changes. Save it first?"))
            if r != QMessageBox.StandardButton.Yes or not self.save():
                return
        fields = [w.field_name for w in self.doc.widgets(self.canvas.page_index) if w.field_type == 6]
        if field_name and field_name in fields:
            fields.remove(field_name)
            fields.insert(0, field_name)
        dlg = SignDialog(self.doc.page_count, self.canvas.page_index, fields, self)
        if dlg.exec() != SignDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        stem = os.path.splitext(self.doc.title)[0]
        start = os.path.join(os.path.dirname(self.doc.path or ""), f"{stem}-signed.pdf")
        out, _ = QFileDialog.getSaveFileName(self, tr("Save signed document as"), start, "PDF files (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        page = self.canvas.page_index
        box = None
        field_name = None
        if v["mode"] == "field":
            field_name = v["field"]
        elif v["mode"] == "visible":
            pr = self.doc.page_rect(page)
            w, h, m = v["width"], v["height"], 24.0
            x0 = m if v["position"].endswith("l") else pr.width - m - w
            y0 = pr.height - m - h if v["position"].startswith("t") else m
            scene = Rect(x0, y0, x0 + w, y0 + h)
            inv = self.doc.pdf_to_page_matrix(page).inverted()
            box = scene.transformed(inv)
        try:
            data = self.doc.pdf.tobytes(garbage=0, deflate=False) if not self.doc.path else open(self.doc.path, "rb").read()
            signed = signing.sign_pdf(data, v["cert"], v["password"], field_name=field_name, page=page if box else None, box_pdf=box,
                                      reason=v["reason"], location=v["location"], contact=v["contact"], certify=v["certify"])
            with open(out, "wb") as fh:
                fh.write(signed)
        except Exception as exc:
            QMessageBox.critical(self, tr("Sign document"), tr("Signing failed:\n\n{error}").format(error=exc))
            return
        self.open_file(out)
        self.show_message(tr("Signed document saved as {name}").format(name=os.path.basename(out)))

    def show_signatures(self) -> None:
        if not self.doc:
            return
        from quirewright.core import signing

        data = open(self.doc.path, "rb").read() if self.doc.path and not self.doc.is_modified else self._signature_bytes()
        sigs = signing.signatures(data, self._trust_roots())
        SignaturesDialog(sigs, self._add_trusted_certificate, self).exec()

    def _add_trusted_certificate(self, parent=None) -> None:
        from quirewright.core import signing

        p, _ = QFileDialog.getOpenFileName(parent or self, tr("Choose certificate to trust"), "", "Certificates (*.pem *.cer *.crt *.der);;All files (*)")
        if not p:
            return
        d = os.path.join(signing.default_cert_dir(), "trusted")
        os.makedirs(d, exist_ok=True)
        import shutil

        shutil.copy(p, os.path.join(d, os.path.basename(p)))
        self.show_message(tr("Certificate added to the trust store. Reopen the Signatures dialog to re-check."))

    def _confirm_area_tool(self, tool: str, rect: QRectF) -> bool:
        if tool == TOOL_REDACT:
            r = QMessageBox.warning(
                self, tr("Redact"), tr("Permanently remove all text and images inside the rectangle and paint it black?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            return r == QMessageBox.StandardButton.Yes
        return True

    # -- edit ---------------------------------------------------------------
    def undo(self) -> None:
        if self.doc:
            self.doc.undo_stack.undo()

    def redo(self) -> None:
        if self.doc:
            self.doc.undo_stack.redo()

    def copy_text(self) -> None:
        text = self.canvas.copy_selected_text()
        if text:
            self.show_message(f"Copied {len(text)} character(s)")

    def insert_image(self) -> None:
        if not self.doc:
            return
        start = self.settings.value("files/lastImageDir", "")
        path, _ = QFileDialog.getOpenFileName(self, tr("Insert image"), start, "Images (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp *.svg);;All files (*)")
        if not path:
            return
        self.settings.setValue("files/lastImageDir", os.path.dirname(path))
        self.canvas.set_tool(TOOL_SELECT)
        self.canvas.insert_image(path)

    def edit_selected_text(self) -> None:
        if len(self.canvas.selection) >= 1:
            self.canvas.begin_text_edit(self.canvas.selection[0])

    def edit_selected_paragraph(self) -> None:
        if len(self.canvas.selection) >= 1:
            self.canvas.begin_paragraph_edit(self.canvas.selection[0])

    def edit_page_labels(self) -> None:
        if not self.doc:
            return
        dlg = PageLabelsDialog(self.doc.page_count, self.doc.page_label_rules(), self)
        if dlg.exec() == PageLabelsDialog.DialogCode.Accepted:
            self.doc.set_page_label_rules(dlg.rules())

    def _toggle_scale_stroke(self, on: bool) -> None:
        self.settings.setValue("edit/scaleStroke", on)
        for v in self.views():
            v.canvas.scale_stroke = on

    def show_preferences(self) -> None:
        dlg = PreferencesDialog(self)
        if dlg.exec() != PreferencesDialog.DialogCode.Accepted:
            return
        res = dlg.apply()

        if res.get("language") and res["language"] != self.settings.value("ui/languageApplied", "system", type=str):
            self.settings.setValue("ui/languageApplied", res["language"])
            QMessageBox.information(self, tr("Language"), tr("The new language is used after you restart the application."))
        t = res["theme"]
        dark = theme.system_prefers_dark() if t == "system" else (t == "dark")
        if dark != theme.current().dark:
            self.act_dark.setChecked(dark)
            self.toggle_dark(dark, persist=False)
        self.act_scale_stroke.setChecked(res["scale_stroke"])
        for v in self.views():
            v.canvas.scale_stroke = res["scale_stroke"]
            v.canvas.author = self.settings.value("user/author", "", type=str)
            v.canvas.set_snapping(grid_size=self.settings.value("view/gridSize", 10.0, type=float))
            v.canvas.snap_tolerance_px = self.settings.value("view/snapTolerance", 6.0, type=float)
            v.refresh_rulers()
        self.properties.refresh_units()

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self.findChildren(QAction), self).exec()

    def open_guide(self, section: str | None = None) -> None:
        if getattr(self, "help_window", None) is None:
            self.help_window = HelpWindow(self)
        self.help_window.show()
        self.help_window.raise_()
        self.help_window.activateWindow()
        if section:
            self.help_window.show_section(section)

    # -- theme ---------------------------------------------------------------
    def toggle_dark(self, on: bool, persist: bool = True) -> None:
        app = QApplication.instance()
        theme.apply_theme(app, on)
        if persist:
            self.settings.setValue("ui/dark", on)
        self._refresh_icons()
        for v in self.views():
            v.apply_theme()
        self._placeholder_view.apply_theme()
        self.pages.refresh()
        self.properties.refresh()
        self.welcome.refresh_theme()
        if getattr(self, "help_window", None) is not None:
            self.help_window.reload()

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
