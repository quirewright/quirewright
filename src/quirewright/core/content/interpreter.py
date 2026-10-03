"""Interpret a content stream into editable objects.

The interpreter walks the operator sequence, tracks the graphics state
(including the ``q``/``Q`` stack), and records every painted path, text run,
XObject invocation, inline image and shading as a :class:`GObject` with the
byte span that produced it. It also notes when a ``q ... Q`` pair contains
exactly one object and only state-setting operators, so that the writer can
later replace that whole wrapper atomically.
"""

from __future__ import annotations

from typing import Any, Protocol

from quirewright.core.content.lexer import Lexer, Name
from quirewright.core.content.model import (
    Color,
    Glyph,
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
from quirewright.core.fonts import FontInfo
from quirewright.core.geometry import Matrix, Rect, union_rects


class XObjectInfo(Protocol):  # pragma: no cover - structural type
    subtype: str
    bbox: Rect | None
    matrix: Matrix


class ResourceProvider(Protocol):  # pragma: no cover - structural type
    def font(self, name: str) -> FontInfo | None: ...

    def xobject(self, name: str) -> Any | None: ...


class NullResources:
    def font(self, name: str) -> FontInfo | None:
        return None

    def xobject(self, name: str) -> Any | None:
        return None


# Operators that only change modeled graphics state. A q..Q wrapper that
# contains only these (plus one object) can be regenerated from the model.
_STATE_OPS = frozenset(
    "cm w J j M d ri i gs g G rg RG k K cs CS sc SC scn SCN Tc Tw Tz TL Tf Tr Ts".split()
)
_TEXT_STATE_OPS = frozenset("Tc Tw Tz TL Tf Tr Ts".split())
_TEXT_POS_OPS = frozenset("Td TD Tm T*".split())
_TEXT_SHOW_OPS = frozenset(["Tj", "TJ", "'", '"'])
_COLOR_OPS = frozenset("g G rg RG k K cs CS sc SC scn SCN".split())
_LINE_OPS = frozenset("w J j M d".split())
_PATH_CONSTRUCT_OPS = frozenset("m l c v y h re".split())
_PATH_PAINT_OPS = frozenset("S s f F f* B B* b b* n".split())


class _Frame:
    __slots__ = ("q_start", "saved_state", "things", "pure")

    def __init__(self, q_start: int, saved_state: GraphicsState):
        self.q_start = q_start
        self.saved_state = saved_state
        self.things: list[Any] = []  # objects or text blocks directly/indirectly inside
        self.pure = True


class Interpreter:
    def __init__(self, stream: bytes, resources: ResourceProvider | None = None, page_box: Rect | None = None,
                 initial_state: GraphicsState | None = None):
        self.stream = stream
        self.res = resources or NullResources()
        self.page_box = page_box
        self.content = PageContent(stream=stream)
        self.state = initial_state.copy() if initial_state is not None else GraphicsState()
        self.stack: list[_Frame] = []
        self._fonts: dict[str, FontInfo | None] = {}
        self._seq = 0
        # path construction
        self._subpaths: list[list[tuple]] = []
        self._path_start: int | None = None
        self._current: tuple[float, float] | None = None
        self._subpath_start: tuple[float, float] | None = None
        self._pending_clip: str | None = None
        self._path_base_state: GraphicsState | None = None
        # text
        self._block: TextBlock | None = None
        self._tm = Matrix()
        self._tlm = Matrix()

    # ------------------------------------------------------------------
    def run(self) -> PageContent:
        lx = Lexer(self.stream)
        operands: list[Any] = []
        operand_start: int | None = None
        while True:
            tok = lx.next_token()
            if tok is None:
                break
            if tok.kind != "op":
                if operand_start is None:
                    operand_start = tok.start
                operands.append(tok.value)
                continue
            op = str(tok.value)
            start = operand_start if operand_start is not None else tok.start
            end = tok.end
            if op == "BI":
                end = self._inline_image(lx, tok.start)
                operands = []
                operand_start = None
                continue
            try:
                self._handle(op, operands, start, end)
            except Exception as exc:  # pragma: no cover - keep going on bad content
                self.content.warnings.append(f"{op} at {start}: {exc}")
            operands = []
            operand_start = None
        self.content.end_in_text = self._block is not None
        self.content.end_depth = len(self.stack)
        self.content.end_base_state = (self.stack[0].saved_state if self.stack else self.state).copy()
        if self._block is not None:  # unterminated BT
            self._end_text(len(self.stream), len(self.stream))
        self.content.objects.sort(key=lambda o: o.sequence)
        for i, o in enumerate(self.content.objects):
            o.id = i
        return self.content

    # ------------------------------------------------------------------
    def _font(self, name: str | None) -> FontInfo:
        if name is None:
            name = ""
        fi = self._fonts.get(name)
        if fi is None:
            fi = self.res.font(name) if name else None
            if fi is None:
                fi = FontInfo.fallback(name or "F?")
            self._fonts[name] = fi
            self.content.fonts[name] = fi
        return fi

    def _note_thing(self, thing: Any) -> None:
        for fr in self.stack:
            fr.things.append(thing)

    def _note_impure(self) -> None:
        if self.stack:
            self.stack[-1].pure = False

    def _add_object(self, obj: GObject) -> None:
        obj.sequence = self._seq
        self._seq += 1
        self.content.objects.append(obj)
        self._note_thing(obj)

    def _num(self, operands: list, i: int, default: float = 0.0) -> float:
        try:
            v = operands[i]
        except IndexError:
            return default
        return float(v) if isinstance(v, (int, float)) else default

    # ------------------------------------------------------------------
    def _handle(self, op: str, ops: list, start: int, end: int) -> None:
        st = self.state
        if op in _PATH_CONSTRUCT_OPS:
            self._construct(op, ops, start)
            return
        if op in _PATH_PAINT_OPS:
            self._paint(op, start, end)
            return
        if op == "W" or op == "W*":
            self._pending_clip = op
            return
        if op == "q":
            frame = _Frame(start, st.copy())
            self.stack.append(frame)
            if self._block is not None:
                self._block.items.append(OpaqueOp((start, end)))
            return
        if op == "Q":
            if self._block is not None:
                self._block.items.append(OpaqueOp((start, end)))
            if not self.stack:
                return
            frame = self.stack.pop()
            self.state = frame.saved_state.copy()
            if frame.pure and len(frame.things) == 1:
                thing = frame.things[0]
                if isinstance(thing, GObject) and thing.wrapper_span is None:
                    thing.wrapper_span = (frame.q_start, end)
                    thing.base_state = frame.saved_state
                elif isinstance(thing, TextBlock) and thing.inside_wrapper is None:
                    thing.inside_wrapper = (frame.q_start, end)
            # propagate things to the parent frame already done in _note_thing
            if not frame.pure:
                self._note_impure()
            return
        if op == "cm":
            if len(ops) >= 6:
                m = Matrix(*[self._num(ops, i) for i in range(6)])
                st.ctm = m * st.ctm
            if self._block is not None:
                self._block.items.append(OpaqueOp((start, end)))
            return
        if op == "w":
            st.line_width = self._num(ops, 0, 1.0)
            return
        if op == "J":
            st.line_cap = int(self._num(ops, 0))
            return
        if op == "j":
            st.line_join = int(self._num(ops, 0))
            return
        if op == "M":
            st.miter_limit = self._num(ops, 0, 10.0)
            return
        if op == "d":
            arr = ops[0] if ops and isinstance(ops[0], list) else []
            st.dash = (tuple(float(x) for x in arr if isinstance(x, (int, float))), self._num(ops, 1))
            return
        if op == "gs":
            st.ext_gstate = str(ops[0]) if ops and isinstance(ops[0], Name) else None
            if self._block is not None:
                self._block.items.append(OpaqueOp((start, end)))
            return
        if op in ("ri", "i"):
            return
        if op in _COLOR_OPS:
            self._color(op, ops)
            return
        # ---- text ----
        if op == "BT":
            self._begin_text(start, end)
            return
        if op == "ET":
            self._end_text(start, end)
            return
        if op in _TEXT_STATE_OPS:
            self._text_state(op, ops)
            return
        if op in _TEXT_POS_OPS:
            self._text_pos(op, ops)
            return
        if op in _TEXT_SHOW_OPS:
            self._show_text(op, ops, start, end)
            return
        if op == "Do":
            self._do(ops, start, end)
            return
        if op == "sh":
            name = str(ops[0]) if ops else ""
            obj = ShadingObject(
                id=0,
                kind="shading",
                span=(start, end),
                state=st.copy(),
                base_state=st.copy(),
                bbox=st.clip_bbox or self.page_box,
                name=name,
            )
            self._add_object(obj)
            return
        if op in ("BX", "EX"):
            return
        # Everything else (marked content, type3 glyph ops, compatibility) is opaque
        if self._block is not None:
            self._block.items.append(OpaqueOp((start, end)))
        self._note_impure()

    # ------------------------------------------------------------------
    def _color(self, op: str, ops: list) -> None:
        st = self.state
        nums = tuple(float(v) for v in ops if isinstance(v, (int, float)))
        if op == "g":
            st.fill_space = "DeviceGray"
            st.fill_color = Color("DeviceGray", nums[:1] or (0.0,))
        elif op == "G":
            st.stroke_space = "DeviceGray"
            st.stroke_color = Color("DeviceGray", nums[:1] or (0.0,))
        elif op == "rg":
            st.fill_space = "DeviceRGB"
            st.fill_color = Color("DeviceRGB", nums[:3])
        elif op == "RG":
            st.stroke_space = "DeviceRGB"
            st.stroke_color = Color("DeviceRGB", nums[:3])
        elif op == "k":
            st.fill_space = "DeviceCMYK"
            st.fill_color = Color("DeviceCMYK", nums[:4])
        elif op == "K":
            st.stroke_space = "DeviceCMYK"
            st.stroke_color = Color("DeviceCMYK", nums[:4])
        elif op == "cs":
            st.fill_space = str(ops[0]) if ops else "DeviceGray"
            st.fill_color = Color(st.fill_space, _initial_components(st.fill_space))
        elif op == "CS":
            st.stroke_space = str(ops[0]) if ops else "DeviceGray"
            st.stroke_color = Color(st.stroke_space, _initial_components(st.stroke_space))
        elif op in ("sc", "scn"):
            pattern = str(ops[-1]) if ops and isinstance(ops[-1], Name) else None
            st.fill_color = Color(st.fill_space, nums, pattern)
        elif op in ("SC", "SCN"):
            pattern = str(ops[-1]) if ops and isinstance(ops[-1], Name) else None
            st.stroke_color = Color(st.stroke_space, nums, pattern)

    # ------------------------------------------------------------------
    def _construct(self, op: str, ops: list, start: int) -> None:
        if self._path_start is None:
            self._path_start = start
            self._subpaths = []
            self._path_base_state = self.state.copy()
        n = lambda i: self._num(ops, i)  # noqa: E731
        if op == "m":
            pt = (n(0), n(1))
            self._subpaths.append([("m", pt[0], pt[1])])
            self._current = pt
            self._subpath_start = pt
        elif op == "l":
            pt = (n(0), n(1))
            self._ensure_subpath(pt)
            self._subpaths[-1].append(("l", pt[0], pt[1]))
            self._current = pt
        elif op == "c":
            pt = (n(4), n(5))
            self._ensure_subpath(pt)
            self._subpaths[-1].append(("c", n(0), n(1), n(2), n(3), pt[0], pt[1]))
            self._current = pt
        elif op == "v":
            pt = (n(2), n(3))
            self._ensure_subpath(pt)
            cx, cy = self._current or pt
            self._subpaths[-1].append(("c", cx, cy, n(0), n(1), pt[0], pt[1]))
            self._current = pt
        elif op == "y":
            pt = (n(2), n(3))
            self._ensure_subpath(pt)
            self._subpaths[-1].append(("c", n(0), n(1), pt[0], pt[1], pt[0], pt[1]))
            self._current = pt
        elif op == "h":
            if self._subpaths and self._subpaths[-1][-1][0] != "h":
                self._subpaths[-1].append(("h",))
                self._current = self._subpath_start
        elif op == "re":
            x, y, w, h = n(0), n(1), n(2), n(3)
            self._subpaths.append(
                [("m", x, y), ("l", x + w, y), ("l", x + w, y + h), ("l", x, y + h), ("h",)]
            )
            self._current = (x, y)
            self._subpath_start = (x, y)

    def _ensure_subpath(self, pt: tuple[float, float]) -> None:
        if not self._subpaths or self._subpaths[-1][-1][0] == "h":
            if self._current is None:
                self._current = pt
            self._subpaths.append([("m", self._current[0], self._current[1])])
            self._subpath_start = self._current

    def _paint(self, op: str, start: int, end: int) -> None:
        st = self.state
        path_start = self._path_start if self._path_start is not None else start
        subpaths = self._subpaths
        base_state = self._path_base_state or st.copy()
        self._path_start = None
        self._subpaths = []
        self._path_base_state = None
        clip = self._pending_clip
        self._pending_clip = None

        fill = op in ("f", "F", "f*", "B", "B*", "b", "b*")
        stroke = op in ("S", "s", "B", "B*", "b", "b*")
        even_odd = op.endswith("*")
        if op in ("s", "b", "b*") and subpaths and subpaths[-1][-1][0] != "h":
            subpaths[-1].append(("h",))

        pts = [st.ctm.apply(seg[i], seg[i + 1]) for sp in subpaths for seg in sp for i in range(1, len(seg), 2)]
        bbox = Rect.from_points(pts)
        if bbox is not None and stroke:
            bbox = bbox.expanded(max(st.line_width, 0.8) * st.ctm.expansion() / 2.0)

        if clip is not None and bbox is not None:
            st.clip_bbox = bbox if st.clip_bbox is None else st.clip_bbox.intersect(bbox)

        if not subpaths:
            return
        if not fill and not stroke:
            if clip is None:
                return  # "n" without clip: nothing painted
            obj = PathObject(
                id=0,
                kind="clip",
                span=(path_start, end),
                state=st.copy(),
                base_state=base_state,
                bbox=bbox,
                subpaths=subpaths,
                is_clip=True,
                clip_even_odd=clip == "W*",
                paint_op=op,
            )
            # Clips are not editable but count as a "thing" for wrapper purity
            self._add_object(obj)
            return
        obj = PathObject(
            id=0,
            kind="path",
            span=(path_start, end),
            state=st.copy(),
            base_state=base_state,
            bbox=bbox,
            subpaths=subpaths,
            fill=fill,
            stroke=stroke,
            even_odd=even_odd,
            is_clip=clip is not None,
            clip_even_odd=clip == "W*",
            paint_op=op,
        )
        # The object's own clip_bbox should not include the clip it establishes
        obj.state.clip_bbox = base_state.clip_bbox if clip is not None else st.clip_bbox
        self._add_object(obj)

    # ------------------------------------------------------------------
    def _begin_text(self, start: int, end: int) -> None:
        if self._block is not None:
            self._end_text(start, start)
        self._block = TextBlock(span=(start, end), start_state=self.state.copy())
        self._tm = Matrix()
        self._tlm = Matrix()
        self._note_thing(self._block)

    def _end_text(self, start: int, end: int) -> None:
        blk = self._block
        if blk is None:
            return
        blk.span = (blk.span[0], end)
        blk.end_state = self.state.copy()
        self.content.blocks.append(blk)
        self._block = None

    def _text_state(self, op: str, ops: list) -> None:
        st = self.state
        if op == "Tc":
            st.char_spacing = self._num(ops, 0)
        elif op == "Tw":
            st.word_spacing = self._num(ops, 0)
        elif op == "Tz":
            st.hscale = self._num(ops, 0, 100.0) / 100.0
        elif op == "TL":
            st.leading = self._num(ops, 0)
        elif op == "Tf":
            st.font = str(ops[0]) if ops and isinstance(ops[0], Name) else None
            st.font_size = self._num(ops, 1)
        elif op == "Tr":
            st.render_mode = int(self._num(ops, 0))
        elif op == "Ts":
            st.rise = self._num(ops, 0)

    def _text_pos(self, op: str, ops: list) -> None:
        st = self.state
        if op == "Td":
            self._tlm = Matrix.translation(self._num(ops, 0), self._num(ops, 1)) * self._tlm
            self._tm = self._tlm
        elif op == "TD":
            st.leading = -self._num(ops, 1)
            self._tlm = Matrix.translation(self._num(ops, 0), self._num(ops, 1)) * self._tlm
            self._tm = self._tlm
        elif op == "Tm":
            if len(ops) >= 6:
                self._tlm = Matrix(*[self._num(ops, i) for i in range(6)])
                self._tm = self._tlm
        elif op == "T*":
            self._tlm = Matrix.translation(0, -st.leading) * self._tlm
            self._tm = self._tlm

    def _show_text(self, op: str, ops: list, start: int, end: int) -> None:
        st = self.state
        if self._block is None:
            # Text outside BT/ET: tolerate by opening an implicit block
            self._begin_text(start, start)
        if op == "'":
            self._text_pos("T*", [])
            items: list = [ops[0] if ops and isinstance(ops[0], bytes) else b""]
        elif op == '"':
            st.word_spacing = self._num(ops, 0)
            st.char_spacing = self._num(ops, 1)
            self._text_pos("T*", [])
            items = [ops[2] if len(ops) > 2 and isinstance(ops[2], bytes) else b""]
        elif op == "TJ":
            arr = ops[0] if ops and isinstance(ops[0], list) else []
            items = [x for x in arr if isinstance(x, (bytes, int, float))]
        else:
            items = [ops[0] if ops and isinstance(ops[0], bytes) else b""]

        font = self._font(st.font)
        tm_start = self._tm
        glyphs: list[Glyph] = []
        text_parts: list[str] = []
        fs = st.font_size
        th = st.hscale
        for item in items:
            if isinstance(item, (int, float)):
                tx = -float(item) / 1000.0 * fs * th
                self._tm = Matrix.translation(tx, 0) * self._tm
                continue
            for code, nbytes in font.decode(item):
                w0 = font.width(code)
                trm = Matrix(fs * th, 0, 0, fs, 0, st.rise) * self._tm * st.ctm
                origin = trm.apply(0, 0)
                gb = Rect(0, font.descent, max(w0, 0.0), font.ascent).transformed(trm)
                uni = font.unicode(code)
                tx = (w0 * fs + st.char_spacing + (st.word_spacing if font.is_word_space(code, nbytes) else 0.0)) * th
                glyphs.append(Glyph(code=code, text=uni, width=w0, advance=tx, origin=origin, bbox=gb))
                text_parts.append(uni)
                self._tm = Matrix.translation(tx, 0) * self._tm
        bbox = union_rects(g.bbox for g in glyphs)
        run = TextRun(
            id=0,
            kind="text",
            span=(start, end),
            state=st.copy(),
            base_state=st.copy(),
            bbox=bbox,
            font=st.font or "",
            font_size=fs,
            tm=tm_start,
            items=items,
            op="TJ" if op == "TJ" else "Tj",
            glyphs=glyphs,
            text="".join(text_parts),
            block=self._block,
            font_info=font,
            end_tm=self._tm,
        )
        self._block.items.append(run)
        self._add_object(run)

    # ------------------------------------------------------------------
    def _do(self, ops: list, start: int, end: int) -> None:
        st = self.state
        name = str(ops[0]) if ops and isinstance(ops[0], Name) else ""
        info = self.res.xobject(name)
        subtype = getattr(info, "subtype", "Image") if info is not None else "Image"
        if subtype == "Form":
            fb: Rect | None = getattr(info, "bbox", None)
            fm: Matrix = getattr(info, "matrix", Matrix())
            bbox = fb.transformed(fm * st.ctm) if fb is not None else None
            obj = XObjectRef(
                id=0, kind="form", span=(start, end), state=st.copy(), base_state=st.copy(),
                bbox=bbox, name=name, subtype="Form", form_bbox=fb, form_matrix=fm, xref=int(getattr(info, "xref", 0) or 0),
            )
        else:
            bbox = Rect(0, 0, 1, 1).transformed(st.ctm)
            obj = XObjectRef(
                id=0, kind="image", span=(start, end), state=st.copy(), base_state=st.copy(),
                bbox=bbox, name=name, subtype="Image",
            )
        self._add_object(obj)

    def _inline_image(self, lx: Lexer, start: int) -> int:
        params: dict[str, Any] = {}
        key: str | None = None
        while True:
            tok = lx.next_token()
            if tok is None:
                return lx.pos
            if tok.kind == "op" and tok.value == "ID":
                break
            if tok.kind == "name" and key is None:
                key = str(tok.value)
            elif key is not None:
                params[key] = tok.value
                key = None
        lx.read_inline_image_data(params)
        end = lx.pos
        st = self.state
        obj = InlineImage(
            id=0, kind="inline_image", span=(start, end), state=st.copy(), base_state=st.copy(),
            bbox=Rect(0, 0, 1, 1).transformed(st.ctm), params=params,
        )
        self._add_object(obj)
        return end


def _initial_components(space: str) -> tuple[float, ...]:
    if space in ("DeviceRGB", "CalRGB"):
        return (0.0, 0.0, 0.0)
    if space in ("DeviceCMYK",):
        return (0.0, 0.0, 0.0, 1.0)
    return (0.0,)


def interpret(stream: bytes, resources: ResourceProvider | None = None, page_box: Rect | None = None,
              initial_state: GraphicsState | None = None) -> PageContent:
    return Interpreter(stream, resources, page_box, initial_state).run()
