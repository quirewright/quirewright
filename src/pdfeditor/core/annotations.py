"""Annotation (comment) support: text markup, sticky notes, listing and editing.

Implemented as a mixin for :class:`pdfeditor.core.document.Document`.
Rectangles exchanged with the UI are in scene space (rotated page, y down).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pymupdf

from pdfeditor.core.geometry import Matrix, Rect

ANNOT_TYPE_NAMES = {
    0: "Text note", 1: "Link", 2: "Free text", 3: "Line", 4: "Square", 5: "Circle", 6: "Polygon", 7: "Polyline",
    8: "Highlight", 9: "Underline", 10: "Squiggly", 11: "Strike-out", 12: "Redaction", 13: "Stamp", 14: "Caret",
    15: "Ink", 16: "Popup", 17: "File attachment", 18: "Sound", 19: "Movie", 20: "Rich media", 21: "Widget",
    22: "Screen", 23: "Printer mark", 24: "Trap net", 25: "Watermark", 26: "3D", 27: "Projection",
}
MARKUP_TYPES = {"highlight": 8, "underline": 9, "strikeout": 11, "squiggly": 10}
DEFAULT_MARKUP_COLORS = {
    "highlight": (1.0, 0.92, 0.23), "underline": (0.1, 0.5, 1.0), "strikeout": (0.9, 0.2, 0.2), "squiggly": (0.2, 0.7, 0.3),
}
NOTE_ICONS = ["Comment", "Note", "Help", "Insert", "Key", "NewParagraph", "Paragraph"]


@dataclass
class AnnotInfo:
    xref: int
    type: int
    rect: Rect  # scene space
    contents: str = ""
    author: str = ""
    color: tuple | None = None
    opacity: float = 1.0
    modified: str = ""
    icon: str = ""

    @property
    def type_name(self) -> str:
        return ANNOT_TYPE_NAMES.get(self.type, "Annotation")

    @property
    def movable(self) -> bool:
        return self.type in (0, 2, 3, 4, 5, 13, 15, 17)


def _scene_rect(page, r) -> Rect:
    rr = pymupdf.Rect(r) * page.rotation_matrix
    return Rect.normalized(rr.x0, rr.y0, rr.x1, rr.y1)


def _unrotated(page, r: Rect) -> pymupdf.Rect:
    rr = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1) * page.derotation_matrix
    rr.normalize()
    return rr


class AnnotationMixin:
    def annotations(self, index: int) -> list[AnnotInfo]:
        page = self.pdf[index]
        out: list[AnnotInfo] = []
        try:
            iterator = list(page.annots())
        except Exception:
            return out
        for a in iterator:
            try:
                t = a.type[0]
                if t in (16, 21, 1):  # popups, widgets and links are not comments
                    continue
                info_d = a.info or {}
                colors = a.colors or {}
                col = colors.get("stroke") or colors.get("fill")
                out.append(AnnotInfo(
                    xref=a.xref, type=int(t), rect=_scene_rect(page, a.rect), contents=info_d.get("content", "") or "",
                    author=info_d.get("title", "") or "", color=tuple(col) if col else None, opacity=float(a.opacity if a.opacity >= 0 else 1.0),
                    modified=info_d.get("modDate", "") or "", icon=info_d.get("name", "") or "",
                ))
            except Exception:
                continue
        return out

    def _find_annot(self, page, xref: int):
        for a in page.annots():
            if a.xref == xref:
                return a
        return None

    def add_markup(self, index: int, kind: str, rects_scene: Iterable[Rect], color: tuple | None = None, author: str = "") -> None:
        rects = list(rects_scene)
        if not rects:
            return
        color = color or DEFAULT_MARKUP_COLORS.get(kind, (1, 1, 0))

        def action(doc) -> None:
            page = doc.pdf[index]
            quads = [_unrotated(page, r).quad for r in rects]
            fn = {
                "highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
                "strikeout": page.add_strikeout_annot, "squiggly": page.add_squiggly_annot,
            }[kind]
            a = fn(quads)
            a.set_colors(stroke=color)
            if author:
                a.set_info(title=author)
            a.update()

        self._structure_op(f"Add {kind}", action)

    def add_note(self, index: int, point_scene: tuple[float, float], contents: str = "", author: str = "", icon: str = "Comment", color: tuple = (1.0, 0.8, 0.2)) -> None:
        def action(doc) -> None:
            page = doc.pdf[index]
            p = pymupdf.Point(point_scene[0], point_scene[1]) * page.derotation_matrix
            a = page.add_text_annot(p, contents, icon=icon)
            a.set_colors(stroke=color)
            if author:
                a.set_info(title=author)
            a.update()

        self._structure_op("Add note", action)

    def update_annotation(self, index: int, xref: int, **props) -> None:
        def action(doc) -> None:
            page = doc.pdf[index]
            a = doc._find_annot(page, xref)
            if a is None:
                return
            info = {}
            if "contents" in props:
                info["content"] = props["contents"]
            if "author" in props:
                info["title"] = props["author"]
            if info:
                a.set_info(**info)
            if "icon" in props and props["icon"]:
                try:
                    a.set_name(props["icon"])
                except Exception:
                    pass
            if "color" in props and props["color"] is not None:
                a.set_colors(stroke=props["color"])
            if "opacity" in props:
                a.set_opacity(float(props["opacity"]))
            if "rect" in props:
                a.set_rect(_unrotated(page, props["rect"]))
            a.update()

        self._structure_op("Edit annotation", action)

    def delete_annotations(self, index: int, xrefs: Iterable[int]) -> None:
        xs = set(xrefs)

        def action(doc) -> None:
            page = doc.pdf[index]
            for a in list(page.annots()):
                if a.xref in xs:
                    page.delete_annot(a)

        self._structure_op("Delete annotation(s)", action)

    def transform_annotations(self, index: int, xrefs: Iterable[int], m_scene: Matrix) -> None:
        xs = list(xrefs)

        def action(doc) -> None:
            page = doc.pdf[index]
            for a in list(page.annots()):
                if a.xref not in xs:
                    continue
                r = _scene_rect(page, a.rect).transformed(m_scene)
                a.set_rect(_unrotated(page, r))
                a.update()

        self._structure_op("Move annotation(s)", action)
