"""Rulers around the canvas; dragging from a ruler creates a guide."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from pdfeditor.ui import theme
from pdfeditor.ui.units import UNITS, current_unit

RULER_SIZE = 22
_STEPS = [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000, 5000]


class Ruler(QWidget):
    """A horizontal or vertical ruler bound to a :class:`PageCanvas`."""

    guideRequested = Signal(str, float)  # orientation ("h"/"v"), page-local coordinate
    guidePreview = Signal(str, object)  # orientation, scene coordinate or None

    def __init__(self, canvas, orientation: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.canvas = canvas
        self.orientation = orientation  # "h" (top) or "v" (left)
        self.cursor_pos: float | None = None
        self._dragging = False
        if orientation == "h":
            self.setFixedHeight(RULER_SIZE)
        else:
            self.setFixedWidth(RULER_SIZE)
        self.setMouseTracking(True)
        self.setToolTip("Drag onto the page to create a guide")

    # -- mapping ---------------------------------------------------------------------
    def _scene_from_px(self, px: float) -> float:
        vp = self.canvas.mapToScene(int(px) if self.orientation == "h" else 0, 0 if self.orientation == "h" else int(px))
        return vp.x() if self.orientation == "h" else vp.y()

    def _px_from_scene(self, v: float) -> float:
        p = self.canvas.mapFromScene(QPointF(v, 0) if self.orientation == "h" else QPointF(0, v))
        return p.x() if self.orientation == "h" else p.y()

    def set_cursor(self, scene_value: float | None) -> None:
        self.cursor_pos = scene_value
        self.update()

    # -- painting --------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(t.panel))
        pen = QPen(QColor(t.border))
        p.setPen(pen)
        if self.orientation == "h":
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        if self.canvas.doc is None:
            return
        unit = current_unit()
        upt = UNITS[unit]
        zoom = max(self.canvas.zoom, 1e-6)
        # choose a major step (in units) giving >= 60 px between labels
        major = next((s for s in _STEPS if s * upt * zoom >= 60), _STEPS[-1])
        minor = major / (5 if major in (1, 5, 10, 50, 100, 500, 1000, 5000, 0.5, 0.1) else 4)
        offset = self.canvas.page_offset
        origin = offset.x() if self.orientation == "h" else offset.y()
        length = self.width() if self.orientation == "h" else self.height()
        start_scene = self._scene_from_px(0)
        end_scene = self._scene_from_px(length)
        lo, hi = min(start_scene, end_scene), max(start_scene, end_scene)
        first = int((lo - origin) / (minor * upt)) - 1
        last = int((hi - origin) / (minor * upt)) + 1
        font = QFont()
        font.setPointSizeF(7.5)
        p.setFont(font)
        text_pen = QPen(QColor(t.text_muted))
        tick_pen = QPen(QColor(t.text_muted))
        for k in range(first, last + 1):
            value_units = k * minor
            scene_v = origin + value_units * upt
            px = self._px_from_scene(scene_v)
            if px < -2 or px > length + 2:
                continue
            is_major = abs((value_units / major) - round(value_units / major)) < 1e-6
            tick = 10 if is_major else 4
            p.setPen(tick_pen)
            if self.orientation == "h":
                p.drawLine(int(px), self.height() - tick, int(px), self.height())
                if is_major:
                    p.setPen(text_pen)
                    p.drawText(int(px) + 3, 10, _fmt(value_units))
            else:
                p.drawLine(self.width() - tick, int(px), self.width(), int(px))
                if is_major:
                    p.setPen(text_pen)
                    p.save()
                    p.translate(9, int(px) - 3)
                    p.rotate(-90)
                    p.drawText(0, 0, _fmt(value_units))
                    p.restore()
        if self.cursor_pos is not None:
            px = self._px_from_scene(self.cursor_pos)
            p.setPen(QPen(QColor(t.accent), 1))
            if self.orientation == "h":
                p.drawLine(int(px), 0, int(px), self.height())
            else:
                p.drawLine(0, int(px), self.width(), int(px))
        p.end()

    # -- guide creation by dragging ------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.canvas.doc is not None:
            self._dragging = True
            self.setCursor(Qt.CursorShape.SplitVCursor if self.orientation == "h" else Qt.CursorShape.SplitHCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        self.guidePreview.emit(self.orientation, self._scene_value(event))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.unsetCursor()
        self.guidePreview.emit(self.orientation, None)
        value = self._scene_value(event)
        vp = self.canvas.viewport()
        local = vp.mapFromGlobal(event.globalPosition().toPoint())
        if vp.rect().contains(local):
            self.guideRequested.emit(self.orientation, value)

    def _scene_value(self, event: QMouseEvent) -> float:
        vp = self.canvas.viewport()
        local = vp.mapFromGlobal(event.globalPosition().toPoint())
        scene = self.canvas.mapToScene(local)
        # a guide from the top ruler is horizontal (fixed y); from the left ruler vertical (fixed x)
        return scene.y() if self.orientation == "h" else scene.x()


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"
