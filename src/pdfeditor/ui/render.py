"""Rendering helpers: PyMuPDF pixmaps to Qt images, with a small cache."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtGui import QImage, QPixmap

from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Rect


def pixmap_to_qimage(pix) -> QImage:
    fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_RGBA8888
    if pix.n not in (3, 4):
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        fmt = QImage.Format.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    return img.copy()


class RenderCache:
    """LRU cache of rendered page images keyed by (page, scale, generation)."""

    def __init__(self, capacity: int = 24):
        self.capacity = capacity
        self._items: OrderedDict[tuple, QPixmap] = OrderedDict()

    def get(self, key: tuple) -> QPixmap | None:
        pm = self._items.get(key)
        if pm is not None:
            self._items.move_to_end(key)
        return pm

    def put(self, key: tuple, pm: QPixmap) -> None:
        self._items[key] = pm
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def drop_page(self, index: int) -> None:
        for key in [k for k in self._items if k[0] == index]:
            del self._items[key]


def render_page(doc: Document, index: int, scale: float, clip: Rect | None = None, annots: bool = True) -> QPixmap:
    pix = doc.render(index, scale, clip=clip, annots=annots)
    return QPixmap.fromImage(pixmap_to_qimage(pix))
