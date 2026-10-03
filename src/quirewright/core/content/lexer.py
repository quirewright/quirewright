"""Tokenizer for PDF content streams and PDF object syntax.

Produces a flat sequence of :class:`Token` objects. Arrays and dictionaries are
parsed recursively into Python lists/dicts so that an operator's operands are
immediately usable. Byte offsets of every token are retained so that the
interpreter can map objects back to spans of the original stream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"
_REGULAR_END = WHITESPACE + DELIMITERS

_NUMBER_RE = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")


class Name(str):
    """A PDF name object (stored without the leading slash)."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"/{str.__str__(self)}"


class Keyword(str):
    """A bare keyword/operator token such as ``Tj``, ``obj`` or ``R``."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return f"Keyword({str.__str__(self)})"


@dataclass(slots=True)
class Token:
    kind: str  # "num", "name", "str", "arr", "dict", "op", "bool", "null"
    value: Any
    start: int
    end: int


class LexError(ValueError):
    pass


class Lexer:
    """Incremental tokenizer over a ``bytes`` buffer.

    ``object_mode`` enables folding of ``<num> <gen> R`` into
    :class:`~quirewright.core.pdfobj.Ref` instances inside arrays/dicts (needed
    for parsing PDF objects rather than content streams).
    """

    def __init__(self, data: bytes, object_mode: bool = False):
        self.data = data
        self.pos = 0
        self.n = len(data)
        self.object_mode = object_mode

    # -- helpers ---------------------------------------------------------
    def skip_whitespace(self) -> None:
        data, n = self.data, self.n
        while self.pos < n:
            ch = data[self.pos]
            if ch in WHITESPACE:
                self.pos += 1
            elif ch == 0x25:  # '%' comment
                while self.pos < n and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                break

    def at_end(self) -> bool:
        self.skip_whitespace()
        return self.pos >= self.n

    # -- tokens ----------------------------------------------------------
    def next_token(self) -> Token | None:
        self.skip_whitespace()
        if self.pos >= self.n:
            return None
        data = self.data
        start = self.pos
        ch = data[start]

        if ch in b"+-.0123456789":
            m = _NUMBER_RE.match(data, start)
            if m and m.end() > start:
                self.pos = m.end()
                text = m.group(0)
                # Tolerate junk like "--5" or "3.4.5" by consuming trailing regular chars
                while self.pos < self.n and data[self.pos] not in _REGULAR_END:
                    self.pos += 1
                try:
                    if b"." in text:
                        value: float | int = float(text)
                    else:
                        value = int(text)
                except ValueError:
                    value = 0
                return Token("num", value, start, self.pos)
            # fallthrough: treat as operator (e.g. a lone '-')

        if ch == 0x2F:  # '/'
            self.pos += 1
            while self.pos < self.n and data[self.pos] not in _REGULAR_END:
                self.pos += 1
            raw = data[start + 1 : self.pos]
            return Token("name", Name(_decode_name(raw)), start, self.pos)

        if ch == 0x28:  # '('
            value = self._read_literal_string()
            return Token("str", value, start, self.pos)

        if ch == 0x3C:  # '<'
            if data.startswith(b"<<", start):
                self.pos += 2
                value = self._read_dict()
                return Token("dict", value, start, self.pos)
            value = self._read_hex_string()
            return Token("str", value, start, self.pos)

        if ch == 0x5B:  # '['
            self.pos += 1
            value = self._read_array()
            return Token("arr", value, start, self.pos)

        if ch in b"]>}":  # stray closers: skip
            self.pos += 1
            return self.next_token()
        if ch == 0x7B:  # '{' (PostScript function syntax; not expected) - skip
            self.pos += 1
            return self.next_token()
        if ch == 0x29:  # stray ')'
            self.pos += 1
            return self.next_token()

        # regular keyword / operator
        while self.pos < self.n and data[self.pos] not in _REGULAR_END:
            self.pos += 1
        if self.pos == start:  # should not happen, but avoid infinite loops
            self.pos += 1
            return self.next_token()
        word = data[start : self.pos]
        if word == b"true":
            return Token("bool", True, start, self.pos)
        if word == b"false":
            return Token("bool", False, start, self.pos)
        if word == b"null":
            return Token("null", None, start, self.pos)
        return Token("op", Keyword(word.decode("latin-1")), start, self.pos)

    def _read_literal_string(self) -> bytes:
        data = self.data
        assert data[self.pos] == 0x28
        self.pos += 1
        depth = 1
        out = bytearray()
        n = self.n
        while self.pos < n:
            ch = data[self.pos]
            if ch == 0x5C:  # backslash
                self.pos += 1
                if self.pos >= n:
                    break
                e = data[self.pos]
                if e == 0x6E:
                    out.append(10)
                elif e == 0x72:
                    out.append(13)
                elif e == 0x74:
                    out.append(9)
                elif e == 0x62:
                    out.append(8)
                elif e == 0x66:
                    out.append(12)
                elif e in b"01234567":
                    oct_digits = bytes([e])
                    for _ in range(2):
                        if self.pos + 1 < n and data[self.pos + 1] in b"01234567":
                            self.pos += 1
                            oct_digits += bytes([data[self.pos]])
                        else:
                            break
                    out.append(int(oct_digits, 8) & 0xFF)
                elif e == 0x0D:  # line continuation \r or \r\n
                    if self.pos + 1 < n and data[self.pos + 1] == 0x0A:
                        self.pos += 1
                elif e == 0x0A:
                    pass
                else:
                    out.append(e)
                self.pos += 1
            elif ch == 0x28:
                depth += 1
                out.append(ch)
                self.pos += 1
            elif ch == 0x29:
                depth -= 1
                self.pos += 1
                if depth == 0:
                    break
                out.append(ch)
            elif ch == 0x0D:
                # EOL inside string is normalized to \n
                out.append(10)
                self.pos += 1
                if self.pos < n and data[self.pos] == 0x0A:
                    self.pos += 1
            else:
                out.append(ch)
                self.pos += 1
        return bytes(out)

    def _read_hex_string(self) -> bytes:
        data = self.data
        assert data[self.pos] == 0x3C
        self.pos += 1
        digits = bytearray()
        n = self.n
        while self.pos < n:
            ch = data[self.pos]
            self.pos += 1
            if ch == 0x3E:
                break
            if ch in b"0123456789abcdefABCDEF":
                digits.append(ch)
            # whitespace / junk ignored
        if len(digits) % 2:
            digits.append(0x30)
        try:
            return bytes.fromhex(digits.decode("ascii"))
        except ValueError:
            return b""

    def _read_array(self) -> list:
        items: list[Any] = []
        while True:
            self.skip_whitespace()
            if self.pos >= self.n:
                break
            if self.data[self.pos] == 0x5D:  # ']'
                self.pos += 1
                break
            tok = self.next_token()
            if tok is None:
                break
            self._append_value(items, tok)
        return items

    def _read_dict(self) -> dict:
        items: list[Any] = []
        while True:
            self.skip_whitespace()
            if self.pos >= self.n:
                break
            if self.data.startswith(b">>", self.pos):
                self.pos += 2
                break
            tok = self.next_token()
            if tok is None:
                break
            self._append_value(items, tok)
        out: dict[str, Any] = {}
        i = 0
        while i + 1 < len(items):
            key = items[i]
            if isinstance(key, Name):
                out[str(key)] = items[i + 1]
                i += 2
            else:
                i += 1
        return out

    def _append_value(self, items: list, tok: Token) -> None:
        if tok.kind == "op":
            if self.object_mode and tok.value == "R" and len(items) >= 2 and isinstance(items[-1], int) and isinstance(items[-2], int):
                from quirewright.core.pdfobj import Ref

                gen = items.pop()
                num = items.pop()
                items.append(Ref(num, gen))
                return
            items.append(tok.value)  # Keyword
        else:
            items.append(tok.value)

    # -- inline image support -------------------------------------------
    def read_inline_image_data(self, params: dict) -> bytes:
        """Called right after the ``ID`` operator: consume binary data up to ``EI``.

        Returns the raw (still encoded) image data. ``self.pos`` is left after ``EI``.
        """
        data = self.data
        # exactly one whitespace byte follows ID
        if self.pos < self.n and data[self.pos] in WHITESPACE:
            self.pos += 1
        start = self.pos
        length = _inline_image_length(params)
        if length is not None and start + length <= self.n:
            end = start + length
            m = re.compile(rb"\s*EI(?=[\s\[\]/<>(%]|$)").match(data, end)
            if m:
                self.pos = m.end()
                return data[start:end]
        # Search for whitespace EI followed by a delimiter/whitespace/EOF
        pat = re.compile(rb"[\s>]EI(?=[\s\[\]/<>(%]|$)")
        m = pat.search(data, start)
        if not m:
            self.pos = self.n
            return data[start:]
        self.pos = m.end()
        return data[start : m.start()]


def _inline_image_length(params: dict) -> int | None:
    """Compute the byte length of unfiltered inline image data, if determinable."""
    if "L" in params and isinstance(params["L"], int):
        return params["L"]
    if "Length" in params and isinstance(params["Length"], int):
        return params["Length"]
    filters = params.get("F", params.get("Filter"))
    if filters:
        return None
    w = params.get("W", params.get("Width"))
    h = params.get("H", params.get("Height"))
    bpc = params.get("BPC", params.get("BitsPerComponent", 8))
    if params.get("IM", params.get("ImageMask")):
        bpc = 1
        ncomp = 1
    else:
        cs = params.get("CS", params.get("ColorSpace", "DeviceGray"))
        cs_name = str(cs) if isinstance(cs, str) else ""
        if cs_name in ("DeviceRGB", "RGB", "CalRGB"):
            ncomp = 3
        elif cs_name in ("DeviceCMYK", "CMYK"):
            ncomp = 4
        elif cs_name in ("DeviceGray", "G", "CalGray", "I", "Indexed"):
            ncomp = 1
        else:
            return None
    if not isinstance(w, int) or not isinstance(h, int) or not isinstance(bpc, int):
        return None
    row_bytes = (w * bpc * ncomp + 7) // 8
    return row_bytes * h


def _decode_name(raw: bytes) -> str:
    if b"#" not in raw:
        return raw.decode("latin-1")
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == 0x23 and i + 2 < n:
            try:
                out.append(int(raw[i + 1 : i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(ch)
        i += 1
    return out.decode("latin-1")


def tokenize(data: bytes, object_mode: bool = False) -> list[Token]:
    lx = Lexer(data, object_mode=object_mode)
    out: list[Token] = []
    while True:
        tok = lx.next_token()
        if tok is None:
            break
        out.append(tok)
    return out
