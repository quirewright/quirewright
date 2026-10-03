"""The page canvas: renders a page and overlays editable objects.

The scene coordinate system is PyMuPDF's page space in points (origin at the
top-left of the rotated, cropped page, y down). The rendered page bitmap is
placed as a pixmap item scaled back to points; selectable objects and form
fields get invisible hit-test items on top, plus a selection frame with scale
handles, a node editor for paths, drawing previews, and an inline text editor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTransform,
    QWheelEvent,
)
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLineEdit,
    QPlainTextEdit,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pdfeditor.core.content.model import Color, GObject, PathObject, TextRun, XObjectRef
from pdfeditor.core.content.writer import ContentEditor, wrap_text
from pdfeditor.core.annotations import AnnotInfo
from pdfeditor.core.document import Document, WidgetInfo
from pdfeditor.core.geometry import Matrix, Rect
from pdfeditor.ui import theme
from pdfeditor.ui.render import RenderCache, render_page

TOOL_SELECT = "select"
TOOL_NODE = "node"
TOOL_TEXT = "text"
TOOL_HAND = "hand"
TOOL_RECT = "rect"
TOOL_ELLIPSE = "ellipse"
TOOL_LINE = "line"
TOOL_PEN = "pen"
TOOL_FIELD = "field"  # followed by ":<type>", e.g. "field:7"
TOOL_MARKUP = "markup"  # followed by ":highlight" / ":underline" / ":strikeout"
TOOL_NOTE = "note"
TOOL_CROP = "crop"
TOOL_REDACT = "redact"

DRAW_TOOLS = (TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE, TOOL_PEN)
AREA_TOOLS = (TOOL_CROP, TOOL_REDACT)

PAGE_GAP = 24.0
HANDLE_PX = 8.0
MIN_ZOOM = 0.1
MAX_ZOOM = 16.0
KAPPA = 0.5522847498


def qmatrix(m: Matrix) -> QTransform:
    return QTransform(m.a, m.b, m.c, m.d, m.e, m.f)


def from_qtransform(t: QTransform) -> Matrix:
    return Matrix(t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def rect_to_qrect(r: Rect) -> QRectF:
    return QRectF(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0)


def qrect_to_rect(r: QRectF) -> Rect:
    return Rect.normalized(r.left(), r.top(), r.right(), r.bottom())


@dataclass
class DrawStyle:
    """Defaults used when creating new objects."""

    fill: Color | None = Color("DeviceRGB", (0.85, 0.9, 1.0))
    stroke: Color | None = Color("DeviceRGB", (0.15, 0.35, 0.8))
    line_width: float = 1.5
    font: str = "helv"
    font_size: float = 12.0
    text_color: Color = Color("DeviceGray", (0.0,))


# --- overlay items -----------------------------------------------------------

class ObjectItem(QGraphicsItem):
    """Hit-test and highlight proxy for one editable content object."""

    def __init__(self, obj: GObject, path: QPainterPath, hit_shape: QPainterPath):
        super().__init__()
        self.obj = obj
        self._path = path
        self._shape = hit_shape
        self._bounds = hit_shape.boundingRect().adjusted(-1, -1, 1, 1)
        self.hovered = False
        self.selected_flag = False
        self.setAcceptHoverEvents(True)
        self.setZValue(10 + obj.sequence * 1e-6)

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        return self._shape

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()

    def set_selected(self, on: bool) -> None:
        if self.selected_flag != on:
            self.selected_flag = on
            self.update()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if not (self.hovered or self.selected_flag):
            return
        t = theme.current()
        if isinstance(self.obj, TextRun) and self.obj.invisible:
            pen = QPen(QColor(t.text_muted), 0, Qt.PenStyle.DashLine)
        elif self.selected_flag:
            pen = QPen(QColor(t.selection), 0)
        else:
            pen = QPen(QColor(t.hover), 0)
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)


class WidgetItem(QGraphicsItem):
    """Hit-test and highlight proxy for a form field (widget annotation)."""

    def __init__(self, info: WidgetInfo, offset: QPointF | None = None):
        super().__init__()
        self.info = info
        self.rect = rect_to_qrect(info.rect).translated(offset or QPointF())
        self.hovered = False
        self.selected_flag = False
        self.show_tint = False
        self.setAcceptHoverEvents(True)
        self.setZValue(50)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1, -1, 1, 1)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRect(self.rect)
        return p

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()

    def set_selected(self, on: bool) -> None:
        if self.selected_flag != on:
            self.selected_flag = on
            self.update()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = theme.current()
        if self.show_tint:
            c = QColor(t.accent)
            c.setAlpha(28)
            painter.fillRect(self.rect, c)
        if not (self.hovered or self.selected_flag or self.show_tint):
            return
        pen = QPen(QColor(t.selection if self.selected_flag else t.hover), 0, Qt.PenStyle.DashLine if not self.selected_flag else Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect)


class AnnotItem(QGraphicsItem):
    """Hit-test and highlight proxy for an annotation (comment)."""

    def __init__(self, info: AnnotInfo, offset: QPointF | None = None):
        super().__init__()
        self.info = info
        self.rect = rect_to_qrect(info.rect).translated(offset or QPointF())
        self.hovered = False
        self.selected_flag = False
        self.setAcceptHoverEvents(True)
        self.setZValue(60)
        self.setToolTip(f"{info.type_name}" + (f" — {info.author}" if info.author else "") + (f"\n{info.contents}" if info.contents else ""))

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1, -1, 1, 1)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRect(self.rect)
        return p

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()

    def set_selected(self, on: bool) -> None:
        if self.selected_flag != on:
            self.selected_flag = on
            self.update()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if not (self.hovered or self.selected_flag):
            return
        t = theme.current()
        pen = QPen(QColor(t.selection if self.selected_flag else t.hover), 0, Qt.PenStyle.SolidLine if self.selected_flag else Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect)


class GridItem(QGraphicsItem):
    """Light grid drawn over the active page."""

    def __init__(self, rect: QRectF, step: float):
        super().__init__()
        self.rect = QRectF(rect)
        self.step = step
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        return self.rect

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = theme.current()
        pen = QPen(QColor(t.accent), 0)
        pen.setCosmetic(True)
        c = QColor(t.accent)
        c.setAlpha(45)
        pen.setColor(c)
        painter.setPen(pen)
        r = self.rect
        x = r.left()
        n = 0
        while x <= r.right() + 1e-6 and n < 5000:
            painter.drawLine(QLineF(x, r.top(), x, r.bottom()))
            x += self.step
            n += 1
        y = r.top()
        n = 0
        while y <= r.bottom() + 1e-6 and n < 5000:
            painter.drawLine(QLineF(r.left(), y, r.right(), y))
            y += self.step
            n += 1


class SelectionFrame(QGraphicsItem):
    """Bounding box of the current selection with eight scale handles."""

    def __init__(self):
        super().__init__()
        self.rect = QRectF()
        self.zoom = 1.0
        self.setZValue(1000)
        self.setVisible(False)

    def set_rect(self, rect: QRectF, zoom: float) -> None:
        self.prepareGeometryChange()
        self.rect = rect
        self.zoom = zoom
        self.setVisible(not rect.isNull())
        self.update()

    def handle_size(self) -> float:
        return HANDLE_PX / max(self.zoom, 1e-6)

    def handle_points(self) -> dict[str, QPointF]:
        r = self.rect
        c = r.center()
        return {
            "nw": r.topLeft(), "n": QPointF(c.x(), r.top()), "ne": r.topRight(), "e": QPointF(r.right(), c.y()),
            "se": r.bottomRight(), "s": QPointF(c.x(), r.bottom()), "sw": r.bottomLeft(), "w": QPointF(r.left(), c.y()),
        }

    def handle_at(self, pos: QPointF) -> str | None:
        if not self.isVisible():
            return None
        hs = self.handle_size() * 0.75
        for name, pt in self.handle_points().items():
            if abs(pos.x() - pt.x()) <= hs and abs(pos.y() - pt.y()) <= hs:
                return name
        return None

    def boundingRect(self) -> QRectF:
        m = self.handle_size()
        return self.rect.adjusted(-m, -m, m, m)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if self.rect.isNull():
            return
        t = theme.current()
        pen = QPen(QColor(t.selection), 0)
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect)
        hs = self.handle_size() / 2
        painter.setBrush(QBrush(QColor(t.handle_fill)))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        for pt in self.handle_points().values():
            painter.drawRect(QRectF(pt.x() - hs, pt.y() - hs, 2 * hs, 2 * hs))


class NodeOverlay(QGraphicsItem):
    """Editable anchors and bezier handles for a single path object."""

    def __init__(self, obj: PathObject, user_to_scene: QTransform, zoom: float):
        super().__init__()
        self.obj = obj
        self.subpaths: list[list[tuple]] = [list(sp) for sp in obj.subpaths]
        self.u2s = user_to_scene
        self.s2u, _ = user_to_scene.inverted()
        self.zoom = zoom
        self.active: tuple[int, int, int] | None = None
        self.hover: tuple[int, int, int] | None = None
        self.setZValue(2000)
        self.setAcceptHoverEvents(True)

    def points(self):
        for si, sp in enumerate(self.subpaths):
            for gi, seg in enumerate(sp):
                op = seg[0]
                if op == "h":
                    continue
                n = (len(seg) - 1) // 2
                for pi in range(n):
                    x, y = seg[1 + 2 * pi], seg[2 + 2 * pi]
                    yield si, gi, pi, x, y, (op != "c" or pi == 2)

    def scene_point(self, x: float, y: float) -> QPointF:
        return self.u2s.map(QPointF(x, y))

    def handle_radius(self) -> float:
        return 5.0 / max(self.zoom, 1e-6)

    def point_at(self, pos: QPointF) -> tuple[int, int, int] | None:
        r = self.handle_radius() * 1.4
        best = None
        best_d = r
        for si, gi, pi, x, y, anchor in self.points():
            p = self.scene_point(x, y)
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d <= best_d:
                best_d = d
                best = (si, gi, pi)
        return best

    def move_point(self, key: tuple[int, int, int], pos: QPointF) -> None:
        si, gi, pi = key
        u = self.s2u.map(pos)
        seg = list(self.subpaths[si][gi])
        old_x, old_y = seg[1 + 2 * pi], seg[2 + 2 * pi]
        seg[1 + 2 * pi], seg[2 + 2 * pi] = u.x(), u.y()
        self.subpaths[si][gi] = tuple(seg)
        is_anchor = seg[0] != "c" or pi == 2
        if is_anchor:
            dx, dy = u.x() - old_x, u.y() - old_y
            if seg[0] == "c":
                s2 = list(self.subpaths[si][gi])
                s2[3], s2[4] = s2[3] + dx, s2[4] + dy
                self.subpaths[si][gi] = tuple(s2)
            nxt = gi + 1
            if nxt < len(self.subpaths[si]) and self.subpaths[si][nxt][0] == "c":
                s3 = list(self.subpaths[si][nxt])
                s3[1], s3[2] = s3[1] + dx, s3[2] + dy
                self.subpaths[si][nxt] = tuple(s3)
        self.prepareGeometryChange()
        self.update()

    def painter_path(self) -> QPainterPath:
        return subpaths_to_qpath(self.subpaths, self.u2s)

    def boundingRect(self) -> QRectF:
        m = self.handle_radius() * 3
        return self.painter_path().boundingRect().adjusted(-m, -m, m, m)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = theme.current()
        pen = QPen(QColor(t.selection), 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.painter_path())
        r = self.handle_radius()
        thin = QPen(QColor(t.hover), 0, Qt.PenStyle.DashLine)
        thin.setCosmetic(True)
        for si, sp in enumerate(self.subpaths):
            prev: tuple[float, float] | None = None
            for gi, seg in enumerate(sp):
                if seg[0] == "c":
                    painter.setPen(thin)
                    if prev is not None:
                        painter.drawLine(self.scene_point(*prev), self.scene_point(seg[1], seg[2]))
                    painter.drawLine(self.scene_point(seg[5], seg[6]), self.scene_point(seg[3], seg[4]))
                if seg[0] != "h":
                    prev = (seg[-2], seg[-1])
        for si, gi, pi, x, y, anchor in self.points():
            p = self.scene_point(x, y)
            key = (si, gi, pi)
            fill = QColor(t.selection) if key == self.active else QColor(t.handle_fill)
            if key == self.hover:
                fill = QColor(t.hover)
            painter.setBrush(QBrush(fill))
            painter.setPen(pen)
            if anchor:
                painter.drawRect(QRectF(p.x() - r, p.y() - r, 2 * r, 2 * r))
            else:
                painter.drawEllipse(p, r * 0.8, r * 0.8)


def subpaths_to_qpath(subpaths, transform: QTransform) -> QPainterPath:
    path = QPainterPath()
    for sp in subpaths:
        for seg in sp:
            op = seg[0]
            if op == "m":
                path.moveTo(transform.map(QPointF(seg[1], seg[2])))
            elif op == "l":
                path.lineTo(transform.map(QPointF(seg[1], seg[2])))
            elif op == "c":
                path.cubicTo(
                    transform.map(QPointF(seg[1], seg[2])),
                    transform.map(QPointF(seg[3], seg[4])),
                    transform.map(QPointF(seg[5], seg[6])),
                )
            elif op == "h":
                path.closeSubpath()
    return path


def ellipse_subpath(r: QRectF) -> list[tuple]:
    """Four-bezier approximation of an ellipse inscribed in ``r`` (scene space)."""
    cx, cy = r.center().x(), r.center().y()
    rx, ry = r.width() / 2, r.height() / 2
    kx, ky = rx * KAPPA, ry * KAPPA
    return [
        ("m", cx + rx, cy),
        ("c", cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry),
        ("c", cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy),
        ("c", cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry),
        ("c", cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy),
        ("h",),
    ]


def transform_subpaths(subpaths, m: Matrix):
    out = []
    for sp in subpaths:
        new = []
        for seg in sp:
            if seg[0] == "h":
                new.append(seg)
                continue
            vals = [seg[0]]
            for i in range(1, len(seg), 2):
                vals.extend(m.apply(seg[i], seg[i + 1]))
            new.append(tuple(vals))
        out.append(new)
    return out


# --- drag state --------------------------------------------------------------

@dataclass
class DragState:
    mode: str  # "move", "scale", "rubber", "pan", "node", "create"
    start: QPointF
    last: QPointF = field(default_factory=QPointF)
    handle: str | None = None
    anchor: QPointF = field(default_factory=QPointF)
    frame_rect: QRectF = field(default_factory=QRectF)
    moved: bool = False
    node_key: tuple[int, int, int] | None = None


# --- the canvas ----------------------------------------------------------------

class PageCanvas(QGraphicsView):
    selectionChanged = Signal(list)
    zoomChanged = Signal(float)
    statusMessage = Signal(str)
    pageEdited = Signal(int)
    toolChanged = Signal(str)
    pageChanged = Signal(int)  # active page changed by clicking/scrolling
    cursorMoved = Signal(QPointF)  # scene position of the mouse (for rulers)
    viewChanged = Signal()  # zoom or scroll changed (for rulers)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.doc: Document | None = None
        self.page_index = 0
        self.zoom = 1.0
        self.tool = TOOL_SELECT
        self.cache = RenderCache()
        self.generation = 0
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.page_item: QGraphicsPixmapItem | None = None
        self.continuous = True
        self.page_items: dict[int, QGraphicsPixmapItem] = {}
        self.page_placeholders: dict[int, QGraphicsRectItem] = {}
        self.page_scales: dict[int, float] = {}
        self.page_rects: list[QRectF] = []  # scene rect of every laid-out page
        self.page_offset = QPointF()
        self.layout_rect = QRectF(0, 0, 1, 1)
        self.items_by_id: dict[int, ObjectItem] = {}
        self.widget_items: dict[int, WidgetItem] = {}
        self.annot_items: dict[int, AnnotItem] = {}
        self.selection: list[int] = []
        self.widget_selection: list[int] = []
        self.annot_selection: list[int] = []
        self.highlight_items: list[QGraphicsRectItem] = []
        self.highlights: list[Rect] = []
        self.current_highlight: Rect | None = None
        self.author = ""
        self.confirm_area = None  # callable(tool, QRectF) -> bool, set by the main window
        self.frame = SelectionFrame()
        self._scene.addItem(self.frame)
        self.node_overlay: NodeOverlay | None = None
        self.text_proxy: QGraphicsProxyWidget | None = None
        self.text_edit_ids: list[int] = []
        self.text_edit_new: QPointF | None = None
        self.text_box: QRectF | None = None  # new text box being created (scene)
        self.paragraph: dict | None = None  # paragraph being edited
        self.pen_handles: list[QPointF | None] = []  # out-handle per pen point (None = corner)
        self.rubber: QGraphicsRectItem | None = None
        self.preview: QGraphicsItem | None = None
        self.pen_points: list[QPointF] = []
        self.pen_preview: QGraphicsPathItem | None = None
        self.drag: DragState | None = None
        self.pdf_to_scene = Matrix()
        self.page_rect = QRectF(0, 0, 612, 792)
        self.scale_stroke = True
        self.draw_style = DrawStyle()
        self._select_new_after_rebuild = False
        self.edit_path: list[tuple[int, Matrix, str]] = []  # (form xref, base matrix, name) when editing inside a form
        self.context_items: list[QGraphicsItem] = []
        # snapping & guides
        self.snap_enabled = True
        self.snap_objects = True
        self.snap_grid = False
        self.show_grid = False
        self.show_guides = True
        self.grid_size = 10.0  # points, page-local
        self.snap_tolerance_px = 6.0
        self.guides: dict[int, list[tuple[str, float]]] = {}  # page -> [(orientation, page-local coord)]
        self.guide_items: list[QGraphicsLineItem] = []
        self.grid_item: QGraphicsItem | None = None
        self.smart_items: list[QGraphicsLineItem] = []
        self.guide_preview_item: QGraphicsLineItem | None = None
        self._guide_drag: tuple[int, str] | None = None  # (index in page guide list, orientation)
        self._snap_targets: tuple[list[float], list[float]] | None = None

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render_now)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._on_scrolled)
        self.verticalScrollBar().valueChanged.connect(lambda v: (self._scroll_timer.start(), self.viewChanged.emit()))
        self.horizontalScrollBar().valueChanged.connect(lambda v: (self._scroll_timer.start(), self.viewChanged.emit()))

        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.apply_theme()

    # -- setup -----------------------------------------------------------
    def apply_theme(self) -> None:
        t = theme.current()
        self.setBackgroundBrush(QBrush(QColor(t.canvas)))
        self.viewport().update()

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.remove_listener(self._on_doc_event)
        self.doc = doc
        self.cache.clear()
        self.page_index = 0
        self.selection = []
        self.widget_selection = []
        self.annot_selection = []
        self.edit_path = []
        self.highlights = []
        self.current_highlight = None
        if doc is not None:
            doc.add_listener(self._on_doc_event)
        self.rebuild()

    def _on_doc_event(self, event: str, payload) -> None:
        if event == "page_content":
            self.cache.drop_page(payload)
            self.page_scales.pop(payload, None)
            if payload == self.page_index:
                self.rebuild(keep_selection=True)
            else:
                self._render_now()
        elif event in ("pages", "saved"):
            self.cache.clear()
            if self.doc is not None and self.page_index >= self.doc.page_count:
                self.page_index = max(0, self.doc.page_count - 1)
            self.rebuild(keep_selection=True)

    def set_page(self, index: int, scroll: bool = True) -> None:
        if self.doc is None:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        if index == self.page_index:
            if scroll and self.continuous:
                self.scroll_to_page(index)
            return
        self.page_index = index
        self.selection = []
        self.widget_selection = []
        self.annot_selection = []
        self.edit_path = []
        if self.continuous and self.page_items:
            self._activate_page(index)
            if scroll:
                self.scroll_to_page(index)
        else:
            self.rebuild()
        self.selectionChanged.emit([])

    def set_continuous(self, on: bool) -> None:
        if on == self.continuous:
            return
        self.continuous = on
        self.rebuild()
        if on:
            self.scroll_to_page(self.page_index)

    def scroll_to_page(self, index: int) -> None:
        if 0 <= index < len(self.page_rects):
            r = self.page_rects[index]
            self._scroll_timer.stop()
            self.verticalScrollBar().setValue(int((r.top() - PAGE_GAP / 2) * self.zoom - self.sceneRect().top() * self.zoom))
            self.horizontalScrollBar().setValue(int((r.center().x() * self.zoom) - self.viewport().width() / 2 - self.sceneRect().left() * self.zoom))
            self._scroll_timer.stop()
            self._last_scroll = (self.verticalScrollBar().value(), self.horizontalScrollBar().value())
            self._render_now()

    def page_at(self, pos: QPointF) -> int | None:
        for i, r in enumerate(self.page_rects):
            if r.adjusted(0, -PAGE_GAP / 2, 0, PAGE_GAP / 2).contains(pos):
                return i
        return None

    def _page_under_viewport(self) -> int | None:
        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        probe = QPointF(vp.center().x(), vp.top() + min(vp.height() * 0.35, 200 / max(self.zoom, 1e-6)))
        best, best_overlap = None, 0.0
        for i, r in enumerate(self.page_rects):
            inter = r.intersected(vp)
            if r.contains(probe):
                return i
            overlap = inter.height() if not inter.isEmpty() else 0.0
            if overlap > best_overlap:
                best, best_overlap = i, overlap
        return best

    def _on_scrolled(self) -> None:
        if self.doc is None or not self.continuous:
            return
        self._render_now()
        if self.drag is not None or self.text_proxy is not None:
            return
        pos = (self.verticalScrollBar().value(), self.horizontalScrollBar().value())
        if pos == getattr(self, "_last_scroll", None):
            return
        self._last_scroll = pos
        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        if self.page_rects and 0 <= self.page_index < len(self.page_rects):
            cur = self.page_rects[self.page_index]
            visible = cur.intersected(vp)
            # keep the active page while a good part of it is still on screen
            if not visible.isEmpty() and (visible.height() >= 0.3 * vp.height() or visible.height() >= 0.9 * cur.height()):
                return
        i = self._page_under_viewport()
        if i is not None and i != self.page_index:
            self.page_index = i
            self.selection = []
            self.widget_selection = []
            self.annot_selection = []
            self.edit_path = []
            self._activate_page(i)
            self.selectionChanged.emit([])
            self.pageChanged.emit(i)

    # -- local <-> scene helpers (scene = page-local + page offset) ------------
    def to_local_rect(self, r: QRectF) -> Rect:
        return qrect_to_rect(r.translated(-self.page_offset))

    def to_local_point(self, p: QPointF) -> tuple[float, float]:
        return (p.x() - self.page_offset.x(), p.y() - self.page_offset.y())

    def to_local_matrix(self, m: Matrix) -> Matrix:
        off = self.page_offset
        return Matrix.translation(off.x(), off.y()) * m * Matrix.translation(-off.x(), -off.y())

    def set_tool(self, tool: str) -> None:
        if tool == self.tool:
            return
        self._end_text_edit(commit=False)
        self._cancel_pen()
        self.tool = tool
        if tool in DRAW_TOOLS or tool in AREA_TOOLS or tool in (TOOL_TEXT, TOOL_NOTE) or self.is_field_tool or self.is_markup_tool:
            self.selection = []
            self.widget_selection = []
            self.annot_selection = []
            self._update_selection_visuals()
            self.selectionChanged.emit([])
        self._update_node_overlay()
        self._update_cursor()
        self._update_widget_tint()
        self.toolChanged.emit(tool)

    @property
    def is_field_tool(self) -> bool:
        return self.tool.startswith(TOOL_FIELD)

    @property
    def is_markup_tool(self) -> bool:
        return self.tool.startswith(TOOL_MARKUP)

    def markup_kind(self) -> str:
        return self.tool.split(":", 1)[1] if ":" in self.tool else "highlight"

    def field_tool_type(self) -> int:
        try:
            return int(self.tool.split(":", 1)[1])
        except (IndexError, ValueError):
            return 7

    def _update_cursor(self) -> None:
        if self.tool == TOOL_HAND:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.tool == TOOL_TEXT:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        elif self.tool in DRAW_TOOLS or self.tool in AREA_TOOLS or self.is_field_tool or self.is_markup_tool:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        elif self.tool == TOOL_NOTE:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _update_widget_tint(self) -> None:
        tint = self.is_field_tool
        for it in self.widget_items.values():
            if it.show_tint != tint:
                it.show_tint = tint
                it.update()

    # -- building the scene ---------------------------------------------
    def rebuild(self, keep_selection: bool = False) -> None:
        self._end_text_edit(commit=False)
        self._cancel_pen()
        old_selection = list(self.selection) if keep_selection else []
        old_widgets = list(self.widget_selection) if keep_selection else []
        old_annots = list(self.annot_selection) if keep_selection else []
        self._scene.removeItem(self.frame)
        self._scene.clear()
        self.items_by_id = {}
        self.widget_items = {}
        self.annot_items = {}
        self.highlight_items = []
        self.page_items = {}
        self.page_placeholders = {}
        self.page_scales = {}
        self.page_rects = []
        self.page_item = None
        self.node_overlay = None
        self.text_proxy = None
        self.rubber = None
        self.preview = None
        self.pen_preview = None
        self._scene.addItem(self.frame)
        self.frame.set_rect(QRectF(), self.zoom)
        if self.doc is None or self.doc.page_count == 0:
            self.layout_rect = QRectF(0, 0, 1, 1)
            self._scene.setSceneRect(self.layout_rect)
            self.viewport().update()
            return
        self._layout_pages()
        self._activate_page(self.page_index, old_selection, old_widgets, old_annots)
        self._render_now()

    def _layout_pages(self) -> None:
        assert self.doc is not None
        n = self.doc.page_count
        indices = list(range(n)) if self.continuous else [self.page_index]
        rects = [self.doc.page_rect(i) for i in indices]
        max_w = max((r.width for r in rects), default=1.0)
        y = 0.0
        self.page_rects = [QRectF() for _ in range(n)]
        t = theme.current()
        for i, r in zip(indices, rects):
            x = (max_w - r.width) / 2 if self.continuous else 0.0
            scene_rect = QRectF(x, y, r.width, r.height)
            self.page_rects[i] = scene_rect
            shadow = QGraphicsRectItem(scene_rect.translated(2, 3))
            shadow.setBrush(QBrush(QColor(0, 0, 0, 40)))
            shadow.setPen(Qt.PenStyle.NoPen)
            shadow.setZValue(-3)
            self._scene.addItem(shadow)
            placeholder = QGraphicsRectItem(scene_rect)
            placeholder.setBrush(QBrush(QColor("#ffffff" if not t.dark else "#f3f4f6")))
            placeholder.setPen(Qt.PenStyle.NoPen)
            placeholder.setZValue(-2)
            self._scene.addItem(placeholder)
            self.page_placeholders[i] = placeholder
            item = QGraphicsPixmapItem()
            item.setZValue(-1)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setPos(scene_rect.topLeft())
            self._scene.addItem(item)
            self.page_items[i] = item
            y += r.height + PAGE_GAP
        total_h = max(y - PAGE_GAP, 1.0)
        self.layout_rect = QRectF(0, 0, max_w, total_h)
        margin = 40 / max(self.zoom, 0.2)
        self._scene.setSceneRect(self.layout_rect.adjusted(-margin, -margin, margin, margin))

    def _clear_overlay(self) -> None:
        for coll in (self.items_by_id, self.widget_items, self.annot_items):
            for it in coll.values():
                try:
                    self._scene.removeItem(it)
                except RuntimeError:
                    pass
            coll.clear()
        for it in self.highlight_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.highlight_items = []
        if self.node_overlay is not None:
            self._scene.removeItem(self.node_overlay)
            self.node_overlay = None
        for it in self.guide_items + self.smart_items + self.context_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.guide_items = []
        self.smart_items = []
        self.context_items = []
        if self.grid_item is not None:
            try:
                self._scene.removeItem(self.grid_item)
            except RuntimeError:
                pass
            self.grid_item = None

    def _activate_page(self, index: int, old_selection=None, old_widgets=None, old_annots=None) -> None:
        """Make ``index`` the editable page: (re)build its overlay in place."""
        assert self.doc is not None
        self._end_text_edit(commit=False)
        self._cancel_pen()
        self._clear_overlay()
        self.page_index = index
        if not self.continuous and (not self.page_rects or self.page_rects[index].isNull()):
            self._layout_pages()
        self.page_rect = QRectF(self.page_rects[index])
        self.page_offset = self.page_rect.topLeft()
        self.page_item = self.page_items.get(index)
        base = self.doc.pdf_to_page_matrix(index)
        self.pdf_to_scene = base * Matrix.translation(self.page_offset.x(), self.page_offset.y())
        self._build_overlay()
        self._build_widgets()
        self._build_annots()
        self._build_highlights()
        self._build_guides()
        self._build_grid()
        self._build_context_overlay()
        if self._select_new_after_rebuild and self.items_by_id:
            self._select_new_after_rebuild = False
            self.selection = [max(self.items_by_id)]
            self.widget_selection = []
            self.annot_selection = []
        else:
            self.selection = [i for i in (old_selection or []) if i in self.items_by_id]
            self.widget_selection = [x for x in (old_widgets or []) if x in self.widget_items]
            self.annot_selection = [x for x in (old_annots or []) if x in self.annot_items]
        self._update_selection_visuals()
        self._update_node_overlay()
        self._update_widget_tint()

    def _build_overlay(self) -> None:
        assert self.doc is not None
        try:
            content = self.doc.content(self.page_index, self.doc_path())
        except Exception as exc:  # pragma: no cover
            self.statusMessage.emit(f"Could not parse page content: {exc}")
            self.edit_path = []
            content = self.doc.content(self.page_index)
        S = qmatrix(self.pdf_to_scene)
        for obj in content.objects:
            if not obj.selectable or obj.visible_bbox is None:
                continue
            path, hit = self._object_geometry(obj, S)
            if path is None:
                continue
            item = ObjectItem(obj, path, hit)
            self._scene.addItem(item)
            self.items_by_id[obj.id] = item
        if content.warnings:
            self.statusMessage.emit(f"{len(content.warnings)} content warnings on this page")

    def _build_widgets(self) -> None:
        assert self.doc is not None
        for info in self.doc.widgets(self.page_index):
            item = WidgetItem(info, self.page_offset)
            self._scene.addItem(item)
            self.widget_items[info.xref] = item

    def _build_annots(self) -> None:
        assert self.doc is not None
        for info in self.doc.annotations(self.page_index):
            item = AnnotItem(info, self.page_offset)
            self._scene.addItem(item)
            self.annot_items[info.xref] = item

    # -- guides & grid -------------------------------------------------------------
    def page_guides(self) -> list[tuple[str, float]]:
        return self.guides.setdefault(self.page_index, [])

    def _guide_pen(self, preview: bool = False) -> QPen:
        t = theme.current()
        pen = QPen(QColor("#22c55e" if not preview else t.accent), 0, Qt.PenStyle.DashLine if preview else Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        return pen

    def _guide_line(self, orientation: str, local: float) -> QLineF:
        r = self.page_rect
        if orientation == "h":
            y = self.page_offset.y() + local
            return QLineF(r.left(), y, r.right(), y)
        x = self.page_offset.x() + local
        return QLineF(x, r.top(), x, r.bottom())

    def _build_guides(self) -> None:
        for it in self.guide_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.guide_items = []
        if not self.show_guides or self.doc is None:
            return
        for orientation, local in self.page_guides():
            item = QGraphicsLineItem(self._guide_line(orientation, local))
            item.setPen(self._guide_pen())
            item.setZValue(4)
            self._scene.addItem(item)
            self.guide_items.append(item)

    def _build_grid(self) -> None:
        if self.grid_item is not None:
            try:
                self._scene.removeItem(self.grid_item)
            except RuntimeError:
                pass
            self.grid_item = None
        if not self.show_grid or self.doc is None or self.grid_size <= 0:
            return
        self.grid_item = GridItem(self.page_rect, self.grid_size)
        self._scene.addItem(self.grid_item)

    def add_guide(self, orientation: str, scene_value: float) -> None:
        """Add a guide at a scene coordinate (converted to the active page's local space)."""
        local = scene_value - (self.page_offset.y() if orientation == "h" else self.page_offset.x())
        limit = self.page_rect.height() if orientation == "h" else self.page_rect.width()
        if local < -1 or local > limit + 1:
            return
        self.page_guides().append((orientation, local))
        self.show_guides = True
        self._build_guides()
        self.statusMessage.emit(f"Guide added at {local:.1f} pt · drag it off the page to remove")

    def clear_guides(self, all_pages: bool = False) -> None:
        if all_pages:
            self.guides.clear()
        else:
            self.guides.pop(self.page_index, None)
        self._build_guides()

    def set_guide_preview(self, orientation: str, scene_value) -> None:
        if self.guide_preview_item is not None:
            try:
                self._scene.removeItem(self.guide_preview_item)
            except RuntimeError:
                pass
            self.guide_preview_item = None
        if scene_value is None:
            return
        local = scene_value - (self.page_offset.y() if orientation == "h" else self.page_offset.x())
        item = QGraphicsLineItem(self._guide_line(orientation, local))
        item.setPen(self._guide_pen(preview=True))
        item.setZValue(4000)
        self._scene.addItem(item)
        self.guide_preview_item = item

    def _guide_at(self, pos: QPointF) -> int | None:
        if not self.show_guides:
            return None
        tol = self.snap_tolerance_px / max(self.zoom, 1e-6)
        for i, (orientation, local) in enumerate(self.page_guides()):
            if orientation == "h" and abs(pos.y() - (self.page_offset.y() + local)) <= tol:
                return i
            if orientation == "v" and abs(pos.x() - (self.page_offset.x() + local)) <= tol:
                return i
        return None

    def set_snapping(self, *, enabled=None, objects=None, grid=None, show_grid=None, show_guides=None, grid_size=None) -> None:
        if enabled is not None:
            self.snap_enabled = enabled
        if objects is not None:
            self.snap_objects = objects
        if grid is not None:
            self.snap_grid = grid
        if show_grid is not None:
            self.show_grid = show_grid
        if show_guides is not None:
            self.show_guides = show_guides
        if grid_size is not None and grid_size > 0:
            self.grid_size = float(grid_size)
        self._build_guides()
        self._build_grid()

    # -- snapping -------------------------------------------------------------------
    def _compute_snap_targets(self) -> tuple[list[float], list[float]]:
        xs: list[float] = []
        ys: list[float] = []
        r = self.page_rect
        xs += [r.left(), r.center().x(), r.right()]
        ys += [r.top(), r.center().y(), r.bottom()]
        for orientation, local in self.page_guides():
            if orientation == "h":
                ys.append(self.page_offset.y() + local)
            else:
                xs.append(self.page_offset.x() + local)
        if self.snap_objects:
            selected = set(self.selection)
            wsel = set(self.widget_selection)
            asel = set(self.annot_selection)
            for oid, it in self.items_by_id.items():
                if oid in selected:
                    continue
                b = it.sceneTransform().mapRect(it.shape().boundingRect())
                xs += [b.left(), b.center().x(), b.right()]
                ys += [b.top(), b.center().y(), b.bottom()]
            for x, it in self.widget_items.items():
                if x in wsel:
                    continue
                b = it.rect
                xs += [b.left(), b.center().x(), b.right()]
                ys += [b.top(), b.center().y(), b.bottom()]
            for x, it in self.annot_items.items():
                if x in asel:
                    continue
                b = it.rect
                xs += [b.left(), b.right()]
                ys += [b.top(), b.bottom()]
        return sorted(set(xs)), sorted(set(ys))

    def _snap_value(self, value: float, targets: list[float], tol: float) -> float | None:
        best = None
        best_d = tol
        for t in targets:
            d = abs(t - value)
            if d <= best_d:
                best, best_d = t, d
        return best

    def _snap_grid_value(self, value: float, axis: str) -> float:
        origin = self.page_offset.x() if axis == "x" else self.page_offset.y()
        g = self.grid_size
        return origin + round((value - origin) / g) * g

    def snap_point(self, pos: QPointF, modifiers=Qt.KeyboardModifier.NoModifier, show: bool = True) -> QPointF:
        """Snap a scene point to targets/grid; draws smart guides when ``show``."""
        if not self.snap_enabled or (modifiers & Qt.KeyboardModifier.AltModifier):
            self._clear_smart()
            return pos
        if self._snap_targets is None:
            self._snap_targets = self._compute_snap_targets()
        xs, ys = self._snap_targets
        tol = self.snap_tolerance_px / max(self.zoom, 1e-6)
        sx = self._snap_value(pos.x(), xs, tol)
        sy = self._snap_value(pos.y(), ys, tol)
        x = sx if sx is not None else (self._snap_grid_value(pos.x(), "x") if self.snap_grid else pos.x())
        y = sy if sy is not None else (self._snap_grid_value(pos.y(), "y") if self.snap_grid else pos.y())
        if show:
            self._show_smart(x if sx is not None else None, y if sy is not None else None)
        return QPointF(x, y)

    def snap_rect_delta(self, rect: QRectF, dx: float, dy: float, modifiers=Qt.KeyboardModifier.NoModifier) -> tuple[float, float]:
        """Adjust a move delta so that the moved rect's edges/centre snap to targets."""
        if rect.isNull() or not self.snap_enabled or (modifiers & Qt.KeyboardModifier.AltModifier):
            self._clear_smart()
            return dx, dy
        if self._snap_targets is None:
            self._snap_targets = self._compute_snap_targets()
        xs, ys = self._snap_targets
        tol = self.snap_tolerance_px / max(self.zoom, 1e-6)
        moved = rect.translated(dx, dy)
        best_x = None
        for cand in (moved.left(), moved.center().x(), moved.right()):
            t = self._snap_value(cand, xs, tol)
            if t is not None and (best_x is None or abs(t - cand) < abs(best_x[0] - best_x[1])):
                best_x = (t, cand)
        best_y = None
        for cand in (moved.top(), moved.center().y(), moved.bottom()):
            t = self._snap_value(cand, ys, tol)
            if t is not None and (best_y is None or abs(t - cand) < abs(best_y[0] - best_y[1])):
                best_y = (t, cand)
        if best_x is not None:
            dx += best_x[0] - best_x[1]
        elif self.snap_grid:
            dx += self._snap_grid_value(moved.left(), "x") - moved.left()
        if best_y is not None:
            dy += best_y[0] - best_y[1]
        elif self.snap_grid:
            dy += self._snap_grid_value(moved.top(), "y") - moved.top()
        self._show_smart(best_x[0] if best_x else None, best_y[0] if best_y else None)
        return dx, dy

    def _show_smart(self, x: float | None, y: float | None) -> None:
        self._clear_smart()
        t = theme.current()
        pen = QPen(QColor("#f43f5e"), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        r = self.sceneRect()
        for line in ((QLineF(x, r.top(), x, r.bottom()) if x is not None else None), (QLineF(r.left(), y, r.right(), y) if y is not None else None)):
            if line is None:
                continue
            item = QGraphicsLineItem(line)
            item.setPen(pen)
            item.setZValue(3500)
            self._scene.addItem(item)
            self.smart_items.append(item)

    def _clear_smart(self) -> None:
        for it in self.smart_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.smart_items = []

    def _build_highlights(self) -> None:
        for it in self.highlight_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.highlight_items = []
        if not self.highlights:
            return
        t = theme.current()
        for r in self.highlights:
            item = QGraphicsRectItem(rect_to_qrect(r).translated(self.page_offset).adjusted(-1, -1, 1, 1))
            is_current = self.current_highlight is not None and r == self.current_highlight
            c = QColor("#f59e0b" if is_current else "#fde047")
            c.setAlpha(120 if is_current else 70)
            item.setBrush(QBrush(c))
            pen = QPen(QColor(t.accent if is_current else "#eab308"), 0)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(5)
            self._scene.addItem(item)
            self.highlight_items.append(item)

    def set_highlights(self, rects: list[Rect], current: Rect | None = None) -> None:
        self.highlights = list(rects)
        self.current_highlight = current
        self._build_highlights()
        if current is not None:
            self.ensureVisible(rect_to_qrect(current).translated(self.page_offset).adjusted(-40, -40, 40, 40))

    def _object_geometry(self, obj: GObject, S: QTransform) -> tuple[QPainterPath | None, QPainterPath | None]:
        clip = obj.state.clip_bbox
        clip_path: QPainterPath | None = None
        if clip is not None:
            clip_path = QPainterPath()
            clip_path.addRect(rect_to_qrect(clip.transformed(self.pdf_to_scene)))
        if isinstance(obj, PathObject):
            u2s = qmatrix(obj.state.ctm) * S
            path = subpaths_to_qpath(obj.subpaths, u2s)
            if path.isEmpty():
                return None, None
            if obj.fill:
                hit = QPainterPath(path)
                hit.setFillRule(Qt.FillRule.OddEvenFill if obj.even_odd else Qt.FillRule.WindingFill)
                if obj.stroke:
                    hit = hit.united(self._stroke_shape(path, obj))
            else:
                hit = self._stroke_shape(path, obj)
        elif isinstance(obj, TextRun):
            if obj.bbox is None:
                return None, None
            path = QPainterPath()
            path.addPolygon(self._quad_polygon(obj))
            path.closeSubpath()
            hit = QPainterPath(path)
        elif isinstance(obj, XObjectRef) and obj.subtype == "Form":
            if obj.bbox is None:
                return None, None
            path = QPainterPath()
            if obj.form_bbox is not None:
                m = qmatrix(obj.form_matrix * obj.state.ctm) * S
                path.addPolygon(m.map(QPolygonF(rect_to_qrect(obj.form_bbox))))
            else:
                path.addRect(rect_to_qrect(obj.bbox.transformed(self.pdf_to_scene)))
            path.closeSubpath()
            hit = QPainterPath(path)
        elif obj.kind in ("image", "inline_image"):
            m = qmatrix(obj.state.ctm) * S
            path = QPainterPath()
            path.addPolygon(m.map(QPolygonF(QRectF(0, 0, 1, 1))))
            path.closeSubpath()
            hit = QPainterPath(path)
        else:  # shading
            if obj.bbox is None:
                return None, None
            path = QPainterPath()
            path.addRect(rect_to_qrect(obj.bbox.transformed(self.pdf_to_scene)))
            hit = QPainterPath(path)
        if clip_path is not None:
            hit = hit.intersected(clip_path)
            if hit.isEmpty():
                return None, None
        return path, hit

    def _stroke_shape(self, path: QPainterPath, obj: PathObject) -> QPainterPath:
        stroker = QPainterPathStroker()
        w = obj.state.line_width * obj.state.ctm.expansion() * self.pdf_to_scene.expansion()
        stroker.setWidth(max(w, 3.0))
        stroker.setCapStyle(Qt.PenCapStyle.SquareCap)
        return stroker.createStroke(path)

    def _quad_polygon(self, run: TextRun) -> QPolygonF:
        font = run.font_info
        asc = font.ascent if font else 0.9
        dsc = font.descent if font else -0.2
        width = sum(g.advance for g in run.glyphs) / max(run.state.font_size * run.state.hscale, 1e-9) if run.glyphs else 0.0
        if run.state.font_size == 0 or width <= 0:
            r = run.bbox.transformed(self.pdf_to_scene) if run.bbox else Rect(0, 0, 1, 1)
            return QPolygonF(rect_to_qrect(r))
        trm = qmatrix(run.text_render_matrix() * self.pdf_to_scene)
        return trm.map(QPolygonF(QRectF(0, dsc, width, asc - dsc)))

    # -- rendering ---------------------------------------------------------
    def _render_now(self) -> None:
        if self.doc is None or not self.page_items:
            return
        dpr = self.devicePixelRatioF()
        scale = self.zoom * dpr
        vp = self.mapToScene(self.viewport().rect()).boundingRect()
        keep = vp.adjusted(0, -vp.height(), 0, vp.height())
        for i, item in self.page_items.items():
            r = self.page_rects[i]
            if not r.intersects(keep):
                if self.page_scales.get(i) is not None:
                    item.setPixmap(QPixmap())
                    self.page_scales.pop(i, None)
                continue
            if self.page_scales.get(i) == scale:
                continue
            key = (i, round(scale, 3), self.generation)
            pm = self.cache.get(key)
            if pm is None:
                try:
                    pm = render_page(self.doc, i, scale)
                except Exception as exc:  # pragma: no cover
                    self.statusMessage.emit(f"Render failed: {exc}")
                    continue
                self.cache.put(key, pm)
            item.setPixmap(pm)
            item.setScale(1.0 / scale)
            self.page_scales[i] = scale

    def _schedule_render(self) -> None:
        self._render_timer.start()

    # -- zoom --------------------------------------------------------------
    def set_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.zoom = zoom
        self.setTransform(QTransform.fromScale(zoom, zoom))
        margin = 40 / max(self.zoom, 0.2)
        self._scene.setSceneRect(self.layout_rect.adjusted(-margin, -margin, margin, margin))
        self.frame.set_rect(self.frame.rect, zoom)
        if self.node_overlay is not None:
            self.node_overlay.zoom = zoom
            self.node_overlay.update()
        self._schedule_render()
        self.zoomChanged.emit(zoom)
        self.viewChanged.emit()

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / 1.25)

    def zoom_fit(self) -> None:
        vp = self.viewport().rect()
        if self.page_rect.isEmpty():
            return
        z = min((vp.width() - 48) / self.page_rect.width(), (vp.height() - 48) / self.page_rect.height())
        self.set_zoom(z)
        if self.continuous:
            self.scroll_to_page(self.page_index)
        else:
            self.centerOn(self.page_rect.center())

    def zoom_width(self) -> None:
        vp = self.viewport().rect()
        if self.page_rect.isEmpty():
            return
        self.set_zoom((vp.width() - 48) / self.page_rect.width())
        if self.continuous:
            self.scroll_to_page(self.page_index)
        else:
            self.centerOn(QPointF(self.page_rect.center().x(), self.page_rect.top() + vp.height() / (2 * self.zoom)))

    def zoom_actual(self) -> None:
        self.set_zoom(1.0)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom * 1.0015 ** event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    # -- selection -------------------------------------------------------
    def selected_objects(self) -> list[GObject]:
        return [self.items_by_id[i].obj for i in self.selection if i in self.items_by_id]

    def selected_widgets(self) -> list[WidgetInfo]:
        return [self.widget_items[x].info for x in self.widget_selection if x in self.widget_items]

    def selected_annots(self) -> list[AnnotInfo]:
        return [self.annot_items[x].info for x in self.annot_selection if x in self.annot_items]

    @property
    def has_selection(self) -> bool:
        return bool(self.selection or self.widget_selection or self.annot_selection)

    def select(self, ids: list[int], emit: bool = True) -> None:
        self.selection = [i for i in ids if i in self.items_by_id]
        self.widget_selection = []
        self.annot_selection = []
        self._update_selection_visuals()
        self._update_node_overlay()
        if emit:
            self.selectionChanged.emit(list(self.selection))

    def select_widgets(self, xrefs: list[int], emit: bool = True) -> None:
        self.widget_selection = [x for x in xrefs if x in self.widget_items]
        self.selection = []
        self.annot_selection = []
        self._update_selection_visuals()
        self._update_node_overlay()
        if emit:
            self.selectionChanged.emit([])

    def select_annots(self, xrefs: list[int], emit: bool = True) -> None:
        self.annot_selection = [x for x in xrefs if x in self.annot_items]
        self.selection = []
        self.widget_selection = []
        self._update_selection_visuals()
        self._update_node_overlay()
        if emit:
            self.selectionChanged.emit([])

    def select_all(self) -> None:
        self.select(list(self.items_by_id.keys()))

    def clear_selection(self) -> None:
        self.select([])

    def _update_selection_visuals(self) -> None:
        sel = set(self.selection)
        for oid, item in self.items_by_id.items():
            item.set_selected(oid in sel)
        wsel = set(self.widget_selection)
        for x, item in self.widget_items.items():
            item.set_selected(x in wsel)
        asel = set(self.annot_selection)
        for x, item in self.annot_items.items():
            item.set_selected(x in asel)
        self.frame.set_rect(self._selection_rect(), self.zoom)

    def _selected_items(self) -> list[QGraphicsItem]:
        items: list[QGraphicsItem] = [self.items_by_id[i] for i in self.selection if i in self.items_by_id]
        items += [self.widget_items[x] for x in self.widget_selection if x in self.widget_items]
        items += [self.annot_items[x] for x in self.annot_selection if x in self.annot_items]
        return items

    def _selection_rect(self) -> QRectF:
        rect = QRectF()
        for item in self._selected_items():
            r = item.sceneTransform().mapRect(item.shape().boundingRect())
            rect = r if rect.isNull() else rect.united(r)
        return rect

    def _update_node_overlay(self) -> None:
        if self.node_overlay is not None:
            self._scene.removeItem(self.node_overlay)
            self.node_overlay = None
        if self.tool != TOOL_NODE or len(self.selection) != 1:
            return
        item = self.items_by_id.get(self.selection[0])
        if item is None or not isinstance(item.obj, PathObject):
            return
        u2s = qmatrix(item.obj.state.ctm) * qmatrix(self.pdf_to_scene)
        self.node_overlay = NodeOverlay(item.obj, u2s, self.zoom)
        self._scene.addItem(self.node_overlay)
        self.frame.set_rect(QRectF(), self.zoom)

    # -- editing helpers --------------------------------------------------
    def doc_path(self) -> tuple:
        return tuple((x, m) for x, m, _n in self.edit_path)

    def _editor(self) -> ContentEditor | None:
        if self.doc is None:
            return None
        return ContentEditor(self.doc.content(self.page_index, self.doc_path()))

    def _commit(self, editor: ContentEditor, label: str, select_new: bool = False) -> None:
        assert self.doc is not None
        try:
            data = editor.build()
        except Exception as exc:
            self.statusMessage.emit(f"Edit failed: {exc}")
            return
        self._select_new_after_rebuild = select_new
        self.doc.apply_content_edit(self.page_index, data, label, self.doc_path())
        self._select_new_after_rebuild = False
        self.pageEdited.emit(self.page_index)
        if select_new:
            self.selectionChanged.emit(list(self.selection))

    def scene_matrix_to_pdf(self, m: Matrix) -> Matrix:
        S = self.pdf_to_scene
        return S * m * S.inverted()

    def scene_to_pdf(self) -> Matrix:
        return self.pdf_to_scene.inverted()

    def transform_selection(self, m_scene: Matrix, label: str = "Transform") -> None:
        if self.annot_selection and self.doc is not None:
            movable = [a.xref for a in self.selected_annots() if a.movable]
            if movable:
                self.doc.transform_annotations(self.page_index, movable, self.to_local_matrix(m_scene))
                self.pageEdited.emit(self.page_index)
            else:
                self.statusMessage.emit("Text markup annotations follow the text and cannot be moved.")
            return
        if self.widget_selection and self.doc is not None:
            self.doc.transform_widgets(self.page_index, list(self.widget_selection), self.to_local_matrix(m_scene))
            self.pageEdited.emit(self.page_index)
            return
        if not self.selection:
            return
        ed = self._editor()
        if ed is None:
            return
        ed.transform(list(self.selection), self.scene_matrix_to_pdf(m_scene), scale_stroke=self.scale_stroke)
        self._commit(ed, label)

    def nudge(self, dx: float, dy: float) -> None:
        self.transform_selection(Matrix.translation(dx, dy), "Nudge")

    def delete_selection(self) -> None:
        if self.annot_selection and self.doc is not None:
            xs = list(self.annot_selection)
            self.annot_selection = []
            self.doc.delete_annotations(self.page_index, xs)
            self.selectionChanged.emit([])
            return
        if self.widget_selection and self.doc is not None:
            xs = list(self.widget_selection)
            self.widget_selection = []
            self.doc.delete_widgets(self.page_index, xs)
            self.selectionChanged.emit([])
            return
        if not self.selection:
            return
        ed = self._editor()
        if ed is None:
            return
        ed.delete(list(self.selection))
        self.selection = []
        self._commit(ed, "Delete")
        self.selectionChanged.emit([])

    # -- groups / form XObjects --------------------------------------------------------
    @property
    def in_group(self) -> bool:
        return bool(self.edit_path)

    def enter_form(self, oid: int | None = None) -> bool:
        """Start editing inside the selected (or given) form XObject."""
        if oid is None:
            oid = self.selection[0] if len(self.selection) == 1 else None
        if oid is None:
            return False
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, XObjectRef) or item.obj.subtype != "Form" or not item.obj.xref:
            return False
        obj = item.obj
        base = obj.form_matrix * obj.state.ctm
        self.edit_path.append((obj.xref, base, obj.name))
        self.selection = []
        self.widget_selection = []
        self.annot_selection = []
        self._activate_page(self.page_index)
        self.selectionChanged.emit([])
        self.statusMessage.emit(f"Editing inside /{obj.name} · Esc or Object › Exit Group to leave")
        return True

    def exit_form(self) -> bool:
        if not self.edit_path:
            return False
        self.edit_path.pop()
        self.selection = []
        self.widget_selection = []
        self.annot_selection = []
        self._activate_page(self.page_index)
        self.selectionChanged.emit([])
        return True

    def exit_all_forms(self) -> None:
        if self.edit_path:
            self.edit_path = []
            self._activate_page(self.page_index)
            self.selectionChanged.emit([])

    def group_selection(self) -> None:
        if self.doc is None or not self.selection:
            return
        ids = list(self.selection)
        self.selection = []
        self._select_new_after_rebuild = True
        self.doc.group_objects(self.page_index, self.doc_path(), ids)
        self._select_new_after_rebuild = False
        self.pageEdited.emit(self.page_index)
        self.selectionChanged.emit(list(self.selection))

    def ungroup_selection(self) -> None:
        if self.doc is None or len(self.selection) != 1:
            return
        obj = self.items_by_id[self.selection[0]].obj
        if not isinstance(obj, XObjectRef) or obj.subtype != "Form":
            self.statusMessage.emit("Select a group (form XObject) to ungroup.")
            return
        self.selection = []
        self.doc.ungroup_object(self.page_index, self.doc_path(), obj.id)
        self.pageEdited.emit(self.page_index)
        self.selectionChanged.emit([])

    def _build_context_overlay(self) -> None:
        for it in self.context_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self.context_items = []
        if not self.edit_path or self.doc is None:
            return
        xref, base, name = self.edit_path[-1]
        info = self.doc.form_info(xref)
        t = theme.current()
        if info.bbox is not None:
            r = rect_to_qrect(info.bbox.transformed(base * self.pdf_to_scene))
            dim = QPainterPath()
            dim.addRect(self.page_rect)
            hole = QPainterPath()
            hole.addRect(r)
            shade = QGraphicsPathItem(dim.subtracted(hole))
            c = QColor(t.canvas)
            c.setAlpha(150)
            shade.setBrush(QBrush(c))
            shade.setPen(Qt.PenStyle.NoPen)
            shade.setZValue(2)
            self._scene.addItem(shade)
            self.context_items.append(shade)
            outline = QGraphicsRectItem(r)
            pen = QPen(QColor(t.accent), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            outline.setPen(pen)
            outline.setZValue(2.5)
            self._scene.addItem(outline)
            self.context_items.append(outline)

    # -- arrangement -----------------------------------------------------------------
    def duplicate_selection(self, offset: float = 10.0) -> None:
        if self.widget_selection or self.annot_selection:
            self.statusMessage.emit("Only page content can be duplicated.")
            return
        ed = self._editor()
        if ed is None or not self.selection:
            return
        n = ed.duplicate(list(self.selection), self.scene_matrix_to_pdf(Matrix.translation(offset, offset)))
        if n:
            self._commit(ed, "Duplicate", select_new=True)
            if n > 1:
                ids = sorted(self.items_by_id)[-n:]
                self.select(ids)

    def bring_to_front(self) -> None:
        ed = self._editor()
        if ed is None or not self.selection:
            return
        n = ed.bring_to_front(list(self.selection))
        self._commit(ed, "Bring to front", select_new=True)
        if n > 1:
            self.select(sorted(self.items_by_id)[-n:])

    def send_to_back(self) -> None:
        ed = self._editor()
        if ed is None or not self.selection:
            return
        n = ed.send_to_back(list(self.selection))
        self.selection = []
        self._commit(ed, "Send to back")
        if n:
            self.select(sorted(self.items_by_id)[:n])

    def flip_selection(self, horizontal: bool) -> None:
        rect = self._selection_rect()
        if rect.isNull():
            return
        c = rect.center()
        m = Matrix.translation(-c.x(), -c.y()) * (Matrix.scale(-1, 1) if horizontal else Matrix.scale(1, -1)) * Matrix.translation(c.x(), c.y())
        self.transform_selection(m, "Flip")

    def rotate_selection(self, degrees: float) -> None:
        rect = self._selection_rect()
        if rect.isNull():
            return
        c = rect.center()
        self.transform_selection(Matrix.translation(-c.x(), -c.y()) * Matrix.rotation(degrees) * Matrix.translation(c.x(), c.y()), "Rotate")

    def align_selection(self, mode: str) -> None:
        """Align content objects: left/hcenter/right/top/vcenter/bottom; a single object aligns to the page."""
        ed = self._editor()
        if ed is None or not self.selection:
            return
        rects = {oid: self.items_by_id[oid].sceneTransform().mapRect(self.items_by_id[oid].shape().boundingRect()) for oid in self.selection}
        target = self._selection_rect() if len(rects) > 1 else self.page_rect
        moved = False
        for oid, r in rects.items():
            dx = dy = 0.0
            if mode == "left":
                dx = target.left() - r.left()
            elif mode == "hcenter":
                dx = target.center().x() - r.center().x()
            elif mode == "right":
                dx = target.right() - r.right()
            elif mode == "top":
                dy = target.top() - r.top()
            elif mode == "vcenter":
                dy = target.center().y() - r.center().y()
            elif mode == "bottom":
                dy = target.bottom() - r.bottom()
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                ed.transform([oid], self.scene_matrix_to_pdf(Matrix.translation(dx, dy)), scale_stroke=False)
                moved = True
        if moved:
            self._commit(ed, "Align")

    def distribute_selection(self, horizontal: bool) -> None:
        ed = self._editor()
        if ed is None or len(self.selection) < 3:
            return
        rects = [(oid, self.items_by_id[oid].sceneTransform().mapRect(self.items_by_id[oid].shape().boundingRect())) for oid in self.selection]
        key = (lambda r: r.center().x()) if horizontal else (lambda r: r.center().y())
        rects.sort(key=lambda t: key(t[1]))
        first, last = key(rects[0][1]), key(rects[-1][1])
        step = (last - first) / (len(rects) - 1)
        for i, (oid, r) in enumerate(rects[1:-1], start=1):
            want = first + i * step
            d = want - key(r)
            if abs(d) > 1e-6:
                ed.transform([oid], self.scene_matrix_to_pdf(Matrix.translation(d, 0) if horizontal else Matrix.translation(0, d)), scale_stroke=False)
        self._commit(ed, "Distribute")

    def copy_selected_text(self) -> str:
        runs = [o for o in self.selected_objects() if isinstance(o, TextRun)]
        if not runs:
            return ""
        lines: list[str] = []
        done: set[int] = set()
        for r in sorted(runs, key=lambda r: (-r.tm.f, r.tm.e)):
            if r.id in done:
                continue
            ids = self.text_line_ids(r.id)
            sel_ids = [i for i in ids if i in self.selection]
            done.update(sel_ids)
            lines.append(self._line_text(sel_ids))
        text = "\n".join(lines)
        QGuiApplication.clipboard().setText(text)
        return text

    def set_selection_style(self, **kwargs) -> None:
        if not self.selection:
            return
        ed = self._editor()
        if ed is None:
            return
        for oid in self.selection:
            obj = self.items_by_id[oid].obj
            if obj.kind in ("path", "text"):
                allowed = dict(kwargs)
                if obj.kind == "text":
                    allowed = {k: v for k, v in allowed.items() if k in ("fill_color", "stroke_color", "line_width")}
                if allowed:
                    ed.set_style(oid, **allowed)
        self._commit(ed, "Change style")

    def set_text_size(self, size: float) -> None:
        ed = self._editor()
        if ed is None:
            return
        for oid in self.selection:
            if self.items_by_id[oid].obj.kind == "text":
                ed.set_text_size(oid, size)
        self._commit(ed, "Text size")

    def _encode_text(self, ed: ContentEditor, oid: int, text: str) -> bool:
        """Set a run's text, falling back to a built-in font when needed."""
        assert self.doc is not None
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return False
        if ed.set_text(oid, text):
            return True
        name = self.doc.substitute_font_name(item.obj.font_info)
        try:
            sub = self.doc.ensure_substitute_font(self.page_index, name)
        except Exception as exc:
            self.statusMessage.emit(f"Could not add substitute font: {exc}")
            return False
        if ed.set_text(oid, text, substitute=sub):
            font = item.obj.font_info.display_name if item.obj.font_info else item.obj.font
            self.statusMessage.emit(f"Some characters are not in the embedded font “{font}”; substituted a built-in font.")
            return True
        self.statusMessage.emit("Text could not be encoded.")
        return False

    def set_text(self, oid: int, text: str) -> bool:
        return self.set_line_text([oid], text)

    def set_line_text(self, ids: list[int], text: str) -> bool:
        """Replace the text of a line made of several runs: first run gets the text, the rest are removed."""
        ed = self._editor()
        if ed is None or not ids:
            return False
        current = self._line_text(ids)
        if current == text:
            return True
        if not self._encode_text(ed, ids[0], text):
            return False
        if len(ids) > 1:
            ed.delete(ids[1:])
        self.selection = [ids[0]]
        self._commit(ed, "Edit text")
        return True

    # -- text lines ----------------------------------------------------------
    def text_line_ids(self, oid: int) -> list[int]:
        """Runs forming the visual line that contains ``oid`` (same block, same baseline)."""
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return [oid]
        run = item.obj
        if run.block is None:
            return [oid]
        size = max(run.state.font_size, 1e-6)
        candidates: list[TextRun] = []
        for it in run.block.items:
            if not isinstance(it, TextRun) or it.id not in self.items_by_id:
                continue
            if it.state.ctm != run.state.ctm or abs(it.state.font_size - size) > 0.05 * size:
                continue
            # same orientation and baseline
            if abs(it.tm.b - run.tm.b) > 1e-6 or abs(it.tm.c - run.tm.c) > 1e-6 or abs(it.tm.d - run.tm.d) > 1e-6:
                continue
            if abs(it.tm.f - run.tm.f) > 0.1 * size:
                continue
            candidates.append(it)
        candidates.sort(key=lambda r: r.tm.e)
        # keep the contiguous group around the run (gaps < 2 em break the line)
        idx = next(i for i, r in enumerate(candidates) if r.id == oid)
        line = [candidates[idx]]
        i = idx
        while i > 0 and candidates[i].tm.e - candidates[i - 1].end_tm.e < 2 * size:
            line.insert(0, candidates[i - 1])
            i -= 1
        i = idx
        while i + 1 < len(candidates) and candidates[i + 1].tm.e - candidates[i].end_tm.e < 2 * size:
            line.append(candidates[i + 1])
            i += 1
        return [r.id for r in line]

    def _line_text(self, ids: list[int]) -> str:
        runs = [self.items_by_id[i].obj for i in ids if i in self.items_by_id]
        out = ""
        prev: TextRun | None = None
        for r in runs:
            if prev is not None:
                gap = r.tm.e - prev.end_tm.e
                if gap > 0.15 * max(r.state.font_size, 1e-6) and not out.endswith(" ") and not r.text.startswith(" "):
                    out += " "
            out += r.text
            prev = r
        return out

    # -- paragraphs ---------------------------------------------------------------
    def paragraph_line_ids(self, oid: int) -> list[list[int]]:
        """Lines (each a list of run ids) forming the paragraph around ``oid``."""
        start = self.text_line_ids(oid)
        if not start:
            return [[oid]]
        first = self.items_by_id[start[0]].obj
        size = max(first.state.font_size, 1e-6)
        lines: dict[int, list[int]] = {}
        seen: set[int] = set()
        for i, it in self.items_by_id.items():
            o = it.obj
            if not isinstance(o, TextRun) or i in seen or o.state.ctm != first.state.ctm:
                continue
            if abs(o.state.font_size - size) > 0.2 * size:
                continue
            if abs(o.tm.b - first.tm.b) > 1e-6 or abs(o.tm.c - first.tm.c) > 1e-6:
                continue
            ids = self.text_line_ids(i)
            seen.update(ids)
            lines[ids[0]] = ids

        def span(ids: list[int]) -> tuple[float, float, float]:
            runs = [self.items_by_id[j].obj for j in ids]
            return (min(r.tm.e for r in runs), max(r.end_tm.e for r in runs), runs[0].tm.f)

        ordered = sorted(lines.values(), key=lambda ids: -span(ids)[2])
        idx = next(k for k, ids in enumerate(ordered) if start[0] in ids)
        x0, x1, _ = span(start)

        def joins(a: list[int], b: list[int]) -> bool:
            ax0, ax1, ay = span(a)
            bx0, bx1, by = span(b)
            gap = abs(ay - by)
            overlap = min(ax1, bx1) - max(ax0, bx0)
            return 0 < gap <= 1.9 * size and overlap > 0.2 * min(ax1 - ax0, bx1 - bx0)

        para = [ordered[idx]]
        k = idx
        while k > 0 and joins(ordered[k - 1], ordered[k]):
            para.insert(0, ordered[k - 1])
            k -= 1
        k = idx
        while k + 1 < len(ordered) and joins(ordered[k], ordered[k + 1]):
            para.append(ordered[k + 1])
            k += 1
        return para

    def begin_paragraph_edit(self, oid: int) -> None:
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return
        lines = self.paragraph_line_ids(oid)
        runs = [self.items_by_id[ids[0]].obj for ids in lines]
        text = "\n".join(self._line_text(ids) for ids in lines)
        rect = QRectF()
        for ids in lines:
            for i in ids:
                r = self.items_by_id[i].sceneBoundingRect()
                rect = r if rect.isNull() else rect.united(r)
        first = runs[0]
        gaps = [abs(runs[k].tm.f - runs[k + 1].tm.f) for k in range(len(runs) - 1)]
        leading = (sorted(gaps)[len(gaps) // 2] if gaps else first.state.font_size * 1.2)
        self.paragraph = {
            "lines": lines, "font": first.font, "font_info": first.font_info, "size": first.state.font_size,
            "color": first.state.fill_color, "tm": first.tm, "ctm": first.state.ctm, "leading": leading,
            "width": max(self.items_by_id[i].obj.end_tm.e for ids in lines for i in ids) - min(self.items_by_id[i].obj.tm.e for ids in lines for i in ids),
        }
        self.select([i for ids in lines for i in ids])
        size_pt = first.state.font_size * first.state.ctm.expansion() * self.pdf_to_scene.expansion()
        self._open_text_editor(text, rect, size_pt, multiline=True, lines_hint=len(lines))

    def begin_text_box(self, rect: QRectF) -> None:
        self.text_box = QRectF(rect)
        size = self.draw_style.font_size
        self._open_text_editor("", rect, size, multiline=True, lines_hint=max(2, int(rect.height() / (size * 1.2))))

    def _commit_paragraph(self, text: str) -> None:
        p = self.paragraph
        self.paragraph = None
        if p is None or self.doc is None:
            return
        old = "\n".join(self._line_text(ids) for ids in p["lines"])
        if text == old:
            return
        ed = self._editor()
        if ed is None:
            return
        all_ids = [i for ids in p["lines"] for i in ids]
        font_name, fi = p["font"], p["font_info"]
        if fi is None or fi.encode(text.replace("\n", "")) is None:
            try:
                font_name, fi = self.doc.ensure_substitute_font(self.page_index, self.doc.substitute_font_name(fi))
                self.statusMessage.emit("Some characters are not in the original font; a built-in font was substituted.")
            except Exception as exc:
                self.statusMessage.emit(f"Could not add font: {exc}")
                return
        ed.delete(all_ids)
        tm = p["tm"] * p["ctm"]  # text origin in device space
        x, y = tm.e, tm.f
        angle = math.degrees(math.atan2(tm.b, tm.a))
        width = max(p["width"] * 1.02, p["size"] * 2)
        if not ed.append_text_block(x, y, width, text, font_name, fi, p["size"], p["color"], leading=p["leading"], rotation=angle):
            self.statusMessage.emit("Text could not be encoded.")
            return
        self.selection = []
        self._commit(ed, "Edit paragraph")

    def _commit_text_box(self, rect: QRectF, text: str) -> None:
        self.text_box = None
        if self.doc is None or not text.strip():
            return
        ed = self._editor()
        if ed is None:
            return
        style = self.draw_style
        try:
            name, fi = self.doc.ensure_substitute_font(self.page_index, style.font)
        except Exception as exc:
            self.statusMessage.emit(f"Could not add font: {exc}")
            return
        inv = self.scene_to_pdf()
        k = inv.expansion()
        size = style.font_size * k
        top_left = QPointF(rect.left(), rect.top() + style.font_size)
        x, y = inv.apply(top_left.x(), top_left.y())
        angle = -math.degrees(math.atan2(inv.b, inv.a))
        if not ed.append_text_block(x, y, rect.width() * k, text, name, fi, size, style.text_color, rotation=angle):
            self.statusMessage.emit("Some characters are not available in the chosen font.")
            return
        self._commit(ed, "Add text box", select_new=True)

    # -- inline text editing -----------------------------------------------
    def begin_text_edit(self, oid: int) -> None:
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return
        ids = self.text_line_ids(oid)
        run = self.items_by_id[ids[0]].obj
        rect = QRectF()
        for i in ids:
            r = self.items_by_id[i].sceneBoundingRect()
            rect = r if rect.isNull() else rect.united(r)
        self.select(ids, emit=True)
        self._open_text_editor(self._line_text(ids), rect, run.state.font_size * run.state.ctm.expansion() * self.pdf_to_scene.expansion(), ids=ids)

    def begin_new_text(self, pos: QPointF) -> None:
        size = self.draw_style.font_size
        rect = QRectF(pos.x(), pos.y() - size, 120, size * 1.2)
        self._open_text_editor("", rect, size, new_at=pos)

    def _open_text_editor(self, text: str, rect: QRectF, size_pt: float, ids: list[int] | None = None, new_at: QPointF | None = None,
                          multiline: bool = False, lines_hint: int = 1) -> None:
        self._end_text_edit(commit=False)
        t = theme.current()
        font = QFont()
        font.setPixelSize(int(round(max(size_pt, 4.0))))
        if multiline:
            edit = QPlainTextEdit()
            edit.setPlainText(text)
            edit.setFont(font)
            edit.setStyleSheet(
                f"QPlainTextEdit {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.accent}; border-radius: 2px; padding: 0 2px; }}"
            )
            edit.setMinimumWidth(int(max(rect.width() * 1.15 + 48, 160)))
            edit.setFixedHeight(int(max(rect.height() * 1.1 + 16, size_pt * 1.35 * max(lines_hint, 2) + 16)))
            edit.setPlaceholderText("Type text… (Ctrl+Enter applies, Esc cancels)")
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        else:
            edit = QLineEdit(text)
            edit.setFont(font)
            edit.setStyleSheet(
                f"QLineEdit {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.accent}; border-radius: 2px; padding: 0 2px; }}"
            )
            edit.setMinimumWidth(int(max(rect.width() + 24, 80)))
            edit.setPlaceholderText("Type text…")
        proxy = self._scene.addWidget(edit)
        proxy.setZValue(5000)
        proxy.setPos(rect.left() - 3, rect.top() - 2)
        proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.text_proxy = proxy
        self.text_edit_ids = list(ids or [])
        self.text_edit_new = new_at
        if isinstance(edit, QLineEdit):
            edit.returnPressed.connect(lambda: self._end_text_edit(commit=True))
        edit.installEventFilter(self)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._scene.setFocusItem(proxy, Qt.FocusReason.OtherFocusReason)
        proxy.setFocus(Qt.FocusReason.OtherFocusReason)
        edit.setFocus(Qt.FocusReason.OtherFocusReason)
        if text and isinstance(edit, QLineEdit):
            edit.selectAll()
        self.statusMessage.emit("Editing paragraph: Ctrl+Enter applies, Esc cancels" if multiline else "Editing text: Enter applies, Esc cancels")

    def _end_text_edit(self, commit: bool) -> None:
        proxy = self.text_proxy
        if proxy is None:
            return
        ids = self.text_edit_ids
        new_at = self.text_edit_new
        widget = proxy.widget()
        if isinstance(widget, QLineEdit):
            text = widget.text()
        elif isinstance(widget, QPlainTextEdit):
            text = widget.toPlainText()
        else:
            text = None
        box = self.text_box
        para = self.paragraph
        self.text_proxy = None
        self.text_edit_ids = []
        self.text_edit_new = None
        self.text_box = None
        try:
            self._scene.removeItem(proxy)
        except RuntimeError:
            pass
        proxy.deleteLater()
        self.setFocus()
        if not commit or text is None:
            self.paragraph = None
            return
        if box is not None:
            self._commit_text_box(box, text)
        elif para is not None:
            self._commit_paragraph(text)
        elif new_at is not None:
            if text.strip():
                self.create_text(new_at, text)
        elif ids:
            self.set_line_text(ids, text)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self._end_text_edit(commit=False)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._end_text_edit(commit=True)
                return True
        if event.type() == QEvent.Type.FocusOut and self.text_proxy is not None:
            try:
                is_editor = obj is self.text_proxy.widget()
            except RuntimeError:  # proxy already destroyed
                self.text_proxy = None
                return False
            if is_editor:
                QTimer.singleShot(0, self._commit_if_unfocused)
            return False
        return super().eventFilter(obj, event)

    def _commit_if_unfocused(self) -> None:
        proxy = self.text_proxy
        if proxy is None:
            return
        try:
            w = proxy.widget()
            focused = w is not None and w.hasFocus()
        except RuntimeError:
            self.text_proxy = None
            return
        if not focused:
            self._end_text_edit(commit=True)

    # -- creation --------------------------------------------------------------
    def create_path_scene(self, subpaths_scene: list[list[tuple]], closed: bool, label: str) -> None:
        ed = self._editor()
        if ed is None:
            return
        style = self.draw_style
        dev = transform_subpaths(subpaths_scene, self.scene_to_pdf())
        k = self.scene_to_pdf().expansion()
        ed.append_path(
            dev,
            fill_color=style.fill if closed else None,
            stroke_color=style.stroke,
            line_width=style.line_width * k,
        )
        if style.fill is None and style.stroke is None:
            self.statusMessage.emit("New objects need a fill or a stroke colour (see the Inspector).")
            return
        self._commit(ed, label, select_new=True)

    def create_rect(self, r: QRectF) -> None:
        self.create_path_scene(
            [[("m", r.left(), r.top()), ("l", r.right(), r.top()), ("l", r.right(), r.bottom()), ("l", r.left(), r.bottom()), ("h",)]],
            True, "Draw rectangle",
        )

    def create_ellipse(self, r: QRectF) -> None:
        self.create_path_scene([ellipse_subpath(r)], True, "Draw ellipse")

    def create_line(self, a: QPointF, b: QPointF) -> None:
        self.create_path_scene([[("m", a.x(), a.y()), ("l", b.x(), b.y())]], False, "Draw line")

    def create_polyline(self, pts: list[QPointF], closed: bool) -> None:
        if len(pts) < 2:
            return
        sp: list[tuple] = [("m", pts[0].x(), pts[0].y())] + [("l", p.x(), p.y()) for p in pts[1:]]
        if closed:
            sp.append(("h",))
        self.create_path_scene([sp], closed, "Draw path")

    def create_text(self, pos: QPointF, text: str) -> None:
        if self.doc is None:
            return
        ed = self._editor()
        if ed is None:
            return
        style = self.draw_style
        try:
            name, fi = self.doc.ensure_substitute_font(self.page_index, style.font)
        except Exception as exc:
            self.statusMessage.emit(f"Could not add font: {exc}")
            return
        inv = self.scene_to_pdf()
        x, y = inv.apply(pos.x(), pos.y())
        # text rotation follows the page rotation so it reads upright on screen
        angle = -math.degrees(math.atan2(inv.b, inv.a))
        size = style.font_size * inv.expansion()
        if not ed.append_text(x, y, text, name, fi, size, style.text_color, rotation=angle):
            self.statusMessage.emit("Some characters are not available in the chosen font.")
            return
        self._commit(ed, "Add text", select_new=True)

    def create_widget(self, r: QRectF, field_type: int) -> None:
        if self.doc is None:
            return
        if r.width() < 4 or r.height() < 4:
            size = {2: 14.0, 5: 14.0}.get(field_type, 0.0)
            if size:
                r = QRectF(r.left(), r.top(), size, size)
            else:
                r = QRectF(r.left(), r.top(), 120.0, 22.0)
        self.doc.add_widget(self.page_index, field_type, self.to_local_rect(r))
        self.pageEdited.emit(self.page_index)
        new = [x for x in self.widget_items]
        if new:
            self.select_widgets([max(new)])

    def insert_image(self, path: str) -> None:
        if self.doc is None:
            return
        try:
            w, h = self.doc.image_size(path)
        except Exception as exc:
            self.statusMessage.emit(f"Could not read image: {exc}")
            return
        pr = self.page_rect
        max_w = pr.width() * 0.5
        max_h = pr.height() * 0.5
        scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
        iw, ih = w * scale, h * scale
        center = self.mapToScene(self.viewport().rect().center())
        if not pr.contains(center):
            center = pr.center()
        r = QRectF(center.x() - iw / 2, center.y() - ih / 2, iw, ih)
        r = r.intersected(pr) if not pr.contains(r) else r
        self._select_new_after_rebuild = True
        self.doc.add_image(self.page_index, self.to_local_rect(r), path)
        self._select_new_after_rebuild = False
        self.pageEdited.emit(self.page_index)
        self.selectionChanged.emit(list(self.selection))

    # -- pen tool --------------------------------------------------------------
    def _cancel_pen(self) -> None:
        self.pen_points = []
        self.pen_handles = []
        if self.pen_preview is not None:
            try:
                self._scene.removeItem(self.pen_preview)
            except RuntimeError:
                pass
            self.pen_preview = None

    def _pen_subpath(self, pts: list[QPointF], handles: list[QPointF | None], closed: bool) -> list[tuple]:
        """Build segments: straight where both ends are corners, cubic otherwise (symmetric handles)."""
        sp: list[tuple] = [("m", pts[0].x(), pts[0].y())]
        n = len(pts)
        pairs = list(range(n - 1)) + ([n - 1] if closed and n > 2 else [])
        for i in pairs:
            a, b = pts[i], pts[(i + 1) % n]
            ha, hb = handles[i], handles[(i + 1) % n]
            if ha is None and hb is None:
                sp.append(("l", b.x(), b.y()))
                continue
            c1 = ha if ha is not None else a
            c2 = (b - (hb - b)) if hb is not None else b  # mirrored in-handle
            sp.append(("c", c1.x(), c1.y(), c2.x(), c2.y(), b.x(), b.y()))
        if closed:
            sp.append(("h",))
        return sp

    def _finish_pen(self, closed: bool = False) -> None:
        pts = list(self.pen_points)
        handles = list(self.pen_handles) + [None] * (len(pts) - len(self.pen_handles))
        self._cancel_pen()
        if len(pts) >= 2:
            sp = self._pen_subpath(pts, handles, closed)
            self.create_path_scene([sp], closed, "Draw path")

    def _update_pen_preview(self, cursor: QPointF | None) -> None:
        if not self.pen_points:
            return
        if self.pen_preview is None:
            self.pen_preview = QGraphicsPathItem()
            self.pen_preview.setZValue(3000)
            self.pen_preview.setPen(self._preview_pen())
            self._scene.addItem(self.pen_preview)
        pts = list(self.pen_points)
        handles = list(self.pen_handles) + [None] * (len(pts) - len(self.pen_handles))
        if cursor is not None and (pts and (cursor - pts[-1]).manhattanLength() > 1e-6):
            pts.append(cursor)
            handles.append(None)
        path = subpaths_to_qpath([self._pen_subpath(pts, handles, False)], QTransform()) if len(pts) >= 2 else QPainterPath(pts[0])
        # show handle lines of the last point
        if self.pen_handles and self.pen_handles[-1] is not None and self.pen_points:
            a = self.pen_points[-1]
            h = self.pen_handles[-1]
            path.moveTo(a - (h - a))
            path.lineTo(h)
        self.pen_preview.setPath(path)

    def _preview_pen(self) -> QPen:
        t = theme.current()
        pen = QPen(QColor(t.selection), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        return pen

    # -- mouse handling ---------------------------------------------------------
    def _object_at(self, pos: QPointF) -> ObjectItem | WidgetItem | AnnotItem | None:
        for it in self._scene.items(pos, Qt.ItemSelectionMode.IntersectsItemShape, Qt.SortOrder.DescendingOrder):
            if isinstance(it, (ObjectItem, WidgetItem, AnnotItem)):
                return it
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.doc is None:
            return
        pos = self.mapToScene(event.position().toPoint())
        if self.text_proxy is not None:
            if not self.text_proxy.sceneBoundingRect().contains(pos):
                self._end_text_edit(commit=True)
            else:
                super().mousePressEvent(event)
                return
        if event.button() == Qt.MouseButton.MiddleButton or self.tool == TOOL_HAND:
            self.drag = DragState("pan", event.position(), event.position())
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self.continuous:
            target = self.page_at(pos)
            if target is not None and target != self.page_index and not (self.tool == TOOL_PEN and self.pen_points):
                self.page_index = target
                self.selection = []
                self.widget_selection = []
                self.annot_selection = []
                self.edit_path = []
                self._activate_page(target)
                self.selectionChanged.emit([])
                self.pageChanged.emit(target)
        self._snap_targets = None
        if self.tool == TOOL_SELECT and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            gi = self._guide_at(pos)
            if gi is not None and self.frame.handle_at(pos) is None and not isinstance(self._object_at(pos), (ObjectItem,)):
                self._guide_drag = (gi, self.page_guides()[gi][0])
                self.drag = DragState("guide", pos, pos)
                return
        if self.tool == TOOL_PEN:
            if self.pen_points and (pos - self.pen_points[0]).manhattanLength() * self.zoom < 8 and len(self.pen_points) > 2:
                self._finish_pen(closed=True)
                return
            pos = self.snap_point(pos, event.modifiers(), show=False)
            self.pen_points.append(pos)
            self.pen_handles.append(None)
            self.drag = DragState("penhandle", pos, pos)
            self._update_pen_preview(pos)
            return
        if self.tool in (TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE) or self.tool in AREA_TOOLS or self.is_field_tool or self.is_markup_tool:
            if not self.is_markup_tool:
                pos = self.snap_point(pos, event.modifiers(), show=False)
            self.drag = DragState("create", pos, pos)
            return
        if self.tool == TOOL_NOTE:
            if self.page_rect.contains(pos) and self.doc is not None:
                self.doc.add_note(self.page_index, self.to_local_point(pos), "", author=self.author)
                self.pageEdited.emit(self.page_index)
                if self.annot_items:
                    self.select_annots([max(self.annot_items)])
            return
        if self.tool == TOOL_NODE and self.node_overlay is not None:
            key = self.node_overlay.point_at(pos)
            if key is not None:
                self.node_overlay.active = key
                self.node_overlay.update()
                self.drag = DragState("node", pos, pos, node_key=key)
                return
        handle = self.frame.handle_at(pos) if self.tool in (TOOL_SELECT, TOOL_NODE) else None
        if handle is not None:
            rect = self.frame.rect
            anchors = {
                "nw": rect.bottomRight(), "n": QPointF(rect.center().x(), rect.bottom()), "ne": rect.bottomLeft(),
                "e": QPointF(rect.left(), rect.center().y()), "se": rect.topLeft(), "s": QPointF(rect.center().x(), rect.top()),
                "sw": rect.topRight(), "w": QPointF(rect.right(), rect.center().y()),
            }
            self.drag = DragState("scale", pos, pos, handle=handle, anchor=anchors[handle], frame_rect=QRectF(rect))
            return
        item = self._object_at(pos)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if self.tool == TOOL_TEXT:
            if isinstance(item, ObjectItem) and isinstance(item.obj, TextRun):
                self.begin_text_edit(item.obj.id)
            elif self.page_rect.contains(pos):
                self.clear_selection()
                pos = self.snap_point(pos, event.modifiers(), show=False)
                self.drag = DragState("textbox", pos, pos)
            return
        if item is None:
            if not shift:
                self.clear_selection()
            self.drag = DragState("rubber", pos, pos)
            self.rubber = QGraphicsRectItem()
            self.rubber.setPen(self._preview_pen())
            c = QColor(theme.current().selection)
            c.setAlpha(30)
            self.rubber.setBrush(QBrush(c))
            self.rubber.setZValue(3000)
            self._scene.addItem(self.rubber)
            return
        if isinstance(item, WidgetItem):
            x = item.info.xref
            if shift:
                sel = [w for w in self.widget_selection if w != x] if x in self.widget_selection else self.widget_selection + [x]
                self.select_widgets(sel)
                return
            if x not in self.widget_selection:
                self.select_widgets([x])
            self.drag = DragState("move", pos, pos, frame_rect=self._selection_rect())
            return
        if isinstance(item, AnnotItem):
            x = item.info.xref
            if shift:
                sel = [a for a in self.annot_selection if a != x] if x in self.annot_selection else self.annot_selection + [x]
                self.select_annots(sel)
                return
            if x not in self.annot_selection:
                self.select_annots([x])
            if item.info.movable:
                self.drag = DragState("move", pos, pos, frame_rect=self._selection_rect())
            return
        oid = item.obj.id
        if shift:
            if oid in self.selection:
                self.select([i for i in self.selection if i != oid])
            else:
                self.select(self.selection + [oid])
            return
        if oid not in self.selection:
            self.select([oid])
        self.drag = DragState("move", pos, pos, frame_rect=self._selection_rect())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        self.cursorMoved.emit(pos)
        if self.drag is None:
            if self.tool == TOOL_PEN and self.pen_points:
                self._update_pen_preview(pos)
            elif self.tool in (TOOL_SELECT, TOOL_NODE):
                handle = self.frame.handle_at(pos)
                if self.tool == TOOL_SELECT and handle is None and self._guide_at(pos) is not None and not isinstance(self._object_at(pos), ObjectItem):
                    gi = self._guide_at(pos)
                    orientation = self.page_guides()[gi][0] if gi is not None else "h"
                    self.viewport().setCursor(Qt.CursorShape.SplitVCursor if orientation == "h" else Qt.CursorShape.SplitHCursor)
                    super().mouseMoveEvent(event)
                    return
                if self.node_overlay is not None:
                    key = self.node_overlay.point_at(pos)
                    if key != self.node_overlay.hover:
                        self.node_overlay.hover = key
                        self.node_overlay.update()
                    if key is not None:
                        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
                        return
                self.viewport().setCursor(_handle_cursor(handle) if handle else Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)
            return
        d = self.drag
        if d.mode == "pan":
            delta = event.position() - d.last
            d.last = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        d.last = pos
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if d.mode == "guide" and self._guide_drag is not None:
            d.moved = True
            gi, orientation = self._guide_drag
            local = (pos.y() - self.page_offset.y()) if orientation == "h" else (pos.x() - self.page_offset.x())
            guides = self.page_guides()
            if gi < len(guides):
                guides[gi] = (orientation, local)
                self._build_guides()
            return
        if d.mode == "rubber" and self.rubber is not None:
            self.rubber.setRect(QRectF(d.start, pos).normalized())
            d.moved = True
        elif d.mode in ("create", "textbox"):
            d.moved = True
            if not self.is_markup_tool:
                pos = self.snap_point(pos, event.modifiers())
                d.last = pos
            self._update_create_preview(d, pos, shift)
        elif d.mode == "move":
            delta = pos - d.start
            if not d.moved and (abs(delta.x()) + abs(delta.y())) * self.zoom < 3:
                return
            d.moved = True
            if shift:
                if abs(delta.x()) > abs(delta.y()):
                    delta.setY(0)
                else:
                    delta.setX(0)
            dx, dy = self.snap_rect_delta(d.frame_rect, delta.x(), delta.y(), event.modifiers())
            self._preview_transform(QTransform.fromTranslate(dx, dy))
        elif d.mode == "scale":
            d.moved = True
            pos = self.snap_point(pos, event.modifiers())
            self._preview_transform(self._scale_transform(d, pos, event.modifiers()))
        elif d.mode == "node" and self.node_overlay is not None and d.node_key is not None:
            d.moved = True
            pos = self.snap_point(pos, event.modifiers())
            self.node_overlay.move_point(d.node_key, pos)
        elif d.mode == "penhandle":
            if (pos - d.start).manhattanLength() * self.zoom >= 4:
                d.moved = True
                self.pen_handles[-1] = pos
                self._update_pen_preview(None)

    def _create_geometry(self, d: DragState, pos: QPointF, shift: bool) -> QRectF | tuple[QPointF, QPointF]:
        if self.tool == TOOL_LINE:
            end = QPointF(pos)
            if shift:
                dx, dy = pos.x() - d.start.x(), pos.y() - d.start.y()
                ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
                length = math.hypot(dx, dy)
                end = QPointF(d.start.x() + length * math.cos(ang), d.start.y() + length * math.sin(ang))
            return d.start, end
        r = QRectF(d.start, pos).normalized()
        if shift:
            s = max(r.width(), r.height())
            x = d.start.x() if pos.x() >= d.start.x() else d.start.x() - s
            y = d.start.y() if pos.y() >= d.start.y() else d.start.y() - s
            r = QRectF(x, y, s, s)
        return r

    def _update_create_preview(self, d: DragState, pos: QPointF, shift: bool) -> None:
        geom = self._create_geometry(d, pos, shift)
        if self.preview is not None:
            self._scene.removeItem(self.preview)
            self.preview = None
        path = QPainterPath()
        if isinstance(geom, tuple):
            path.moveTo(geom[0])
            path.lineTo(geom[1])
        elif self.tool == TOOL_ELLIPSE:
            path.addEllipse(geom)
        else:
            path.addRect(geom)
        item = QGraphicsPathItem(path)
        item.setPen(self._preview_pen())
        if not isinstance(geom, tuple):
            c = QColor(theme.current().selection)
            c.setAlpha(25)
            item.setBrush(QBrush(c))
        item.setZValue(3000)
        self._scene.addItem(item)
        self.preview = item

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        d = self.drag
        if d is None:
            super().mouseReleaseEvent(event)
            return
        self.drag = None
        if d.mode == "pan":
            self._update_cursor()
            return
        pos = self.mapToScene(event.position().toPoint())
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._clear_smart()
        self._snap_targets = None
        if d.mode == "guide" and self._guide_drag is not None:
            gi, orientation = self._guide_drag
            self._guide_drag = None
            guides = self.page_guides()
            if gi < len(guides):
                local = guides[gi][1]
                limit = self.page_rect.height() if orientation == "h" else self.page_rect.width()
                if local < 0 or local > limit:
                    guides.pop(gi)
                    self.statusMessage.emit("Guide removed")
            self._build_guides()
            return
        if d.mode in ("create", "textbox") and not self.is_markup_tool:
            pos = d.last if d.moved else pos
        if d.mode == "penhandle":
            if not d.moved:
                self.pen_handles[-1] = None
            self._update_pen_preview(pos)
            return
        if d.mode == "rubber":
            rect = QRectF(d.start, pos).normalized()
            if self.rubber is not None:
                self._scene.removeItem(self.rubber)
                self.rubber = None
            if d.moved and rect.width() * self.zoom > 2:
                ids = [oid for oid, it in self.items_by_id.items() if rect.contains(it.sceneBoundingRect())]
                if ids:
                    if shift:
                        ids = self.selection + [i for i in ids if i not in self.selection]
                    self.select(ids)
                else:
                    xs = [x for x, it in self.widget_items.items() if rect.contains(it.sceneBoundingRect())]
                    if xs:
                        self.select_widgets(xs)
                    else:
                        self.select_annots([x for x, it in self.annot_items.items() if rect.contains(it.sceneBoundingRect())])
            return
        if d.mode == "textbox":
            if self.preview is not None:
                self._scene.removeItem(self.preview)
                self.preview = None
            r = QRectF(d.start, pos).normalized()
            if d.moved and r.width() * self.zoom > 12 and r.height() * self.zoom > 8:
                self.begin_text_box(r)
            else:
                self.begin_new_text(d.start)
            return
        if d.mode == "create":
            if self.preview is not None:
                self._scene.removeItem(self.preview)
                self.preview = None
            geom = self._create_geometry(d, pos, shift)
            if self.is_field_tool:
                r = geom if isinstance(geom, QRectF) else QRectF(geom[0], geom[1]).normalized()
                self.create_widget(r, self.field_tool_type())
                return
            if self.is_markup_tool or self.tool in AREA_TOOLS:
                r = geom if isinstance(geom, QRectF) else QRectF(geom[0], geom[1]).normalized()
                if r.width() * self.zoom >= 3 and r.height() * self.zoom >= 3:
                    self._apply_area_tool(r)
                return
            if isinstance(geom, tuple):
                if (geom[0] - geom[1]).manhattanLength() * self.zoom >= 3:
                    self.create_line(*geom)
            elif geom.width() * self.zoom >= 3 and geom.height() * self.zoom >= 3:
                if self.tool == TOOL_ELLIPSE:
                    self.create_ellipse(geom)
                else:
                    self.create_rect(geom)
            return
        if d.mode in ("move", "scale"):
            m = self._clear_preview()
            if d.moved and m is not None and not m.isIdentity():
                self.transform_selection(from_qtransform(m), "Move" if d.mode == "move" else "Scale")
            return
        if d.mode == "node" and self.node_overlay is not None:
            ov = self.node_overlay
            ov.active = None
            if d.moved:
                ed = self._editor()
                if ed is not None:
                    ed.set_path_geometry(ov.obj.id, ov.subpaths)
                    self._commit(ed, "Edit nodes")
            else:
                ov.update()

    def _apply_area_tool(self, r: QRectF) -> None:
        if self.doc is None:
            return
        rect = self.to_local_rect(r)
        if self.is_markup_tool:
            words = self.doc.words_in_rect(self.page_index, rect)
            if not words:
                self.statusMessage.emit("No text in that area.")
                return
            self.doc.add_markup(self.page_index, self.markup_kind(), words, author=self.author)
            self.pageEdited.emit(self.page_index)
            if self.annot_items:
                self.select_annots([max(self.annot_items)])
            return
        if self.confirm_area is not None and not self.confirm_area(self.tool, r):
            return
        if self.tool == TOOL_CROP:
            self.doc.set_cropbox_scene(self.page_index, rect)
            self.set_tool(TOOL_SELECT)
            QTimer.singleShot(0, self.zoom_fit)
        elif self.tool == TOOL_REDACT:
            self.doc.redact_area(self.page_index, rect)
        self.pageEdited.emit(self.page_index)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        if self.tool == TOOL_PEN:
            self._finish_pen(closed=False)
            return
        item = self._object_at(pos)
        if isinstance(item, ObjectItem) and isinstance(item.obj, TextRun) and self.tool in (TOOL_SELECT, TOOL_TEXT):
            self.begin_text_edit(item.obj.id)
            return
        if isinstance(item, ObjectItem) and isinstance(item.obj, PathObject) and self.tool == TOOL_SELECT:
            self.select([item.obj.id])
            self.set_tool(TOOL_NODE)
            return
        if isinstance(item, ObjectItem) and isinstance(item.obj, XObjectRef) and item.obj.subtype == "Form" and self.tool == TOOL_SELECT:
            self.select([item.obj.id])
            self.enter_form(item.obj.id)
            return
        if item is None and self.edit_path and self.tool == TOOL_SELECT:
            self.exit_form()
            return
        super().mouseDoubleClickEvent(event)

    def _scale_transform(self, d: DragState, pos: QPointF, modifiers) -> QTransform:
        r = d.frame_rect
        a = d.anchor
        start_dx = d.start.x() - a.x()
        start_dy = d.start.y() - a.y()
        sx = (pos.x() - a.x()) / start_dx if abs(start_dx) > 1e-9 else 1.0
        sy = (pos.y() - a.y()) / start_dy if abs(start_dy) > 1e-9 else 1.0
        h = d.handle or ""
        if h in ("n", "s"):
            sx = 1.0
        elif h in ("e", "w"):
            sy = 1.0
        elif not (modifiers & Qt.KeyboardModifier.ShiftModifier):
            s = sx if abs(pos.x() - a.x()) * r.height() > abs(pos.y() - a.y()) * r.width() else sy
            sx = sy = s
        sx = max(sx, 0.02) if sx > 0 else min(sx, -0.02)
        sy = max(sy, 0.02) if sy > 0 else min(sy, -0.02)
        t = QTransform()
        t.translate(a.x(), a.y())
        t.scale(sx, sy)
        t.translate(-a.x(), -a.y())
        return t

    def _preview_transform(self, t: QTransform) -> None:
        for item in self._selected_items():
            item.setTransform(t)
        self.frame.set_rect(self._selection_rect(), self.zoom)

    def _clear_preview(self) -> QTransform | None:
        m: QTransform | None = None
        for item in self._selected_items():
            if m is None:
                m = item.transform()
            item.setTransform(QTransform())
        self.frame.set_rect(self._selection_rect(), self.zoom)
        return m

    # -- keyboard ----------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            if self.text_proxy is not None:
                self._end_text_edit(commit=False)
            elif self.tool == TOOL_PEN and self.pen_points:
                self._finish_pen(closed=False)
            elif self.tool != TOOL_SELECT:
                self.set_tool(TOOL_SELECT)
            elif self.selection or self.widget_selection or self.annot_selection:
                self.clear_selection()
            elif self.edit_path:
                self.exit_form()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.tool == TOOL_PEN and self.pen_points:
            self._finish_pen(closed=bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.has_selection:
            self.delete_selection()
            return
        step = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
        arrows = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
        if key in arrows and self.has_selection:
            dx, dy = arrows[key]
            self.nudge(dx, dy)
            return
        if key == Qt.Key.Key_Return and len(self.selection) == 1:
            obj = self.items_by_id[self.selection[0]].obj
            if isinstance(obj, TextRun):
                self.begin_text_edit(obj.id)
                return
        super().keyPressEvent(event)


def _handle_cursor(handle: str) -> Qt.CursorShape:
    return {
        "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
        "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
        "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
    }.get(handle, Qt.CursorShape.ArrowCursor)
