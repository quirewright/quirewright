"""The page canvas: renders a page and overlays editable objects.

The scene coordinate system is PyMuPDF's page space in points (origin at the
top-left of the rotated, cropped page, y down). The rendered page bitmap is
placed as a pixmap item scaled back to points; selectable objects get
invisible hit-test items on top, plus a selection frame with scale handles,
a node editor for paths, and an inline text editor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
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
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLineEdit,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pdfeditor.core.content.model import GObject, PathObject, TextRun, XObjectRef
from pdfeditor.core.content.writer import ContentEditor
from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Matrix, Rect
from pdfeditor.ui import theme
from pdfeditor.ui.render import RenderCache, render_page

TOOL_SELECT = "select"
TOOL_NODE = "node"
TOOL_TEXT = "text"
TOOL_HAND = "hand"

HANDLE_PX = 8.0
MIN_ZOOM = 0.1
MAX_ZOOM = 16.0


def qmatrix(m: Matrix) -> QTransform:
    return QTransform(m.a, m.b, m.c, m.d, m.e, m.f)


def from_qtransform(t: QTransform) -> Matrix:
    return Matrix(t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def rect_to_qrect(r: Rect) -> QRectF:
    return QRectF(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0)


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
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents, False)

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
        if self.obj.kind == "text" and self.obj.invisible:  # type: ignore[attr-defined]
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


class SelectionFrame(QGraphicsItem):
    """Bounding box of the current selection with eight scale handles."""

    HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

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
        self.active: tuple[int, int, int] | None = None  # (subpath, segment, point index)
        self.hover: tuple[int, int, int] | None = None
        self.setZValue(2000)
        self.setAcceptHoverEvents(True)

    # points: iterate (subpath idx, seg idx, point idx (0,1,2 for c; 0 for m/l), user x, y, is_anchor)
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
        # Moving an anchor drags the attached control handles along
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
        # control handle lines
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


# --- drag state --------------------------------------------------------------

@dataclass
class DragState:
    mode: str  # "move", "scale", "rubber", "pan", "node"
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
        self.items_by_id: dict[int, ObjectItem] = {}
        self.selection: list[int] = []
        self.frame = SelectionFrame()
        self._scene.addItem(self.frame)
        self.node_overlay: NodeOverlay | None = None
        self.text_proxy: QGraphicsProxyWidget | None = None
        self.text_edit_id: int | None = None
        self.rubber: QGraphicsRectItem | None = None
        self.drag: DragState | None = None
        self.pdf_to_scene = Matrix()
        self.page_rect = QRectF(0, 0, 612, 792)
        self.scale_stroke = True

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._render_now)

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
        if doc is not None:
            doc.add_listener(self._on_doc_event)
        self.rebuild()

    def _on_doc_event(self, event: str, payload) -> None:
        if event == "page_content":
            self.cache.drop_page(payload)
            if payload == self.page_index:
                self.rebuild(keep_selection=True)
        elif event in ("pages", "saved"):
            self.cache.clear()
            if self.doc is not None and self.page_index >= self.doc.page_count:
                self.page_index = max(0, self.doc.page_count - 1)
            self.rebuild()

    def set_page(self, index: int) -> None:
        if self.doc is None:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        if index == self.page_index:
            return
        self.page_index = index
        self.selection = []
        self.rebuild()
        self.selectionChanged.emit([])

    def set_tool(self, tool: str) -> None:
        if tool == self.tool:
            return
        self._end_text_edit(commit=False)
        self.tool = tool
        self._update_node_overlay()
        self._update_cursor()
        self.toolChanged.emit(tool)

    def _update_cursor(self) -> None:
        if self.tool == TOOL_HAND:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.tool == TOOL_TEXT:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    # -- building the scene ---------------------------------------------
    def rebuild(self, keep_selection: bool = False) -> None:
        self._end_text_edit(commit=False)
        old_selection = list(self.selection) if keep_selection else []
        self._scene.removeItem(self.frame)
        self._scene.clear()
        self.items_by_id = {}
        self.page_item = None
        self.node_overlay = None
        self.text_proxy = None
        self.rubber = None
        self._scene.addItem(self.frame)
        self.frame.set_rect(QRectF(), self.zoom)
        if self.doc is None or self.doc.page_count == 0:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            self.viewport().update()
            return
        r = self.doc.page_rect(self.page_index)
        self.page_rect = QRectF(r.x0, r.y0, r.width, r.height)
        self.pdf_to_scene = self.doc.pdf_to_page_matrix(self.page_index)
        margin = 40 / max(self.zoom, 0.2)
        self._scene.setSceneRect(self.page_rect.adjusted(-margin, -margin, margin, margin))
        # page shadow + bitmap
        shadow = QGraphicsRectItem(self.page_rect.translated(2, 3))
        shadow.setBrush(QBrush(QColor(0, 0, 0, 40)))
        shadow.setPen(Qt.PenStyle.NoPen)
        shadow.setZValue(-2)
        self._scene.addItem(shadow)
        self.page_item = QGraphicsPixmapItem()
        self.page_item.setZValue(-1)
        self.page_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self.page_item)
        self._render_now()
        self._build_overlay()
        self.selection = [i for i in old_selection if i in self.items_by_id]
        self._update_selection_visuals()
        self._update_node_overlay()

    def _build_overlay(self) -> None:
        assert self.doc is not None
        try:
            content = self.doc.content(self.page_index)
        except Exception as exc:  # pragma: no cover
            self.statusMessage.emit(f"Could not parse page content: {exc}")
            return
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
        """Tight rotated quad for a text run (text space box mapped through its matrices)."""
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
        if self.doc is None or self.page_item is None:
            return
        dpr = self.devicePixelRatioF()
        scale = self.zoom * dpr
        key = (self.page_index, round(scale, 3), self.generation)
        pm = self.cache.get(key)
        if pm is None:
            try:
                pm = render_page(self.doc, self.page_index, scale)
            except Exception as exc:  # pragma: no cover
                self.statusMessage.emit(f"Render failed: {exc}")
                return
            self.cache.put(key, pm)
        self.page_item.setPixmap(pm)
        self.page_item.setPos(self.page_rect.topLeft())
        self.page_item.setScale(1.0 / scale)

    def _schedule_render(self) -> None:
        self._render_timer.start()

    # -- zoom --------------------------------------------------------------
    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.zoom = zoom
        self.setTransform(QTransform.fromScale(zoom, zoom))
        margin = 40 / max(self.zoom, 0.2)
        self._scene.setSceneRect(self.page_rect.adjusted(-margin, -margin, margin, margin))
        self.frame.set_rect(self.frame.rect, zoom)
        if self.node_overlay is not None:
            self.node_overlay.zoom = zoom
            self.node_overlay.update()
        self._schedule_render()
        self.zoomChanged.emit(zoom)

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
        self.centerOn(self.page_rect.center())

    def zoom_width(self) -> None:
        vp = self.viewport().rect()
        if self.page_rect.isEmpty():
            return
        self.set_zoom((vp.width() - 48) / self.page_rect.width())
        self.centerOn(QPointF(self.page_rect.center().x(), self.page_rect.top() + vp.height() / (2 * self.zoom)))

    def zoom_actual(self) -> None:
        self.set_zoom(1.0)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.0015 ** delta
            self.set_zoom(self.zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    # -- selection -------------------------------------------------------
    def selected_objects(self) -> list[GObject]:
        return [self.items_by_id[i].obj for i in self.selection if i in self.items_by_id]

    def select(self, ids: list[int], emit: bool = True) -> None:
        self.selection = [i for i in ids if i in self.items_by_id]
        self._update_selection_visuals()
        self._update_node_overlay()
        if emit:
            self.selectionChanged.emit(list(self.selection))

    def select_all(self) -> None:
        self.select(list(self.items_by_id.keys()))

    def clear_selection(self) -> None:
        self.select([])

    def _update_selection_visuals(self) -> None:
        sel = set(self.selection)
        for oid, item in self.items_by_id.items():
            item.set_selected(oid in sel)
        self.frame.set_rect(self._selection_rect(), self.zoom)

    def _selection_rect(self) -> QRectF:
        rect = QRectF()
        for oid in self.selection:
            item = self.items_by_id.get(oid)
            if item is None:
                continue
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
    def _editor(self) -> ContentEditor | None:
        if self.doc is None:
            return None
        return ContentEditor(self.doc.content(self.page_index))

    def _commit(self, editor: ContentEditor, label: str) -> None:
        assert self.doc is not None
        try:
            data = editor.build()
        except Exception as exc:
            self.statusMessage.emit(f"Edit failed: {exc}")
            return
        self.doc.apply_content_edit(self.page_index, data, label)
        self.pageEdited.emit(self.page_index)

    def scene_matrix_to_pdf(self, m: Matrix) -> Matrix:
        S = self.pdf_to_scene
        return S * m * S.inverted()

    def transform_selection(self, m_scene: Matrix, label: str = "Transform") -> None:
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
        if not self.selection:
            return
        ed = self._editor()
        if ed is None:
            return
        ed.delete(list(self.selection))
        self.selection = []
        self._commit(ed, "Delete")
        self.selectionChanged.emit([])

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

    def set_text(self, oid: int, text: str) -> bool:
        ed = self._editor()
        if ed is None or self.doc is None:
            return False
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return False
        if item.obj.text == text:
            return True
        ok = ed.set_text(oid, text)
        if not ok:
            try:
                sub = self.doc.ensure_substitute_font(self.page_index)
            except Exception as exc:
                self.statusMessage.emit(f"Could not add substitute font: {exc}")
                return False
            ok = ed.set_text(oid, text, substitute=sub)
            if ok:
                font = item.obj.font_info.display_name if item.obj.font_info else item.obj.font
                self.statusMessage.emit(f"Some characters are not in the embedded font “{font}”; substituted Helvetica.")
        if not ok:
            self.statusMessage.emit("Text could not be encoded.")
            return False
        self._commit(ed, "Edit text")
        return True

    # -- inline text editing -----------------------------------------------
    def begin_text_edit(self, oid: int) -> None:
        item = self.items_by_id.get(oid)
        if item is None or not isinstance(item.obj, TextRun):
            return
        self._end_text_edit(commit=False)
        run = item.obj
        rect = item.sceneBoundingRect()
        edit = QLineEdit(run.text)
        t = theme.current()
        size_pt = max(run.state.font_size * run.state.ctm.expansion() * self.pdf_to_scene.expansion(), 4.0)
        font = QFont()
        font.setPixelSize(int(round(size_pt)))
        edit.setFont(font)
        edit.setStyleSheet(
            f"QLineEdit {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.accent}; border-radius: 2px; padding: 0 2px; }}"
        )
        edit.setMinimumWidth(int(max(rect.width() + 24, 80)))
        proxy = self._scene.addWidget(edit)
        proxy.setZValue(5000)
        proxy.setPos(rect.left() - 3, rect.top() - 2)
        self.text_proxy = proxy
        self.text_edit_id = oid
        edit.returnPressed.connect(lambda: self._end_text_edit(commit=True))
        edit.installEventFilter(self)
        edit.setFocus()
        edit.selectAll()
        self.statusMessage.emit("Editing text: Enter to apply, Esc to cancel")

    def _end_text_edit(self, commit: bool) -> None:
        proxy = self.text_proxy
        if proxy is None:
            return
        oid = self.text_edit_id
        widget = proxy.widget()
        text = widget.text() if isinstance(widget, QLineEdit) else None
        self.text_proxy = None
        self.text_edit_id = None
        try:
            self._scene.removeItem(proxy)
        except RuntimeError:
            pass
        proxy.deleteLater()
        self.setFocus()
        if commit and oid is not None and text is not None:
            self.set_text(oid, text)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self._end_text_edit(commit=False)
                return True
        if event.type() == QEvent.Type.FocusOut and self.text_proxy is not None:
            self._end_text_edit(commit=True)
            return False
        return super().eventFilter(obj, event)

    # -- mouse handling ---------------------------------------------------------
    def _object_at(self, pos: QPointF) -> ObjectItem | None:
        for it in self._scene.items(pos, Qt.ItemSelectionMode.IntersectsItemShape, Qt.SortOrder.DescendingOrder):
            if isinstance(it, ObjectItem):
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
            if item is not None and isinstance(item.obj, TextRun):
                self.select([item.obj.id])
                self.begin_text_edit(item.obj.id)
            else:
                self.clear_selection()
            return
        if item is None:
            if not shift:
                self.clear_selection()
            self.drag = DragState("rubber", pos, pos)
            self.rubber = QGraphicsRectItem()
            t = theme.current()
            pen = QPen(QColor(t.selection), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self.rubber.setPen(pen)
            c = QColor(t.selection)
            c.setAlpha(30)
            self.rubber.setBrush(QBrush(c))
            self.rubber.setZValue(3000)
            self._scene.addItem(self.rubber)
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
        self.drag = DragState("move", pos, pos)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag is None:
            if self.tool in (TOOL_SELECT, TOOL_NODE):
                pos = self.mapToScene(event.position().toPoint())
                handle = self.frame.handle_at(pos)
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
        pos = self.mapToScene(event.position().toPoint())
        d.last = pos
        if d.mode == "rubber" and self.rubber is not None:
            self.rubber.setRect(QRectF(d.start, pos).normalized())
            d.moved = True
        elif d.mode == "move":
            delta = pos - d.start
            if not d.moved and (abs(delta.x()) + abs(delta.y())) * self.zoom < 3:
                return
            d.moved = True
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if abs(delta.x()) > abs(delta.y()):
                    delta.setY(0)
                else:
                    delta.setX(0)
            self._preview_transform(QTransform.fromTranslate(delta.x(), delta.y()))
        elif d.mode == "scale":
            d.moved = True
            self._preview_transform(self._scale_transform(d, pos, event.modifiers()))
        elif d.mode == "node" and self.node_overlay is not None and d.node_key is not None:
            d.moved = True
            self.node_overlay.move_point(d.node_key, pos)

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
        if d.mode == "rubber":
            rect = QRectF(d.start, pos).normalized()
            if self.rubber is not None:
                self._scene.removeItem(self.rubber)
                self.rubber = None
            if d.moved and rect.width() * self.zoom > 2:
                ids = [oid for oid, it in self.items_by_id.items() if rect.contains(it.sceneBoundingRect())]
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    ids = self.selection + [i for i in ids if i not in self.selection]
                self.select(ids)
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = self.mapToScene(event.position().toPoint())
        item = self._object_at(pos)
        if item is not None and isinstance(item.obj, TextRun) and self.tool in (TOOL_SELECT, TOOL_TEXT):
            self.select([item.obj.id])
            self.begin_text_edit(item.obj.id)
            return
        if item is not None and isinstance(item.obj, PathObject) and self.tool == TOOL_SELECT:
            self.select([item.obj.id])
            self.set_tool(TOOL_NODE)
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
        for oid in self.selection:
            item = self.items_by_id.get(oid)
            if item is not None:
                item.setTransform(t)
        self.frame.set_rect(self._selection_rect(), self.zoom)

    def _clear_preview(self) -> QTransform | None:
        m: QTransform | None = None
        for oid in self.selection:
            item = self.items_by_id.get(oid)
            if item is not None:
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
            elif self.tool == TOOL_NODE:
                self.set_tool(TOOL_SELECT)
            else:
                self.clear_selection()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selection:
            self.delete_selection()
            return
        step = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
        arrows = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0), Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}
        if key in arrows and self.selection:
            dx, dy = arrows[key]
            self.nudge(dx, dy)
            return
        if key == Qt.Key.Key_Return and len(self.selection) == 1:
            obj = self.items_by_id[self.selection[0]].obj
            if isinstance(obj, TextRun):
                self.begin_text_edit(obj.id)
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)


def _handle_cursor(handle: str) -> Qt.CursorShape:
    return {
        "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
        "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
        "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
    }.get(handle, Qt.CursorShape.ArrowCursor)
