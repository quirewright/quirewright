"""Document model wrapping a PyMuPDF document.

Responsibilities:

* open/save, password handling,
* parse page content streams into editable objects (with resource lookup),
* write modified content streams back,
* page structure operations (rotate, reorder, delete, insert, extract, crop),
* undo/redo via :mod:`pdfeditor.core.commands`,
* change notification for the UI.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

import pymupdf

from pdfeditor.core.annotations import AnnotationMixin
from pdfeditor.core.commands import ContentEditCommand, SnapshotCommand, UndoStack
from pdfeditor.core.docinfo import DocInfoMixin, SecuritySettings
from pdfeditor.core.content.interpreter import interpret
from pdfeditor.core.content.model import PageContent
from pdfeditor.core.fonts import FontInfo
from pdfeditor.core.geometry import Matrix, Rect
from pdfeditor.core.pdfobj import Ref, Resolver, as_float

log = logging.getLogger(__name__)

Listener = Callable[[str, Any], None]
EditPath = tuple  # tuple[tuple[int, Matrix], ...]


@dataclass
class XObjectInfo:
    name: str
    subtype: str
    bbox: Rect | None = None
    matrix: Matrix = Matrix()
    xref: int = 0


class PageResources:
    """Resolves font and XObject resources for one page (with inheritance),
    or for a form XObject (falling back to the page's resources)."""

    def __init__(self, doc: "Document", page_index: int, form_xref: int = 0, parent: "PageResources | None" = None):
        self.doc = doc
        self.page_index = page_index
        self.form_xref = form_xref
        self.parent = parent
        self.resolver = Resolver(doc.pdf)
        self._fonts: dict[str, FontInfo | None] = {}
        self._xobjects: dict[str, XObjectInfo | None] = {}
        self._resources: dict | None = None

    def _page_dict(self) -> dict | None:
        page = self.doc.pdf[self.page_index]
        d = self.resolver.get(page.xref)
        return d if isinstance(d, dict) else None

    def resources(self) -> dict:
        if self._resources is None:
            res: dict = {}
            if self.form_xref:
                d = self.resolver.get(self.form_xref)
                r = self.resolver.resolve(d.get("Resources")) if isinstance(d, dict) else None
                res = r if isinstance(r, dict) else {}
            else:
                d = self._page_dict()
                depth = 0
                while isinstance(d, dict) and depth < 64:
                    r = self.resolver.resolve(d.get("Resources"))
                    if isinstance(r, dict):
                        res = r
                        break
                    d = self.resolver.resolve(d.get("Parent"))
                    depth += 1
            self._resources = res
        return self._resources

    def _category(self, key: str) -> dict:
        cat = self.resolver.resolve(self.resources().get(key))
        out = dict(cat) if isinstance(cat, dict) else {}
        if self.parent is not None:
            base = self.parent._category(key)
            for k, v in base.items():
                out.setdefault(k, v)
        return out

    def font(self, name: str) -> FontInfo | None:
        if name in self._fonts:
            return self._fonts[name]
        fonts = self._category("Font")
        obj = fonts.get(name)
        fi: FontInfo | None = None
        if obj is not None:
            xref = obj.num if isinstance(obj, Ref) else 0
            fi = FontInfo.load(self.doc.pdf, self.resolver, obj, name, xref)
        self._fonts[name] = fi
        return fi

    def font_names(self) -> list[str]:
        return list(self._category("Font").keys())

    def xobject(self, name: str) -> XObjectInfo | None:
        if name in self._xobjects:
            return self._xobjects[name]
        xobjs = self._category("XObject")
        obj = xobjs.get(name)
        info: XObjectInfo | None = None
        if obj is not None:
            d = self.resolver.resolve(obj)
            xref = obj.num if isinstance(obj, Ref) else 0
            if isinstance(d, dict):
                subtype = str(self.resolver.dict_get(d, "Subtype", "Image"))
                info = XObjectInfo(name=name, subtype=subtype, xref=xref)
                if subtype == "Form":
                    bbox = self.resolver.dict_get(d, "BBox")
                    if isinstance(bbox, list) and len(bbox) == 4:
                        vals = [as_float(self.resolver.resolve(v)) for v in bbox]
                        info.bbox = Rect.normalized(*vals)
                    mtx = self.resolver.dict_get(d, "Matrix")
                    if isinstance(mtx, list) and len(mtx) == 6:
                        info.matrix = Matrix(*[as_float(self.resolver.resolve(v)) for v in mtx])
        self._xobjects[name] = info
        return info



# ---------------------------------------------------------------------------
# Images and form fields
# ---------------------------------------------------------------------------

from dataclasses import field as _field

WIDGET_TYPES = {
    1: "Button", 2: "Checkbox", 3: "Combo box", 4: "List box", 5: "Radio button", 6: "Signature", 7: "Text field",
}
WIDGET_TYPE_BY_NAME = {v: k for k, v in WIDGET_TYPES.items()}


@dataclass
class WidgetInfo:
    xref: int
    field_type: int
    field_name: str
    rect: Rect  # scene space (rotated page space, y down)
    value: Any = None
    flags: int = 0
    choices: list[str] = _field(default_factory=list)
    font_size: float = 0.0
    text_color: tuple | None = None
    fill_color: tuple | None = None
    border_color: tuple | None = None
    border_width: float = 1.0
    label: str = ""
    on_state: str | None = None
    script_calc: str = ""
    script_format: str = ""
    script_validate: str = ""  # "change" action in PyMuPDF terms (field value validation)
    script_keystroke: str = ""
    script_action: str = ""  # mouse-up action (buttons)

    @property
    def type_name(self) -> str:
        return WIDGET_TYPES.get(self.field_type, "Unknown")


def _to_rgb_tuple(v: Any) -> tuple | None:
    if v is None:
        return None
    try:
        vals = [float(x) for x in v]
    except TypeError:
        return None
    if len(vals) == 1:
        return (vals[0], vals[0], vals[0])
    if len(vals) == 3:
        return tuple(vals)
    if len(vals) == 4:
        c, m, y, k = vals
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _scene_rect(page, r) -> Rect:
    rr = pymupdf.Rect(r) * page.rotation_matrix
    return Rect.normalized(rr.x0, rr.y0, rr.x1, rr.y1)


def _unrotated_rect(page, r: Rect) -> pymupdf.Rect:
    rr = pymupdf.Rect(r.x0, r.y0, r.x1, r.y1) * page.derotation_matrix
    rr.normalize()
    return rr


def format_number(value: float, format_script: str = "") -> str:
    """Render a number the way an AFNumber_Format / AFPercent_Format script would (approximately)."""
    import re

    m = re.search(r"AF(Number|Percent)_Format\(\s*(\d+)", format_script or "")
    if m:
        decimals = int(m.group(2))
        if m.group(1) == "Percent":
            return f"{value * 100:.{decimals}f}%"
        return f"{value:,.{decimals}f}" if "1," not in format_script else f"{value:.{decimals}f}"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


CALC_OPS = {"sum": "SUM", "product": "PRD", "average": "AVG", "minimum": "MIN", "maximum": "MAX"}


def calc_script(op: str, fields: Sequence[str]) -> str:
    names = ", ".join(f'"{f}"' for f in fields)
    return f'AFSimple_Calculate("{CALC_OPS.get(op, op)}", new Array({names}));'


def number_format_script(decimals: int = 2, separator: int = 0, negative: int = 0, currency: str = "", prepend: bool = True) -> str:
    return f'AFNumber_Format({decimals}, {separator}, {negative}, 0, "{currency}", {"true" if prepend else "false"});'


def percent_format_script(decimals: int = 2) -> str:
    return f"AFPercent_Format({decimals}, 0);"


def date_format_script(fmt: str = "yyyy-mm-dd") -> str:
    return f'AFDate_FormatEx("{fmt}");'


def range_validate_script(low: float | None, high: float | None) -> str:
    return f'AFRange_Validate({"true" if low is not None else "false"}, {low if low is not None else 0}, {"true" if high is not None else "false"}, {high if high is not None else 0});'


def number_keystroke_script(decimals: int = 2, separator: int = 0, negative: int = 0, currency: str = "", prepend: bool = True) -> str:
    return f'AFNumber_Keystroke({decimals}, {separator}, {negative}, 0, "{currency}", {"true" if prepend else "false"});'


class _DocumentExtras:
    """Image and form-field operations (mixed into Document)."""

    def substitute_font_name(self, font_info: FontInfo | None) -> str:
        """Pick the built-in font (helv/hebo/tiro/...) that best matches a run's font."""
        from pdfeditor.core.fonts import builtin_font_name

        if font_info is None:
            return "helv"
        name = builtin_font_name(font_info.base_font)
        return "helv" if name in ("symb", "zadb") else name

    # -- images ----------------------------------------------------------------
    def add_image(self, index: int, rect_scene: Rect, path: str) -> None:
        def action(doc: "Document") -> None:
            page = doc.pdf[index]
            r = _unrotated_rect(page, rect_scene)
            page.insert_image(r, filename=path, keep_proportion=True, rotate=page.rotation)

        self._structure_op("Insert image", action)

    def image_size(self, path: str) -> tuple[int, int]:
        pix = pymupdf.Pixmap(path)
        w, h = pix.width, pix.height
        pix = None
        return w, h

    # -- form fields ------------------------------------------------------------
    def widgets(self, index: int) -> list[WidgetInfo]:
        page = self.pdf[index]
        out: list[WidgetInfo] = []
        try:
            iterator = page.widgets()
        except Exception:
            return out
        for w in iterator:
            try:
                info = WidgetInfo(
                    xref=w.xref,
                    field_type=int(w.field_type),
                    field_name=w.field_name or "",
                    rect=_scene_rect(page, w.rect),
                    value=w.field_value,
                    flags=int(w.field_flags or 0),
                    choices=list(w.choice_values or []),
                    font_size=float(w.text_fontsize or 0),
                    text_color=_to_rgb_tuple(w.text_color),
                    fill_color=_to_rgb_tuple(w.fill_color),
                    border_color=_to_rgb_tuple(w.border_color),
                    border_width=float(w.border_width or 0),
                    label=w.field_label or "",
                    on_state=w.on_state() if w.field_type in (2, 5) else None,
                    script_calc=w.script_calc or "",
                    script_format=w.script_format or "",
                    script_validate=w.script_change or "",
                    script_keystroke=w.script_stroke or "",
                    script_action=w.script or "",
                )
            except Exception as exc:  # pragma: no cover
                log.warning("widget %s: %s", getattr(w, "xref", "?"), exc)
                continue
            out.append(info)
        return out

    def has_widgets(self, index: int) -> bool:
        return bool(self.widgets(index))

    def _unique_field_name(self, base: str) -> str:
        existing: set[str] = set()
        for i in range(self.pdf.page_count):
            for w in self.widgets(i):
                existing.add(w.field_name)
        n = 1
        while f"{base}{n}" in existing:
            n += 1
        return f"{base}{n}"

    def add_widget(self, index: int, field_type: int, rect_scene: Rect, name: str | None = None, **props) -> None:
        base = {1: "Button", 2: "Check", 3: "Combo", 4: "List", 5: "Radio", 6: "Signature", 7: "Text"}.get(field_type, "Field")
        name = name or self._unique_field_name(base)

        def action(doc: "Document") -> None:
            page = doc.pdf[index]
            if field_type == 5:
                doc._add_radio(page, name, rect_scene, props)
                return
            w = pymupdf.Widget()
            w.field_type = field_type
            w.field_name = name
            w.rect = _unrotated_rect(page, rect_scene)
            w.text_fontsize = props.get("font_size", 0 if field_type in (2, 5) else 11)
            w.border_color = props.get("border_color", (0.45, 0.45, 0.45))
            w.border_width = props.get("border_width", 1)
            if field_type in (3, 4):
                w.choice_values = props.get("choices", ["Option 1", "Option 2", "Option 3"])
                w.field_value = props.get("value", w.choice_values[0] if w.choice_values else "")
            elif field_type == 7:
                w.field_value = props.get("value", "")
                w.fill_color = props.get("fill_color", (1, 1, 1))
            elif field_type == 1:
                w.button_caption = props.get("label", "Button")
                w.fill_color = props.get("fill_color", (0.9, 0.9, 0.9))
            elif field_type == 2:
                w.field_value = props.get("value", False)
            elif field_type == 5:
                w.field_value = props.get("value", False)
            if "fill_color" in props:
                w.fill_color = props["fill_color"]
            if "flags" in props:
                w.field_flags = props["flags"]
            page.add_widget(w)

        self._structure_op(f"Add {WIDGET_TYPES.get(field_type, 'field').lower()}", action)

    def _add_radio(self, page, name: str, rect_scene: Rect, props: dict) -> None:
        """Create a radio button.

        PyMuPDF cannot create radio widgets directly, so this adds a checkbox,
        flips the radio flag and gives the button its own on-state name so
        buttons sharing a field name form a group with distinct choices.
        """
        w = pymupdf.Widget()
        w.field_type = 2
        w.field_name = name
        w.rect = _unrotated_rect(page, rect_scene)
        w.border_color = props.get("border_color", (0.45, 0.45, 0.45))
        w.border_width = props.get("border_width", 1)
        w.field_value = bool(props.get("value", False))
        if "fill_color" in props:
            w.fill_color = props["fill_color"]
        annot = page.add_widget(w)
        xref = annot.xref
        doc = self.pdf
        # unique on-state name within the group
        existing = sum(1 for x in page.widgets() if x.field_name == name)
        state = props.get("on_state") or f"Choice{existing}"
        try:
            kind, ap = doc.xref_get_key(xref, "AP/N")
            if kind == "dict" and "/Yes" in ap:
                doc.xref_set_key(xref, "AP/N", ap.replace("/Yes", "/" + state, 1))
            kind, ap = doc.xref_get_key(xref, "AP/D")
            if kind == "dict" and "/Yes" in ap:
                doc.xref_set_key(xref, "AP/D", ap.replace("/Yes", "/" + state, 1))
            flags = int(doc.xref_get_key(xref, "Ff")[1] or 0) if doc.xref_get_key(xref, "Ff")[0] == "int" else 0
            doc.xref_set_key(xref, "Ff", str(flags | pymupdf.PDF_BTN_FIELD_IS_RADIO | pymupdf.PDF_BTN_FIELD_IS_NO_TOGGLE_TO_OFF))
            doc.xref_set_key(xref, "AS", "/" + (state if w.field_value else "Off"))
            doc.xref_set_key(xref, "V", "/" + (state if w.field_value else "Off"))
            doc.xref_set_key(xref, "MK", "<< /CA (l) >>")  # ZapfDingbats 'l' = filled circle
        except Exception as exc:  # pragma: no cover
            log.warning("radio setup: %s", exc)

    def _find_widget(self, page, xref: int):
        for w in page.widgets():
            if w.xref == xref:
                return w
        return None

    def update_widget(self, index: int, xref: int, label: str = "Edit field", **props) -> None:
        def action(doc: "Document") -> None:
            page = doc.pdf[index]
            w = doc._find_widget(page, xref)
            if w is None:
                return
            if "rect" in props:
                w.rect = _unrotated_rect(page, props["rect"])
            if "field_name" in props and props["field_name"]:
                w.field_name = props["field_name"]
            if "value" in props:
                w.field_value = props["value"]
            if "flags" in props:
                w.field_flags = int(props["flags"])
            if "choices" in props:
                w.choice_values = list(props["choices"])
            if "font_size" in props:
                w.text_fontsize = float(props["font_size"])
            if "text_color" in props:
                w.text_color = props["text_color"]
            if "fill_color" in props:
                w.fill_color = props["fill_color"]
            if "border_color" in props:
                w.border_color = props["border_color"]
            if "border_width" in props:
                w.border_width = float(props["border_width"])
            if "label" in props:
                w.button_caption = props["label"]
            for key, attr in (("script_calc", "script_calc"), ("script_format", "script_format"), ("script_validate", "script_change"),
                              ("script_keystroke", "script_stroke"), ("script_action", "script")):
                if key in props:
                    setattr(w, attr, props[key] or None)
            w.update()

        self._structure_op(label, action)

    # -- calculations (evaluated locally so the preview updates; viewers run the JS) ----
    def recalculate(self, index: int) -> int:
        """Evaluate AFSimple_Calculate scripts of fields on the page; returns the number updated."""
        import re

        page = self.pdf[index]
        widgets = list(page.widgets())
        values: dict[str, float] = {}
        for w in widgets:
            try:
                values[w.field_name] = float(str(w.field_value or "").replace(",", ".") or 0)
            except ValueError:
                values[w.field_name] = 0.0
        pat = re.compile(r'AFSimple_Calculate\(\s*"(SUM|PRD|AVG|MIN|MAX)"\s*,\s*(?:new\s+Array\s*\(|\[)\s*([^\])]*)[\)\]]')
        updated = 0
        for w in widgets:
            script = w.script_calc or ""
            m = pat.search(script)
            if not m:
                continue
            op = m.group(1)
            names = [n.strip().strip('"\'') for n in m.group(2).split(",") if n.strip()]
            nums = [values.get(n, 0.0) for n in names]
            if not nums:
                continue
            if op == "SUM":
                res = sum(nums)
            elif op == "PRD":
                res = 1.0
                for v in nums:
                    res *= v
            elif op == "AVG":
                res = sum(nums) / len(nums)
            elif op == "MIN":
                res = min(nums)
            else:
                res = max(nums)
            text = format_number(res, w.script_format or "")
            if str(w.field_value or "") != text:
                w.field_value = text
                w.update()
                updated += 1
        if updated:
            self._content_cache.clear()
        return updated

    def delete_widgets(self, index: int, xrefs: Iterable[int]) -> None:
        xs = set(xrefs)

        def action(doc: "Document") -> None:
            page = doc.pdf[index]
            for w in list(page.widgets()):
                if w.xref in xs:
                    page.delete_widget(w)

        self._structure_op("Delete field(s)", action)

    # -- grouping (form XObjects) ---------------------------------------------------
    def _resources_owner(self, index: int, path: EditPath) -> tuple[int, str]:
        """(xref, key prefix) of the dictionary holding the resources for a context."""
        if path:
            form_xref = path[-1][0]
            kind, val = self.pdf.xref_get_key(form_xref, "Resources")
            if kind == "xref":
                return int(val.split()[0]), ""
            if kind == "dict":
                return form_xref, "Resources/"
            # no resources on the form: point it at the page's resources
            pkind, pval = self.pdf.xref_get_key(self.pdf[index].xref, "Resources")
            if pkind == "xref":
                self.pdf.xref_set_key(form_xref, "Resources", pval)
                return int(pval.split()[0]), ""
            self.pdf.xref_set_key(form_xref, "Resources", "<< >>")
            return form_xref, "Resources/"
        page_xref = self.pdf[index].xref
        kind, val = self.pdf.xref_get_key(page_xref, "Resources")
        if kind == "xref":
            return int(val.split()[0]), ""
        if kind != "dict":
            self.pdf.xref_set_key(page_xref, "Resources", "<< >>")
        return page_xref, "Resources/"

    def _register_resource(self, owner: int, prefix: str, category: str, base_name: str, value: str) -> str:
        """Add ``value`` under Resources/<category>/<unique name>; returns the name."""
        kind, cat = self.pdf.xref_get_key(owner, prefix + category)
        existing = ""
        if kind == "xref":
            owner, prefix, cat_kind, existing = int(cat.split()[0]), "", "dict", self.pdf.xref_object(int(cat.split()[0]))
            cat_path = ""
        elif kind == "dict":
            existing = cat
            cat_path = prefix + category + "/"
        else:
            self.pdf.xref_set_key(owner, prefix + category, "<< >>")
            cat_path = prefix + category + "/"
        name = base_name
        n = 1
        while f"/{name} " in existing or f"/{name}\n" in existing:
            n += 1
            name = f"{base_name}{n}"
        if cat_path:
            self.pdf.xref_set_key(owner, cat_path + name, value)
        else:
            self.pdf.xref_set_key(owner, name, value)
        return name

    def group_objects(self, index: int, path: EditPath, ids: Sequence[int]) -> None:
        """Move the given objects of a context into a new form XObject placed on top."""
        from pdfeditor.core.content.writer import ContentEditor

        ids = [i for i in ids]
        if not ids:
            return

        def action(doc: "Document") -> None:
            pc = doc.content(index, path)
            ed = ContentEditor(pc)
            base = pc.end_base_state
            parts: list[bytes] = []
            boxes = []
            for oid in sorted(ids):
                obj = pc.objects[oid]
                data = ed._standalone_bytes(obj)
                if data is None:
                    continue
                parts.append(data)
                if obj.bbox is not None:
                    boxes.append(obj.bbox.transformed(base.ctm.inverted()))
            if not parts:
                return
            bbox = boxes[0]
            for b in boxes[1:]:
                bbox = bbox.union(b)
            bbox = bbox.expanded(1.0)
            owner, prefix = doc._resources_owner(index, path)
            res_ref = f"{owner} 0 R" if prefix == "" else None
            xref = doc.pdf.get_new_xref()
            res_entry = f" /Resources {res_ref}" if res_ref else ""
            doc.pdf.update_object(xref, f"<< /Type /XObject /Subtype /Form /BBox [{bbox.x0:.4f} {bbox.y0:.4f} {bbox.x1:.4f} {bbox.y1:.4f}]{res_entry} >>")
            doc.pdf.update_stream(xref, b"\n".join(parts))
            if not res_ref:
                # resources are a direct dict on the owner: copy it by value
                kind, val = doc.pdf.xref_get_key(owner, prefix.rstrip("/"))
                if kind == "dict":
                    doc.pdf.xref_set_key(xref, "Resources", val)
            name = doc._register_resource(owner, prefix, "XObject", "Group", f"{xref} 0 R")
            ed.delete(ids)
            ed._appends.append(b"q /" + name.encode() + b" Do Q")
            doc._write_stream(index, ed.build(), path[-1][0] if path else 0)

        self._structure_op("Group", action)

    def ungroup_object(self, index: int, path: EditPath, oid: int) -> None:
        """Inline a form XObject's content into its parent stream."""
        from pdfeditor.core.content.model import XObjectRef
        from pdfeditor.core.content.writer import fmt, fmt_matrix

        def action(doc: "Document") -> None:
            pc = doc.content(index, path)
            obj = pc.objects[oid]
            if not isinstance(obj, XObjectRef) or obj.subtype != "Form" or not obj.xref:
                return
            inner = doc.pdf.xref_stream(obj.xref) or b""
            inner = doc._merge_form_resources(index, path, obj.xref, inner)
            ops: list[bytes] = [b"q"]
            if not obj.form_matrix.is_identity():
                ops.append(fmt_matrix(obj.form_matrix) + b" cm")
            if obj.form_bbox is not None:
                b = obj.form_bbox
                ops.append(b" ".join(fmt(v) for v in (b.x0, b.y0, b.width, b.height)) + b" re W n")
            body = b"\n".join(ops) + b"\n" + inner + b"\nQ"
            start, end = obj.span  # keep any wrapper's state ops, replace only the Do
            stream = pc.stream[:start] + body + pc.stream[end:]
            doc._write_stream(index, stream, path[-1][0] if path else 0)

        self._structure_op("Ungroup", action)

    def _merge_form_resources(self, index: int, path: EditPath, form_xref: int, stream: bytes) -> bytes:
        """Copy a form's resources into the parent's, renaming on conflicts; returns the adjusted stream."""
        from pdfeditor.core.content.lexer import Lexer, Name

        owner, prefix = self._resources_owner(index, path)
        kind, val = self.pdf.xref_get_key(form_xref, "Resources")
        if kind == "null":
            return stream
        if kind == "xref" and prefix == "" and int(val.split()[0]) == owner:
            return stream  # same dictionary: nothing to merge
        resolver = Resolver(self.pdf)
        fres = resolver.resolve(resolver.get(form_xref).get("Resources")) if isinstance(resolver.get(form_xref), dict) else None
        if not isinstance(fres, dict):
            return stream
        rename: dict[tuple[str, str], str] = {}
        categories = {"Font": ("Tf",), "XObject": ("Do",), "ExtGState": ("gs",), "ColorSpace": ("cs", "CS"), "Pattern": ("scn", "SCN"), "Shading": ("sh",), "Properties": ("BDC", "DP")}
        for cat in categories:
            entries = resolver.resolve(fres.get(cat))
            if not isinstance(entries, dict):
                continue
            for name, value in entries.items():
                if isinstance(value, Ref):
                    text = f"{value.num} {value.gen} R"
                else:
                    text = self.pdf.xref_get_key(form_xref, f"Resources/{cat}/{name}")[1] if kind == "dict" else None
                    if text is None:
                        rkind, rval = self.pdf.xref_get_key(int(val.split()[0]), f"{cat}/{name}")
                        text = rval
                new = self._register_resource(owner, prefix, cat, name, text)
                if new != name:
                    rename[(cat, name)] = new
        if not rename:
            return stream
        # rewrite operand names in the stream
        ops_to_cat = {op: cat for cat, ops in categories.items() for op in ops}
        lx = Lexer(stream)
        out = bytearray()
        pos = 0
        pending: list = []
        while True:
            tok = lx.next_token()
            if tok is None:
                break
            if tok.kind != "op":
                pending.append(tok)
                continue
            cat = ops_to_cat.get(str(tok.value))
            if cat and pending:
                target = pending[0] if cat != "Pattern" else pending[-1]
                if target.kind == "name" and (cat, str(target.value)) in rename:
                    out += stream[pos:target.start]
                    out += b"/" + rename[(cat, str(target.value))].encode()
                    pos = target.end
            pending = []
        out += stream[pos:]
        return bytes(out)

    def transform_widgets(self, index: int, xrefs: Iterable[int], m_scene: Matrix) -> None:
        """Apply a scene-space transform to widget rectangles (move/scale)."""
        xs = list(xrefs)

        def action(doc: "Document") -> None:
            page = doc.pdf[index]
            for w in list(page.widgets()):
                if w.xref not in xs:
                    continue
                r = _scene_rect(page, w.rect).transformed(m_scene)
                w.rect = _unrotated_rect(page, r)
                w.update()

        self._structure_op("Move field(s)", action)


class Document(_DocumentExtras, DocInfoMixin, AnnotationMixin):
    def __init__(self, path: str | None = None, pdf: pymupdf.Document | None = None):
        self.path: str | None = path
        if pdf is not None:
            self.pdf = pdf
        elif path:
            self.pdf = pymupdf.open(path)
        else:
            self.pdf = pymupdf.open()
            self.pdf.new_page()
        self.undo_stack = UndoStack(self)
        self.security = SecuritySettings()
        self.listeners: list[Listener] = []
        self._content_cache: dict[int, PageContent] = {}
        self._resources_cache: dict[int, PageResources] = {}

    # -- lifecycle -------------------------------------------------------
    @property
    def needs_password(self) -> bool:
        return bool(self.pdf.needs_pass)

    def authenticate(self, password: str) -> bool:
        return bool(self.pdf.authenticate(password))

    @property
    def page_count(self) -> int:
        return self.pdf.page_count

    @property
    def is_modified(self) -> bool:
        return not self.undo_stack.is_clean

    @property
    def title(self) -> str:
        if self.path:
            return os.path.basename(self.path)
        return "Untitled.pdf"

    def close(self) -> None:
        try:
            self.pdf.close()
        except Exception:
            pass

    def add_listener(self, cb: Listener) -> None:
        self.listeners.append(cb)

    def remove_listener(self, cb: Listener) -> None:
        if cb in self.listeners:
            self.listeners.remove(cb)

    def _emit(self, event: str, payload: Any = None) -> None:
        for cb in list(self.listeners):
            try:
                cb(event, payload)
            except Exception:  # pragma: no cover
                log.exception("listener failed")

    # -- pages -----------------------------------------------------------
    def page(self, index: int) -> pymupdf.Page:
        return self.pdf[index]

    def page_rect(self, index: int) -> Rect:
        r = self.pdf[index].rect
        return Rect(r.x0, r.y0, r.x1, r.y1)

    def page_rotation(self, index: int) -> int:
        return int(self.pdf[index].rotation)

    def page_label(self, index: int) -> str:
        try:
            lbl = self.pdf[index].get_label()
        except Exception:
            lbl = ""
        return lbl or str(index + 1)

    def pdf_to_page_matrix(self, index: int) -> Matrix:
        """Matrix from PDF user space to PyMuPDF's rotated, top-left page space."""
        page = self.pdf[index]
        m = page.transformation_matrix * page.rotation_matrix
        return Matrix(m.a, m.b, m.c, m.d, m.e, m.f)

    def render(self, index: int, scale: float, clip: Rect | None = None, annots: bool = True) -> pymupdf.Pixmap:
        page = self.pdf[index]
        mat = pymupdf.Matrix(scale, scale)
        kw: dict[str, Any] = {"matrix": mat, "alpha": False, "annots": annots}
        if clip is not None:
            kw["clip"] = pymupdf.Rect(clip.x0, clip.y0, clip.x1, clip.y1)
        return page.get_pixmap(**kw)

    # -- content ---------------------------------------------------------
    def resources(self, index: int, path: "EditPath" = ()) -> PageResources:
        key = (index, tuple(x for x, _m in path))
        res = self._resources_cache.get(key)
        if res is None:
            if path:
                parent = self.resources(index, path[:-1])
                res = PageResources(self, index, form_xref=path[-1][0], parent=parent)
            else:
                res = PageResources(self, index)
            self._resources_cache[key] = res
        return res

    def content(self, index: int, path: "EditPath" = ()) -> PageContent:
        """Parsed content of a page, or of a form XObject reached through ``path``.

        ``path`` is a tuple of ``(xobject xref, base matrix)`` pairs, outermost first;
        the base matrix maps the form's content space to page (device) space.
        """
        key = (index, tuple(path))
        pc = self._content_cache.get(key)
        if pc is None:
            page = self.pdf[index]
            mb = page.mediabox
            page_box = Rect(mb.x0, mb.y0, mb.x1, mb.y1)
            if path:
                xref, base = path[-1]
                stream = self.pdf.xref_stream(xref) or b""
                from pdfeditor.core.content.model import GraphicsState

                init = GraphicsState(ctm=base)
                info = self.form_info(xref)
                if info.bbox is not None:
                    init.clip_bbox = info.bbox.transformed(base)
                pc = interpret(stream, self.resources(index, path), page_box, initial_state=init)
            else:
                stream = page.read_contents() or b""
                pc = interpret(stream, self.resources(index), page_box)
            self._content_cache[key] = pc
        return pc

    def form_info(self, xref: int) -> XObjectInfo:
        resolver = Resolver(self.pdf)
        d = resolver.get(xref)
        info = XObjectInfo(name="", subtype="Form", xref=xref)
        if isinstance(d, dict):
            bbox = resolver.dict_get(d, "BBox")
            if isinstance(bbox, list) and len(bbox) == 4:
                info.bbox = Rect.normalized(*[as_float(resolver.resolve(v)) for v in bbox])
            mtx = resolver.dict_get(d, "Matrix")
            if isinstance(mtx, list) and len(mtx) == 6:
                info.matrix = Matrix(*[as_float(resolver.resolve(v)) for v in mtx])
        return info

    def invalidate(self, index: int | None = None) -> None:
        if index is None:
            self._content_cache.clear()
            self._resources_cache.clear()
        else:
            for key in [k for k in self._content_cache if k[0] == index]:
                self._content_cache.pop(key, None)
            for key in [k for k in self._resources_cache if k[0] == index]:
                self._resources_cache.pop(key, None)

    def apply_content_edit(self, index: int, new_stream: bytes, label: str = "Edit", path: "EditPath" = ()) -> None:
        old = self.content(index, path).stream
        if new_stream == old:
            return
        xref = path[-1][0] if path else 0
        bbox_old = bbox_new = None
        if path:
            bbox_old, bbox_new = self._grown_form_bbox(index, path, new_stream)
        cmd = ContentEditCommand(label=label, page_index=index, old_stream=old, new_stream=new_stream, page_xref=xref,
                                 bbox_old=bbox_old, bbox_new=bbox_new)
        self.undo_stack.push(cmd)

    def _grown_form_bbox(self, index: int, path: "EditPath", new_stream: bytes) -> tuple[str | None, str | None]:
        """If the edited content extends beyond the form's /BBox, return (old, grown) BBox strings."""
        from pdfeditor.core.content.model import GraphicsState

        xref, base = path[-1]
        info = self.form_info(xref)
        try:
            tmp = interpret(new_stream, self.resources(index, path), None, initial_state=GraphicsState(ctm=base))
            inv = base.inverted()
        except Exception:
            return None, None
        union = info.bbox
        for o in tmp.objects:
            if o.bbox is None or o.kind not in ("path", "text", "image", "form", "inline_image"):
                continue
            b = o.bbox.transformed(inv)
            union = b if union is None else union.union(b)
        if union is None or union == info.bbox:
            return None, None
        old = self.pdf.xref_get_key(xref, "BBox")[1]
        new = f"[{union.x0:.4f} {union.y0:.4f} {union.x1:.4f} {union.y1:.4f}]"
        return (old if old and old != "null" else None), new

    def _write_stream(self, index: int, data: bytes, xref: int = 0) -> None:
        if xref:
            # a form XObject may be used on several pages: drop every cached parse and resource info
            self.pdf.update_stream(xref, data)
            self._content_cache.clear()
            self._resources_cache.clear()
            self._emit("page_content", index)
            return
        page = self.pdf[index]
        xrefs = page.get_contents()
        if len(xrefs) == 1:
            self.pdf.update_stream(xrefs[0], data)
        else:
            new_xref = self.pdf.get_new_xref()
            self.pdf.update_object(new_xref, "<<>>")
            self.pdf.update_stream(new_xref, data)
            page.set_contents(new_xref)
        for key in [k for k in self._content_cache if k[0] == index]:
            self._content_cache.pop(key, None)
        self._emit("page_content", index)

    def ensure_substitute_font(self, index: int, fontname: str = "helv") -> tuple[str, FontInfo]:
        """Make sure a built-in font resource exists on the page; return (resource name, info)."""
        page = self.pdf[index]
        page.insert_font(fontname=fontname)
        self._resources_cache.pop(index, None)
        res = self.resources(index)
        fi = res.font(fontname)
        if fi is None:
            fi = FontInfo.fallback(fontname, "Helvetica")
        return fontname, fi

    # -- structure operations (snapshot-undoable) --------------------------
    def snapshot(self) -> bytes:
        return self.pdf.tobytes(garbage=0, deflate=False)

    def restore(self, data: bytes) -> None:
        old = self.pdf
        self.pdf = pymupdf.open(stream=data, filetype="pdf")
        try:
            old.close()
        except Exception:
            pass
        self._after_structure_change()

    def _after_structure_change(self) -> None:
        self.invalidate()
        self._emit("pages", None)

    def _structure_op(self, label: str, action: Callable[["Document"], None]) -> None:
        cmd = SnapshotCommand(label=label, before=self.snapshot(), action=action)
        self.undo_stack.push(cmd)

    def rotate_pages(self, indices: Iterable[int], delta: int) -> None:
        idx = list(indices)

        def action(doc: "Document") -> None:
            for i in idx:
                p = doc.pdf[i]
                p.set_rotation((p.rotation + delta) % 360)

        self._structure_op("Rotate page(s)", action)

    def delete_pages(self, indices: Iterable[int]) -> None:
        idx = sorted(set(indices))
        if not idx or len(idx) >= self.page_count:
            return

        def action(doc: "Document") -> None:
            doc.pdf.delete_pages(idx)

        self._structure_op("Delete page(s)", action)

    def move_page(self, src: int, dst: int) -> None:
        """Move page ``src`` so that it ends up at index ``dst``."""
        if src == dst:
            return

        def action(doc: "Document") -> None:
            n = doc.pdf.page_count
            order = list(range(n))
            order.pop(src)
            order.insert(max(0, min(dst, n - 1)), src)
            doc.pdf.select(order)

        self._structure_op("Move page", action)

    def move_pages(self, sources: Sequence[int], dst: int) -> None:
        """Move a set of pages so they start at index ``dst`` (in the original numbering)."""
        srcs = sorted(set(sources))
        if not srcs:
            return

        def action(doc: "Document") -> None:
            n = doc.pdf.page_count
            order = [i for i in range(n) if i not in srcs]
            insert_at = dst - sum(1 for s in srcs if s < dst)
            insert_at = max(0, min(insert_at, len(order)))
            order[insert_at:insert_at] = srcs
            doc.pdf.select(order)

        self._structure_op("Move page(s)", action)

    def duplicate_pages(self, indices: Iterable[int]) -> None:
        idx = sorted(set(indices))

        def action(doc: "Document") -> None:
            for i in reversed(idx):
                n = doc.pdf.page_count
                doc.pdf.copy_page(i, i + 1 if i + 1 < n else -1)

        self._structure_op("Duplicate page(s)", action)

    def insert_blank_page(self, at: int, width: float, height: float) -> None:
        def action(doc: "Document") -> None:
            doc.pdf.new_page(pno=at, width=width, height=height)

        self._structure_op("Insert blank page", action)

    def insert_pages_from(self, src_path: str, at: int, from_page: int = -1, to_page: int = -1) -> None:
        def action(doc: "Document") -> None:
            src = pymupdf.open(src_path)
            try:
                doc.pdf.insert_pdf(src, from_page=from_page, to_page=to_page, start_at=at)
            finally:
                src.close()

        self._structure_op("Insert pages", action)

    def reverse_pages(self) -> None:
        def action(doc: "Document") -> None:
            doc.pdf.select(list(range(doc.pdf.page_count - 1, -1, -1)))

        self._structure_op("Reverse page order", action)

    def set_cropbox(self, indices: Iterable[int], rect: Rect) -> None:
        idx = list(indices)

        def action(doc: "Document") -> None:
            for i in idx:
                p = doc.pdf[i]
                r = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1) & p.mediabox
                if not r.is_empty:
                    p.set_cropbox(r)

        self._structure_op("Crop page(s)", action)

    def set_cropbox_margins(self, indices: Iterable[int], left: float, top: float, right: float, bottom: float) -> None:
        """Crop by margins measured in points from the current visible page edges."""
        idx = list(indices)

        def action(doc: "Document") -> None:
            for i in idx:
                p = doc.pdf[i]
                cb = p.cropbox  # unrotated PDF coordinates (y up); treat top/bottom accordingly
                r = pymupdf.Rect(cb.x0 + left, cb.y0 + top, cb.x1 - right, cb.y1 - bottom)
                r = r & p.mediabox
                if not r.is_empty and r.width > 1 and r.height > 1:
                    p.set_cropbox(r)

        self._structure_op("Crop page(s)", action)

    def reset_cropbox(self, indices: Iterable[int]) -> None:
        idx = list(indices)

        def action(doc: "Document") -> None:
            for i in idx:
                p = doc.pdf[i]
                p.set_cropbox(p.mediabox)

        self._structure_op("Reset crop", action)

    def extract_pages(self, indices: Sequence[int], out_path: str) -> None:
        """Write the selected pages to a new PDF (does not modify this document)."""
        out = pymupdf.open()
        try:
            for i in indices:
                out.insert_pdf(self.pdf, from_page=i, to_page=i)
            out.save(out_path, garbage=3, deflate=True)
        finally:
            out.close()

    def split_every(self, chunk: int, out_dir: str, stem: str) -> list[str]:
        paths: list[str] = []
        n = self.page_count
        k = 1
        for start in range(0, n, chunk):
            end = min(start + chunk, n) - 1
            out = pymupdf.open()
            out.insert_pdf(self.pdf, from_page=start, to_page=end)
            p = os.path.join(out_dir, f"{stem}-{k:03d}.pdf")
            out.save(p, garbage=3, deflate=True)
            out.close()
            paths.append(p)
            k += 1
        return paths

    # -- saving ------------------------------------------------------------
    def save(self, path: str | None = None, garbage: int = 3) -> None:
        target = path or self.path
        if not target:
            raise ValueError("no path to save to")
        target = os.path.abspath(target)
        directory = os.path.dirname(target) or "."
        fd, tmp = tempfile.mkstemp(prefix=".pdfeditor-", suffix=".pdf", dir=directory)
        os.close(fd)
        try:
            self.pdf.save(tmp, garbage=garbage, deflate=True, use_objstms=0, **self.security.to_save_args())
            os.replace(tmp, target)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        # Reopen from the saved file so further edits/incremental state are sane
        data = open(target, "rb").read()
        old = self.pdf
        self.pdf = pymupdf.open(stream=data, filetype="pdf")
        if self.pdf.needs_pass:
            pw = self.security.user_password or self.security.owner_password
            self.pdf.authenticate(pw)
        self.security = SecuritySettings()
        try:
            old.close()
        except Exception:
            pass
        self.path = target
        self.invalidate()
        self.undo_stack.mark_clean()
        self._emit("saved", target)
