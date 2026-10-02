"""Font metrics and encodings needed to lay out and re-encode text runs.

A :class:`FontInfo` answers three questions for a font resource:

* how a string's bytes split into character codes,
* how wide each code is (text space, font size 1) and what its ascent/descent are,
* what Unicode text a code represents, and conversely which code (if any)
  encodes a given character so edited text can be written back.

Metrics come from the PDF font dictionary (``/Widths`` or ``/W``), falling
back to the standard-14 metrics shipped with MuPDF for non-embedded fonts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pdfeditor.core.content.lexer import Lexer, Name
from pdfeditor.core.encodings import BASE_ENCODINGS, STANDARD_ENCODING, glyph_name_to_unicode
from pdfeditor.core.geometry import Matrix
from pdfeditor.core.pdfobj import Ref, Resolver, as_float

log = logging.getLogger(__name__)

STANDARD14_ALIASES = {
    # (family, bold, italic) -> MuPDF built-in name
    ("helv", False, False): "helv",
    ("helv", True, False): "hebo",
    ("helv", False, True): "heit",
    ("helv", True, True): "hebi",
    ("tiro", False, False): "tiro",
    ("tiro", True, False): "tibo",
    ("tiro", False, True): "tiit",
    ("tiro", True, True): "tibi",
    ("cour", False, False): "cour",
    ("cour", True, False): "cobo",
    ("cour", False, True): "coit",
    ("cour", True, True): "cobi",
}


def builtin_font_name(base_font: str, flags: int = 0) -> str:
    """Pick the closest MuPDF built-in (standard 14) font for a base font name."""
    name = base_font.split("+")[-1] if "+" in base_font[:8] else base_font
    low = name.lower()
    bold = "bold" in low or "black" in low or "heavy" in low or bool(flags & (1 << 18))
    italic = "italic" in low or "oblique" in low or bool(flags & (1 << 6))
    if "symbol" in low:
        return "symb"
    if "zapf" in low or "dingbat" in low:
        return "zadb"
    if "courier" in low or "mono" in low or (flags & 1 and "cour" in low):
        fam = "cour"
    elif "times" in low or "serif" in low or "georgia" in low or "book" in low or "roman" in low or "garamond" in low:
        fam = "tiro"
    else:
        fam = "helv"
    return STANDARD14_ALIASES[(fam, bold, italic)]


@dataclass(slots=True)
class CodeRange:
    nbytes: int
    low: int
    high: int


@dataclass
class FontInfo:
    name: str  # resource name, e.g. "F1"
    base_font: str = "Helvetica"
    subtype: str = "Type1"
    xref: int = 0
    is_type0: bool = False
    is_type3: bool = False
    is_subset: bool = False
    embedded: bool = False
    font_matrix: Matrix = field(default_factory=lambda: Matrix(0.001, 0, 0, 0.001, 0, 0))
    code_ranges: list[CodeRange] = field(default_factory=list)  # empty => single byte
    widths: dict[int, float] = field(default_factory=dict)  # code -> width (text space)
    default_width: float | None = None
    ascent: float = 0.9
    descent: float = -0.2
    code_to_unicode: dict[int, str] = field(default_factory=dict)
    encoding_unicode: dict[int, str] = field(default_factory=dict)  # from /Encoding only
    builtin: str | None = None  # MuPDF builtin name used for fallback widths
    _unicode_to_code: dict[str, int] | None = field(default=None, repr=False)
    _builtin_widths: dict[int, float] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    @property
    def display_name(self) -> str:
        bf = self.base_font
        if "+" in bf[:8]:
            bf = bf.split("+", 1)[1]
        return bf

    def decode(self, data: bytes) -> list[tuple[int, int]]:
        """Split string bytes into ``(code, nbytes)`` pairs."""
        if not self.code_ranges:
            return [(b, 1) for b in data]
        out: list[tuple[int, int]] = []
        i = 0
        n = len(data)
        ranges = self.code_ranges
        while i < n:
            matched = False
            for nb in (1, 2, 3, 4):
                if i + nb > n:
                    break
                code = int.from_bytes(data[i : i + nb], "big")
                for r in ranges:
                    if r.nbytes == nb and r.low <= code <= r.high:
                        out.append((code, nb))
                        i += nb
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                # Fall back to the shortest codespace length (or 1 byte)
                nb = min((r.nbytes for r in ranges), default=1)
                if i + nb > n:
                    nb = n - i
                out.append((int.from_bytes(data[i : i + nb], "big"), nb))
                i += nb
        return out

    def encode_code(self, code: int) -> bytes:
        if not self.code_ranges:
            return bytes([code & 0xFF])
        for r in self.code_ranges:
            if r.low <= code <= r.high:
                return code.to_bytes(r.nbytes, "big")
        nb = max((r.nbytes for r in self.code_ranges), default=1)
        return code.to_bytes(nb, "big")

    def width(self, code: int) -> float:
        w = self.widths.get(code)
        if w is not None:
            return w
        if self.default_width is not None:
            return self.default_width
        if self.builtin:
            return self._builtin_width(code)
        return 0.5

    def _builtin_width(self, code: int) -> float:
        if code in self._builtin_widths:
            return self._builtin_widths[code]
        ch = self.unicode(code)
        w = 0.5
        if ch:
            try:
                import pymupdf

                w = pymupdf.get_text_length(ch, fontname=self.builtin or "helv", fontsize=1000) / 1000.0
            except Exception:
                w = 0.5
        self._builtin_widths[code] = w
        return w

    def unicode(self, code: int) -> str:
        u = self.code_to_unicode.get(code)
        if u is not None:
            return u
        u = self.encoding_unicode.get(code)
        if u is not None:
            return u
        if not self.is_type0 and 32 <= code < 127:
            return chr(code)
        return ""

    def unicode_to_code(self) -> dict[str, int]:
        if self._unicode_to_code is None:
            inv: dict[str, int] = {}
            # Codes known from ToUnicode are certainly present in the font program.
            for code, u in self.code_to_unicode.items():
                if u and u not in inv:
                    inv[u] = code
            # Codes from /Encoding: for subset fonts only trust codes with a width.
            for code, u in self.encoding_unicode.items():
                if not u or u in inv:
                    continue
                if self.is_subset and not (self.widths.get(code, 0) > 0):
                    continue
                inv[u] = code
            if not self.is_type0 and not self.is_subset:
                for c in range(32, 127):
                    inv.setdefault(chr(c), c)
            self._unicode_to_code = inv
        return self._unicode_to_code

    def encode(self, text: str) -> bytes | None:
        """Encode ``text`` using this font, or return None if a character cannot be encoded."""
        inv = self.unicode_to_code()
        out = bytearray()
        for ch in text:
            code = inv.get(ch)
            if code is None:
                # try decomposed ligatures etc.
                return None
            out += self.encode_code(code)
        return bytes(out)

    def unencodable(self, text: str) -> str:
        inv = self.unicode_to_code()
        return "".join(ch for ch in text if ch not in inv)

    def is_word_space(self, code: int, nbytes: int) -> bool:
        return nbytes == 1 and code == 32

    # ------------------------------------------------------------------
    @classmethod
    def fallback(cls, name: str, base_font: str = "Helvetica") -> "FontInfo":
        fi = cls(name=name, base_font=base_font, builtin=builtin_font_name(base_font))
        fi.encoding_unicode = dict(STANDARD_ENCODING)
        return fi

    @classmethod
    def load(cls, doc, resolver: Resolver, font_obj: Any, name: str, xref: int = 0) -> "FontInfo":
        """Build a FontInfo from a font dictionary (or a reference to one)."""
        if isinstance(font_obj, Ref):
            xref = font_obj.num
        d = resolver.resolve(font_obj)
        if not isinstance(d, dict):
            return cls.fallback(name)
        subtype = str(resolver.dict_get(d, "Subtype", "Type1"))
        base_font = str(resolver.dict_get(d, "BaseFont", "Helvetica"))
        fi = cls(name=name, base_font=base_font, subtype=subtype, xref=xref)
        fi.is_subset = len(base_font) > 7 and base_font[6] == "+" and base_font[:6].isupper()
        try:
            if subtype == "Type0":
                fi.is_type0 = True
                _load_type0(fi, resolver, d)
            elif subtype == "Type3":
                fi.is_type3 = True
                _load_type3(fi, resolver, d)
            else:
                _load_simple(fi, resolver, d)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("font %s: metrics load failed: %s", name, exc)
        # ToUnicode
        tu = d.get("ToUnicode")
        if tu is not None:
            data = resolver.stream(tu)
            if data:
                try:
                    ranges, mapping = parse_cmap(data)
                    fi.code_to_unicode.update(mapping)
                    if fi.is_type0 and not fi.code_ranges and ranges:
                        fi.code_ranges = ranges
                except Exception as exc:  # pragma: no cover
                    log.warning("font %s: ToUnicode parse failed: %s", name, exc)
        if fi.is_type0 and not fi.code_ranges:
            fi.code_ranges = [CodeRange(2, 0, 0xFFFF)]
        if not fi.widths and not fi.is_type3:
            fi.builtin = builtin_font_name(base_font)
            fi.default_width = None
        return fi


# ----------------------------------------------------------------------
def _font_descriptor_metrics(fi: FontInfo, resolver: Resolver, desc: Any, scale: float = 0.001) -> int:
    desc = resolver.resolve(desc)
    flags = 0
    if not isinstance(desc, dict):
        return flags
    flags = int(as_float(resolver.dict_get(desc, "Flags", 0)))
    asc = as_float(resolver.dict_get(desc, "Ascent", 0))
    dsc = as_float(resolver.dict_get(desc, "Descent", 0))
    bbox = resolver.dict_get(desc, "FontBBox")
    if (asc == 0 or dsc == 0) and isinstance(bbox, list) and len(bbox) == 4:
        if asc == 0:
            asc = as_float(resolver.resolve(bbox[3]))
        if dsc == 0:
            dsc = as_float(resolver.resolve(bbox[1]))
    if asc > 0:
        fi.ascent = asc * scale
    if dsc < 0:
        fi.descent = dsc * scale
    elif dsc > 0:
        fi.descent = -dsc * scale
    mw = resolver.dict_get(desc, "MissingWidth")
    if isinstance(mw, (int, float)):
        fi.default_width = float(mw) * scale
    for key in ("FontFile", "FontFile2", "FontFile3"):
        if key in desc:
            fi.embedded = True
    return flags


def _load_simple(fi: FontInfo, resolver: Resolver, d: dict) -> None:
    flags = _font_descriptor_metrics(fi, resolver, d.get("FontDescriptor"))
    symbolic = bool(flags & 4) and not (flags & 32)
    widths = resolver.dict_get(d, "Widths")
    first = int(as_float(resolver.dict_get(d, "FirstChar", 0)))
    if isinstance(widths, list) and widths:
        for i, w in enumerate(widths):
            w = resolver.resolve(w)
            if isinstance(w, (int, float)):
                fi.widths[first + i] = float(w) / 1000.0
        if fi.default_width is None:
            fi.default_width = 0.0
    # Encoding
    base: dict[int, str] | None = None
    enc = resolver.dict_get(d, "Encoding")
    diffs = None
    if isinstance(enc, Name):
        base = BASE_ENCODINGS.get(str(enc))
    elif isinstance(enc, dict):
        be = resolver.dict_get(enc, "BaseEncoding")
        if isinstance(be, Name):
            base = BASE_ENCODINGS.get(str(be))
        diffs = resolver.dict_get(enc, "Differences")
    if base is None and not symbolic:
        base = STANDARD_ENCODING
    if base is None and fi.subtype == "TrueType" and not fi.embedded:
        base = BASE_ENCODINGS["WinAnsiEncoding"]
    table: dict[int, str] = dict(base) if base else {}
    if isinstance(diffs, list):
        code = 0
        for item in diffs:
            item = resolver.resolve(item)
            if isinstance(item, (int, float)):
                code = int(item)
            elif isinstance(item, Name):
                u = glyph_name_to_unicode(str(item))
                if u is not None:
                    table[code] = u
                else:
                    table.pop(code, None)
                code += 1
    fi.encoding_unicode = table
    fi.builtin = builtin_font_name(fi.base_font, flags)


def _load_type3(fi: FontInfo, resolver: Resolver, d: dict) -> None:
    fm = resolver.dict_get(d, "FontMatrix")
    if isinstance(fm, list) and len(fm) == 6:
        vals = [as_float(resolver.resolve(v)) for v in fm]
        fi.font_matrix = Matrix(*vals)
    _font_descriptor_metrics(fi, resolver, d.get("FontDescriptor"), scale=1.0)
    # Ascent/descent in glyph space: scale through the font matrix's d component
    sy = fi.font_matrix.d or 0.001
    fi.ascent = fi.ascent * sy if fi.ascent != 0.9 else 0.9
    fi.descent = fi.descent * sy if fi.descent != -0.2 else -0.2
    bbox = resolver.dict_get(d, "FontBBox")
    if isinstance(bbox, list) and len(bbox) == 4:
        y0 = as_float(resolver.resolve(bbox[1]))
        y1 = as_float(resolver.resolve(bbox[3]))
        if y1 > y0:
            _, a = fi.font_matrix.apply_vector(0, y1)
            _, b = fi.font_matrix.apply_vector(0, y0)
            fi.ascent, fi.descent = max(a, b), min(a, b)
    widths = resolver.dict_get(d, "Widths")
    first = int(as_float(resolver.dict_get(d, "FirstChar", 0)))
    if isinstance(widths, list):
        for i, w in enumerate(widths):
            w = as_float(resolver.resolve(w))
            wx, _ = fi.font_matrix.apply_vector(w, 0)
            fi.widths[first + i] = wx
    fi.default_width = 0.0
    enc = resolver.dict_get(d, "Encoding")
    table: dict[int, str] = {}
    if isinstance(enc, dict):
        diffs = resolver.dict_get(enc, "Differences")
        if isinstance(diffs, list):
            code = 0
            for item in diffs:
                item = resolver.resolve(item)
                if isinstance(item, (int, float)):
                    code = int(item)
                elif isinstance(item, Name):
                    u = glyph_name_to_unicode(str(item))
                    if u is not None:
                        table[code] = u
                    code += 1
    fi.encoding_unicode = table


def _load_type0(fi: FontInfo, resolver: Resolver, d: dict) -> None:
    enc = resolver.dict_get(d, "Encoding")
    if isinstance(enc, Name):
        if str(enc).startswith("Identity"):
            fi.code_ranges = [CodeRange(2, 0, 0xFFFF)]
        else:
            fi.code_ranges = [CodeRange(2, 0, 0xFFFF)]  # predefined CMaps: assume 2 bytes
    elif isinstance(d.get("Encoding"), Ref):
        data = resolver.stream(d["Encoding"])
        if data:
            try:
                ranges, _ = parse_cmap(data)
                if ranges:
                    fi.code_ranges = ranges
            except Exception:
                pass
    desc_fonts = resolver.dict_get(d, "DescendantFonts")
    df = None
    if isinstance(desc_fonts, list) and desc_fonts:
        df = resolver.resolve(desc_fonts[0])
    if isinstance(df, dict):
        _font_descriptor_metrics(fi, resolver, df.get("FontDescriptor"))
        dw = resolver.dict_get(df, "DW", 1000)
        fi.default_width = as_float(dw, 1000) / 1000.0
        w = resolver.dict_get(df, "W")
        if isinstance(w, list):
            _parse_w_array(fi, resolver, w)
    else:
        fi.default_width = 1.0


def _parse_w_array(fi: FontInfo, resolver: Resolver, w: list) -> None:
    items = [resolver.resolve(x) for x in w]
    i = 0
    n = len(items)
    while i < n:
        first = items[i]
        if not isinstance(first, (int, float)):
            i += 1
            continue
        if i + 1 < n and isinstance(items[i + 1], list):
            arr = items[i + 1]
            for j, ww in enumerate(arr):
                ww = resolver.resolve(ww)
                if isinstance(ww, (int, float)):
                    fi.widths[int(first) + j] = float(ww) / 1000.0
            i += 2
        elif i + 2 < n and isinstance(items[i + 1], (int, float)) and isinstance(items[i + 2], (int, float)):
            last = int(items[i + 1])
            ww = float(items[i + 2]) / 1000.0
            if last - int(first) < 65536:
                for c in range(int(first), last + 1):
                    fi.widths[c] = ww
            i += 3
        else:
            i += 1


# ----------------------------------------------------------------------
def parse_cmap(data: bytes) -> tuple[list[CodeRange], dict[int, str]]:
    """Parse the parts of a CMap we care about: codespace ranges and bf mappings."""
    lx = Lexer(data)
    stack: list[Any] = []
    ranges: list[CodeRange] = []
    mapping: dict[int, str] = {}
    mode: str | None = None
    while True:
        tok = lx.next_token()
        if tok is None:
            break
        if tok.kind == "op":
            op = str(tok.value)
            if op == "begincodespacerange":
                mode = "cs"
                stack = []
            elif op == "endcodespacerange":
                for lo, hi in _pairs(stack):
                    if isinstance(lo, bytes) and isinstance(hi, bytes) and lo:
                        ranges.append(CodeRange(len(lo), int.from_bytes(lo, "big"), int.from_bytes(hi, "big")))
                mode = None
                stack = []
            elif op == "beginbfchar":
                mode = "bfchar"
                stack = []
            elif op == "endbfchar":
                for src, dst in _pairs(stack):
                    if isinstance(src, bytes):
                        u = _dst_to_unicode(dst)
                        if u is not None:
                            mapping[int.from_bytes(src, "big")] = u
                mode = None
                stack = []
            elif op == "beginbfrange":
                mode = "bfrange"
                stack = []
            elif op == "endbfrange":
                for lo, hi, dst in _triples(stack):
                    if not (isinstance(lo, bytes) and isinstance(hi, bytes)):
                        continue
                    lo_i = int.from_bytes(lo, "big")
                    hi_i = int.from_bytes(hi, "big")
                    if hi_i - lo_i > 65535:
                        continue
                    if isinstance(dst, list):
                        for k, item in enumerate(dst):
                            u = _dst_to_unicode(item)
                            if u is not None:
                                mapping[lo_i + k] = u
                    else:
                        base = _dst_to_unicode(dst)
                        if base is None:
                            continue
                        if len(base) == 0:
                            continue
                        last_cp = ord(base[-1])
                        prefix = base[:-1]
                        for k in range(hi_i - lo_i + 1):
                            mapping[lo_i + k] = prefix + chr(last_cp + k)
                mode = None
                stack = []
            else:
                if mode is None:
                    stack = []
        else:
            if mode is not None:
                stack.append(tok.value)
    return ranges, mapping


def _pairs(items: list) -> list[tuple[Any, Any]]:
    return [(items[i], items[i + 1]) for i in range(0, len(items) - 1, 2)]


def _triples(items: list) -> list[tuple[Any, Any, Any]]:
    return [(items[i], items[i + 1], items[i + 2]) for i in range(0, len(items) - 2, 3)]


def _dst_to_unicode(dst: Any) -> str | None:
    if isinstance(dst, bytes):
        if len(dst) % 2 == 1:
            dst = dst + b"\x00"
        try:
            return dst.decode("utf-16-be", errors="replace")
        except Exception:
            return None
    if isinstance(dst, Name):
        return glyph_name_to_unicode(str(dst))
    if isinstance(dst, int):
        try:
            return chr(dst)
        except ValueError:
            return None
    return None
