"""Object model for an interpreted page content stream.

Every editable thing on a page (a filled/stroked path, a run of text, a placed
image or form XObject, an inline image, a shading) becomes a
:class:`GObject` carrying:

* the graphics state in effect when it was painted,
* the *base* state it is diffed against when rewritten,
* the byte span of the operators that produced it, and
* its device-space bounding box.

"Device space" throughout the core means the PDF default user space of the
page (origin at the bottom-left of the MediaBox, y up). The UI maps that to
screen coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Union

from pdfeditor.core.geometry import Matrix, Rect

if TYPE_CHECKING:  # pragma: no cover
    from pdfeditor.core.fonts import FontInfo


@dataclass(frozen=True, slots=True)
class Color:
    """A colour in some colour space.

    ``space`` is a PDF colour space name (``DeviceGray``, ``DeviceRGB``,
    ``DeviceCMYK``, or any resource name); ``components`` are the raw numeric
    operands; ``pattern`` holds a pattern resource name for ``/P scn``.
    """

    space: str = "DeviceGray"
    components: tuple[float, ...] = (0.0,)
    pattern: str | None = None

    def to_rgb(self) -> tuple[float, float, float] | None:
        """Best-effort conversion to an RGB triple in 0..1, or None if unknown."""
        c = self.components
        if self.pattern is not None:
            return None
        n = len(c)
        if self.space in ("DeviceGray", "G", "CalGray") or n == 1:
            if n >= 1:
                g = _clamp(c[0])
                return (g, g, g)
            return None
        if self.space in ("DeviceRGB", "RGB", "CalRGB") or n == 3:
            if n >= 3:
                return (_clamp(c[0]), _clamp(c[1]), _clamp(c[2]))
            return None
        if self.space in ("DeviceCMYK", "CMYK") or n == 4:
            if n >= 4:
                cc, m, y, k = (_clamp(v) for v in c[:4])
                return ((1 - cc) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
            return None
        return None


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


BLACK = Color("DeviceGray", (0.0,))


@dataclass(slots=True)
class GraphicsState:
    ctm: Matrix = field(default_factory=Matrix)
    stroke_color: Color = BLACK
    fill_color: Color = BLACK
    stroke_space: str = "DeviceGray"
    fill_space: str = "DeviceGray"
    line_width: float = 1.0
    line_cap: int = 0
    line_join: int = 0
    miter_limit: float = 10.0
    dash: tuple[tuple[float, ...], float] = ((), 0.0)
    ext_gstate: str | None = None
    clip_bbox: Rect | None = None  # device space; None = unclipped
    # text state (part of the graphics state per the PDF spec)
    font: str | None = None
    font_size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    hscale: float = 1.0  # Tz / 100
    leading: float = 0.0
    rise: float = 0.0
    render_mode: int = 0

    def copy(self) -> "GraphicsState":
        return replace(self)


# --- path geometry ----------------------------------------------------------

# Segment tuples, all in *user space* of the object's CTM:
#   ("m", x, y)                     move to
#   ("l", x, y)                     line to
#   ("c", x1, y1, x2, y2, x3, y3)   cubic bezier
#   ("h",)                          close subpath
Segment = tuple


@dataclass(slots=True)
class GObject:
    id: int
    kind: str  # "path", "clip", "text", "image", "form", "inline_image", "shading"
    span: tuple[int, int]
    state: GraphicsState
    base_state: GraphicsState
    wrapper_span: tuple[int, int] | None = None
    bbox: Rect | None = None  # device space, unclipped
    sequence: int = 0  # paint order

    @property
    def visible_bbox(self) -> Rect | None:
        if self.bbox is None:
            return None
        clip = self.state.clip_bbox
        if clip is None:
            return self.bbox
        r = self.bbox.intersect(clip)
        return None if r.is_empty else r

    @property
    def selectable(self) -> bool:
        return self.kind in ("path", "text", "image", "form", "inline_image", "shading")

    @property
    def ctm(self) -> Matrix:
        return self.state.ctm


@dataclass(slots=True)
class PathObject(GObject):
    subpaths: list[list[Segment]] = field(default_factory=list)
    fill: bool = False
    stroke: bool = False
    even_odd: bool = False
    is_clip: bool = False
    clip_even_odd: bool = False
    paint_op: str = "n"

    def device_points(self) -> list[tuple[float, float]]:
        m = self.state.ctm
        pts = []
        for sp in self.subpaths:
            for seg in sp:
                for i in range(1, len(seg), 2):
                    pts.append(m.apply(seg[i], seg[i + 1]))
        return pts


@dataclass(slots=True)
class Glyph:
    code: int
    text: str
    width: float  # text-space advance (units of font size 1), includes nothing else
    advance: float  # total horizontal displacement in text space incl. spacing & hscale
    origin: tuple[float, float]  # device-space glyph origin
    bbox: Rect | None  # device-space bbox


@dataclass(slots=True)
class OpaqueOp:
    """An operator inside a BT/ET block that the editor preserves verbatim."""

    span: tuple[int, int]


@dataclass(slots=True)
class TextRun(GObject):
    font: str = ""
    font_size: float = 0.0
    tm: Matrix = field(default_factory=Matrix)  # text matrix at start of run
    items: list[Union[bytes, float]] = field(default_factory=list)  # TJ array or [bytes]
    op: str = "Tj"
    glyphs: list[Glyph] = field(default_factory=list)
    text: str = ""
    block: "TextBlock | None" = None
    font_info: "FontInfo | None" = None
    deleted: bool = False
    end_tm: Matrix = field(default_factory=Matrix)  # text matrix after the run

    @property
    def invisible(self) -> bool:
        return self.state.render_mode in (3, 7)

    def text_render_matrix(self) -> Matrix:
        """Matrix mapping text space (size 1) to device space for this run."""
        s = self.state
        return Matrix(s.font_size * s.hscale, 0, 0, s.font_size, 0, s.rise) * self.tm * s.ctm


@dataclass(slots=True)
class XObjectRef(GObject):
    name: str = ""
    subtype: str = "Image"  # or "Form"
    form_bbox: Rect | None = None  # /BBox of form xobjects (form space)
    form_matrix: Matrix = field(default_factory=Matrix)

    def unit_rect(self) -> Rect:
        return Rect(0, 0, 1, 1)


@dataclass(slots=True)
class InlineImage(GObject):
    params: dict = field(default_factory=dict)


@dataclass(slots=True)
class ShadingObject(GObject):
    name: str = ""


@dataclass(slots=True)
class TextBlock:
    span: tuple[int, int]  # from "BT" to end of "ET"
    items: list[Union[TextRun, OpaqueOp]] = field(default_factory=list)
    start_state: GraphicsState | None = None  # state at BT
    end_state: GraphicsState | None = None  # state at ET (after text state ops)
    inside_wrapper: tuple[int, int] | None = None


@dataclass(slots=True)
class PageContent:
    stream: bytes
    objects: list[GObject] = field(default_factory=list)
    blocks: list[TextBlock] = field(default_factory=list)
    fonts: dict = field(default_factory=dict)  # resource name -> FontInfo
    warnings: list[str] = field(default_factory=list)

    def by_id(self, oid: int) -> GObject:
        return self.objects[oid]

    def selectable_objects(self) -> list[GObject]:
        return [o for o in self.objects if o.selectable and o.visible_bbox is not None]
