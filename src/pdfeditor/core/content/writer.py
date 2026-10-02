"""Write edited objects back into a content stream.

The strategy is span replacement: each edited object is re-serialized from the
model and spliced over the bytes that originally produced it. Paths, XObjects,
inline images and shadings are wrapped in ``q ... Q`` with only the state
differences needed; text runs are rewritten by regenerating their whole
``BT ... ET`` block with absolute ``Tm`` positioning so edits never disturb
neighbouring runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pdfeditor.core.content.model import (
    Color,
    GObject,
    GraphicsState,
    InlineImage,
    OpaqueOp,
    PageContent,
    PathObject,
    ShadingObject,
    TextBlock,
    TextRun,
    XObjectRef,
)
from pdfeditor.core.fonts import FontInfo
from pdfeditor.core.geometry import Matrix


# --- serialization helpers --------------------------------------------------

def fmt(v: float) -> bytes:
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v)).encode()
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s.encode()


def fmt_matrix(m: Matrix) -> bytes:
    return b" ".join(fmt(v) for v in m.as_tuple())


def fmt_name(name: str) -> bytes:
    out = bytearray(b"/")
    for ch in name.encode("latin-1", errors="replace"):
        if ch < 33 or ch > 126 or ch in b"()<>[]{}/%#":
            out += b"#%02X" % ch
        else:
            out.append(ch)
    return bytes(out)


def fmt_string(data: bytes, force_hex: bool = False) -> bytes:
    if force_hex or any(b < 32 or b > 126 for b in data):
        return b"<" + data.hex().encode() + b">"
    out = bytearray(b"(")
    for b in data:
        if b in b"()\\":
            out += b"\\" + bytes([b])
        else:
            out.append(b)
    out += b")"
    return bytes(out)


def serialize_subpaths(subpaths: Iterable[Iterable[tuple]]) -> bytes:
    parts: list[bytes] = []
    for sp in subpaths:
        for seg in sp:
            op = seg[0]
            if op == "h":
                parts.append(b"h")
            else:
                parts.append(b" ".join(fmt(v) for v in seg[1:]) + b" " + op.encode())
    return b"\n".join(parts)


def paint_operator(fill: bool, stroke: bool, even_odd: bool) -> bytes:
    if fill and stroke:
        return b"B*" if even_odd else b"B"
    if fill:
        return b"f*" if even_odd else b"f"
    if stroke:
        return b"S"
    return b"n"


def _color_ops(cur: Color, cur_space: str, new: Color, new_space: str, stroking: bool) -> list[bytes]:
    if cur == new and cur_space == new_space:
        return []
    comps = b" ".join(fmt(c) for c in new.components)
    if new.pattern is None:
        if new.space == "DeviceGray" and len(new.components) == 1:
            return [comps + (b" G" if stroking else b" g")]
        if new.space == "DeviceRGB" and len(new.components) == 3:
            return [comps + (b" RG" if stroking else b" rg")]
        if new.space == "DeviceCMYK" and len(new.components) == 4:
            return [comps + (b" K" if stroking else b" k")]
    ops: list[bytes] = []
    if new.space != cur_space or cur.pattern is not None or new.pattern is not None:
        ops.append(fmt_name(new.space) + (b" CS" if stroking else b" cs"))
    tail = b" SCN" if stroking else b" scn"
    if new.pattern is not None:
        ops.append((comps + b" " if comps else b"") + fmt_name(new.pattern) + tail)
    elif comps:
        ops.append(comps + tail)
    return ops


def diff_ops(base: GraphicsState, new: GraphicsState, *, ctm: bool = True, text: bool = False, gs: bool = True) -> list[bytes]:
    """Operators that turn ``base`` into ``new`` (for the modeled fields)."""
    ops: list[bytes] = []
    if ctm and new.ctm != base.ctm:
        try:
            cm = new.ctm * base.ctm.inverted()
        except ValueError:
            cm = new.ctm
        if not cm.is_identity():
            ops.append(fmt_matrix(cm) + b" cm")
    if gs and new.ext_gstate and new.ext_gstate != base.ext_gstate:
        ops.append(fmt_name(new.ext_gstate) + b" gs")
    ops += _color_ops(base.fill_color, base.fill_space, new.fill_color, new.fill_space, False)
    ops += _color_ops(base.stroke_color, base.stroke_space, new.stroke_color, new.stroke_space, True)
    if new.line_width != base.line_width:
        ops.append(fmt(new.line_width) + b" w")
    if new.line_cap != base.line_cap:
        ops.append(fmt(new.line_cap) + b" J")
    if new.line_join != base.line_join:
        ops.append(fmt(new.line_join) + b" j")
    if new.miter_limit != base.miter_limit:
        ops.append(fmt(new.miter_limit) + b" M")
    if new.dash != base.dash:
        arr = b"[" + b" ".join(fmt(v) for v in new.dash[0]) + b"]"
        ops.append(arr + b" " + fmt(new.dash[1]) + b" d")
    if text:
        if (new.font, new.font_size) != (base.font, base.font_size) and new.font is not None:
            ops.append(fmt_name(new.font) + b" " + fmt(new.font_size) + b" Tf")
        if new.char_spacing != base.char_spacing:
            ops.append(fmt(new.char_spacing) + b" Tc")
        if new.word_spacing != base.word_spacing:
            ops.append(fmt(new.word_spacing) + b" Tw")
        if new.hscale != base.hscale:
            ops.append(fmt(new.hscale * 100.0) + b" Tz")
        if new.leading != base.leading:
            ops.append(fmt(new.leading) + b" TL")
        if new.rise != base.rise:
            ops.append(fmt(new.rise) + b" Ts")
        if new.render_mode != base.render_mode:
            ops.append(fmt(new.render_mode) + b" Tr")
    return ops


def _sync_state(cur: GraphicsState, new: GraphicsState, text: bool) -> None:
    """Copy the fields emitted by :func:`diff_ops` from ``new`` into ``cur``."""
    cur.fill_color, cur.fill_space = new.fill_color, new.fill_space
    cur.stroke_color, cur.stroke_space = new.stroke_color, new.stroke_space
    cur.line_width, cur.line_cap, cur.line_join = new.line_width, new.line_cap, new.line_join
    cur.miter_limit, cur.dash = new.miter_limit, new.dash
    if text:
        if new.font is not None:
            cur.font, cur.font_size = new.font, new.font_size
        cur.char_spacing, cur.word_spacing, cur.hscale = new.char_spacing, new.word_spacing, new.hscale
        cur.leading, cur.rise, cur.render_mode = new.leading, new.rise, new.render_mode


# --- the editor -------------------------------------------------------------

@dataclass
class _Replacement:
    start: int
    end: int
    data: bytes


class ContentEditor:
    """Accumulates edits against a :class:`PageContent` and builds the new stream."""

    def __init__(self, content: PageContent):
        self.content = content
        self.stream = content.stream
        self._dirty: set[int] = set()  # object ids with pending re-serialization
        self._deleted: set[int] = set()
        self._dirty_blocks: set[int] = set()  # id(block)
        self._blocks_by_id: dict[int, TextBlock] = {}
        self._appends: list[bytes] = []

    # -- mutations -------------------------------------------------------
    def _obj(self, oid: int) -> GObject:
        return self.content.objects[oid]

    def _mark(self, obj: GObject) -> None:
        if isinstance(obj, TextRun) and obj.block is not None:
            self._dirty_blocks.add(id(obj.block))
            self._blocks_by_id[id(obj.block)] = obj.block
        else:
            self._dirty.add(obj.id)

    def transform(self, ids: Iterable[int], m: Matrix, scale_stroke: bool = True) -> None:
        """Apply device-space transform ``m`` to the given objects."""
        for oid in ids:
            obj = self._obj(oid)
            ctm = obj.state.ctm
            try:
                user = ctm * m * ctm.inverted()
            except ValueError:
                continue
            if isinstance(obj, PathObject):
                if obj.kind == "clip":
                    continue
                obj.subpaths = [
                    [_transform_segment(seg, user) for seg in sp] for sp in obj.subpaths
                ]
                if scale_stroke and obj.stroke:
                    k = user.expansion()
                    if abs(k - 1.0) > 1e-6:
                        obj.state.line_width *= k
                        if obj.state.dash[0]:
                            obj.state.dash = (tuple(v * k for v in obj.state.dash[0]), obj.state.dash[1] * k)
            elif isinstance(obj, TextRun):
                obj.tm = obj.tm * user
            elif isinstance(obj, (XObjectRef, InlineImage, ShadingObject)):
                obj.state.ctm = ctm * m
            else:
                continue
            if obj.bbox is not None:
                obj.bbox = obj.bbox.transformed(m)
            self._mark(obj)

    def delete(self, ids: Iterable[int]) -> None:
        for oid in ids:
            obj = self._obj(oid)
            if obj.kind == "clip":
                continue
            if isinstance(obj, TextRun):
                obj.deleted = True
            self._deleted.add(oid)
            self._mark(obj)

    def set_path_geometry(self, oid: int, subpaths: list[list[tuple]]) -> None:
        obj = self._obj(oid)
        if not isinstance(obj, PathObject):
            raise TypeError("not a path")
        obj.subpaths = [list(sp) for sp in subpaths]
        self._mark(obj)

    def set_style(
        self,
        oid: int,
        *,
        fill_color: Color | None = None,
        stroke_color: Color | None = None,
        fill: bool | None = None,
        stroke: bool | None = None,
        line_width: float | None = None,
        line_cap: int | None = None,
        line_join: int | None = None,
        dash: tuple[tuple[float, ...], float] | None = None,
    ) -> None:
        obj = self._obj(oid)
        st = obj.state
        if fill_color is not None:
            st.fill_color, st.fill_space = fill_color, fill_color.space
        if stroke_color is not None:
            st.stroke_color, st.stroke_space = stroke_color, stroke_color.space
        if line_width is not None:
            st.line_width = float(line_width)
        if line_cap is not None:
            st.line_cap = int(line_cap)
        if line_join is not None:
            st.line_join = int(line_join)
        if dash is not None:
            st.dash = dash
        if isinstance(obj, PathObject):
            if fill is not None:
                obj.fill = fill
            if stroke is not None:
                obj.stroke = stroke
        self._mark(obj)

    def set_text(self, oid: int, text: str, substitute: tuple[str, FontInfo] | None = None) -> bool:
        """Replace a run's text. Returns False if it could not be encoded.

        ``substitute`` is an optional ``(resource_name, FontInfo)`` used when the
        run's own font cannot encode the text.
        """
        run = self._obj(oid)
        if not isinstance(run, TextRun):
            raise TypeError("not a text run")
        font = run.font_info or FontInfo.fallback(run.font)
        encoded = font.encode(text)
        if encoded is None:
            if substitute is None:
                return False
            name, sub = substitute
            encoded = sub.encode(text)
            if encoded is None:
                return False
            run.font = name
            run.state.font = name
            run.font_info = sub
            font = sub
        run.items = [encoded]
        run.op = "Tj"
        run.text = text
        self._mark(run)
        return True

    def set_text_size(self, oid: int, size: float) -> None:
        run = self._obj(oid)
        if not isinstance(run, TextRun):
            raise TypeError("not a text run")
        run.state.font_size = float(size)
        run.font_size = float(size)
        self._mark(run)

    def set_text_render_mode(self, oid: int, mode: int) -> None:
        run = self._obj(oid)
        if isinstance(run, TextRun):
            run.state.render_mode = int(mode)
            self._mark(run)

    # -- creating new objects (appended at the end, i.e. on top) --------------
    def _append_base(self) -> tuple[GraphicsState, Matrix]:
        base = self.content.end_base_state
        try:
            inv = base.ctm.inverted()
        except ValueError:
            inv = Matrix()
        return base, inv

    def append_path(
        self,
        subpaths_device: list[list[tuple]],
        *,
        fill_color: Color | None = None,
        stroke_color: Color | None = None,
        line_width: float = 1.0,
        even_odd: bool = False,
        line_cap: int = 0,
        line_join: int = 0,
    ) -> None:
        """Append a new path given in device (PDF user) space."""
        base, inv = self._append_base()
        subpaths = [[_transform_segment(seg, inv) for seg in sp] for sp in subpaths_device]
        ops: list[bytes] = [b"q"]
        if fill_color is not None:
            ops += _color_ops(base.fill_color, base.fill_space, fill_color, fill_color.space, False) or []
            if not ops[1:]:
                ops += _color_ops(Color("X", ()), "X", fill_color, fill_color.space, False)
        if stroke_color is not None:
            ops += _color_ops(Color("X", ()), "X", stroke_color, stroke_color.space, True)
            ops.append(fmt(line_width / max(base.ctm.expansion(), 1e-9)) + b" w")
            if line_cap:
                ops.append(fmt(line_cap) + b" J")
            if line_join:
                ops.append(fmt(line_join) + b" j")
        ops.append(serialize_subpaths(subpaths))
        ops.append(paint_operator(fill_color is not None, stroke_color is not None, even_odd))
        ops.append(b"Q")
        self._appends.append(b"\n".join(ops))

    def append_text(
        self,
        x: float,
        y: float,
        text: str,
        font_name: str,
        font: FontInfo,
        size: float,
        color: Color | None = None,
        rotation: float = 0.0,
    ) -> bool:
        """Append a text object with its baseline origin at device point (x, y)."""
        encoded = font.encode(text)
        if encoded is None:
            return False
        base, inv = self._append_base()
        tm = Matrix.rotation(rotation) * Matrix.translation(x, y) * inv
        ops: list[bytes] = [b"q", b"BT"]
        if color is not None:
            ops += _color_ops(Color("X", ()), "X", color, color.space, False)
        ops.append(fmt_name(font_name) + b" " + fmt(size) + b" Tf")
        ops.append(fmt_matrix(tm) + b" Tm")
        ops.append(fmt_string(encoded, bool(font.code_ranges)) + b" Tj")
        ops += [b"ET", b"Q"]
        self._appends.append(b"\n".join(ops))
        return True

    # -- building --------------------------------------------------------
    def build(self) -> bytes:
        reps: list[_Replacement] = []
        for oid in self._dirty:
            obj = self._obj(oid)
            start, end = obj.wrapper_span or obj.span
            if oid in self._deleted:
                data = self._deletion_bytes(obj)
            else:
                data = self._serialize(obj)
            reps.append(_Replacement(start, end, data))
        for bid in self._dirty_blocks:
            blk = self._blocks_by_id[bid]
            reps.append(_Replacement(blk.span[0], blk.span[1], self._serialize_block(blk)))
        reps.sort(key=lambda r: r.start)
        out = bytearray()
        pos = 0
        for r in reps:
            if r.start < pos:
                raise ValueError("overlapping edits")
            out += self.stream[pos : r.start]
            out += r.data
            pos = r.end
        out += self.stream[pos:]
        if self._appends:
            if len(out) and out[-1:] not in (b"\n", b" ", b"\r"):
                out += b"\n"
            if self.content.end_in_text:
                out += b"ET\n"
            out += b"Q\n" * self.content.end_depth
            out += b"\n".join(self._appends) + b"\n"
        return bytes(out)

    def _deletion_bytes(self, obj: GObject) -> bytes:
        if isinstance(obj, PathObject) and obj.is_clip:
            # keep the clipping effect, drop the painting
            return serialize_subpaths(obj.subpaths) + (b" W* n" if obj.clip_even_odd else b" W n")
        return b""

    def _serialize(self, obj: GObject) -> bytes:
        base = obj.base_state
        st = obj.state
        if isinstance(obj, PathObject):
            body = serialize_subpaths(obj.subpaths)
            op = paint_operator(obj.fill, obj.stroke, obj.even_odd)
            if obj.is_clip:
                body += b" W* " if obj.clip_even_odd else b" W "
                return body + op
            diff = diff_ops(base, st, ctm=True)
            inner = body + b" " + op
        elif isinstance(obj, XObjectRef):
            diff = diff_ops(base, st, ctm=True)
            inner = fmt_name(obj.name) + b" Do"
        elif isinstance(obj, ShadingObject):
            diff = diff_ops(base, st, ctm=True)
            inner = fmt_name(obj.name) + b" sh"
        elif isinstance(obj, InlineImage):
            diff = diff_ops(base, st, ctm=True)
            inner = self.stream[obj.span[0] : obj.span[1]]
        else:
            raise TypeError(f"cannot serialize {obj.kind}")
        if not diff and obj.wrapper_span is None:
            return inner
        return b"q " + b" ".join(diff) + (b"\n" if diff else b"") + inner + b" Q"

    def _serialize_block(self, blk: TextBlock) -> bytes:
        start_state = blk.start_state or GraphicsState()
        cur = start_state.copy()
        out: list[bytes] = [b"BT"]
        for item in blk.items:
            if isinstance(item, OpaqueOp):
                out.append(self.stream[item.span[0] : item.span[1]])
                continue
            run = item
            if run.deleted:
                continue
            ops = diff_ops(cur, run.state, ctm=False, text=True, gs=False)
            _sync_state(cur, run.state, text=True)
            if cur.font is None and run.font:
                ops.append(fmt_name(run.font) + b" " + fmt(run.font_size) + b" Tf")
                cur.font, cur.font_size = run.font, run.font_size
            out.extend(ops)
            out.append(fmt_matrix(run.tm) + b" Tm")
            out.append(self._serialize_items(run))
        end_state = blk.end_state or start_state
        tail = diff_ops(cur, end_state, ctm=False, text=True, gs=False)
        out.extend(tail)
        out.append(b"ET")
        return b"\n".join(out)

    def _serialize_items(self, run: TextRun) -> bytes:
        font = run.font_info
        force_hex = bool(font and font.code_ranges)
        if run.op == "TJ" and (len(run.items) != 1 or not isinstance(run.items[0], bytes)):
            parts: list[bytes] = []
            for item in run.items:
                if isinstance(item, bytes):
                    parts.append(fmt_string(item, force_hex))
                else:
                    parts.append(fmt(float(item)))
            return b"[" + b" ".join(parts) + b"] TJ"
        data = run.items[0] if run.items and isinstance(run.items[0], bytes) else b""
        return fmt_string(data, force_hex) + b" Tj"


def _transform_segment(seg: tuple, m: Matrix) -> tuple:
    op = seg[0]
    if op == "h":
        return seg
    coords = list(seg[1:])
    out = [op]
    for i in range(0, len(coords), 2):
        x, y = m.apply(coords[i], coords[i + 1])
        out.extend((x, y))
    return tuple(out)
