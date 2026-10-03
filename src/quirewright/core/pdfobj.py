"""Parsing of PDF object syntax (dictionaries, arrays, references) and
resolution of indirect references through a PyMuPDF document.

PyMuPDF exposes objects as source text via ``Document.xref_object``; this module
turns that text into Python values so font dictionaries, resources and
XObject attributes can be inspected without a second PDF library.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from quirewright.core.content.lexer import Keyword, Lexer, Name


class Ref(NamedTuple):
    num: int
    gen: int = 0


def parse_object(text: bytes | str) -> Any:
    """Parse a single PDF object from its textual representation."""
    if isinstance(text, str):
        text = text.encode("latin-1", errors="replace")
    lx = Lexer(text, object_mode=True)
    items: list[Any] = []
    while True:
        tok = lx.next_token()
        if tok is None:
            break
        if tok.kind == "op":
            if tok.value == "R" and len(items) >= 2 and isinstance(items[-1], int) and isinstance(items[-2], int):
                gen = items.pop()
                num = items.pop()
                items.append(Ref(num, gen))
            elif tok.value in ("obj", "endobj", "stream", "endstream"):
                continue
            else:
                items.append(tok.value)
        else:
            items.append(tok.value)
    # "n g obj <object>" form: drop the leading numbers if an object follows
    if len(items) >= 3 and isinstance(items[0], int) and isinstance(items[1], int):
        items = items[2:]
    if not items:
        return None
    return items[0]


class Resolver:
    """Resolves indirect references via a PyMuPDF document."""

    def __init__(self, doc):
        self.doc = doc
        self._cache: dict[int, Any] = {}

    def resolve(self, value: Any, depth: int = 0) -> Any:
        while isinstance(value, Ref) and depth < 32:
            value = self.get(value.num)
            depth += 1
        return value

    def get(self, xref: int) -> Any:
        if xref in self._cache:
            return self._cache[xref]
        try:
            text = self.doc.xref_object(xref, compressed=False)
        except Exception:
            text = ""
        try:
            value = parse_object(text) if text else None
        except Exception:
            value = None
        self._cache[xref] = value
        return value

    def stream(self, value: Any) -> bytes | None:
        """Return decoded stream contents for a reference to a stream object."""
        if isinstance(value, Ref):
            try:
                return self.doc.xref_stream(value.num)
            except Exception:
                return None
        return None

    def dict_get(self, d: Any, key: str, default: Any = None) -> Any:
        """Lookup ``key`` in dict ``d`` (resolving refs on both the dict and the value)."""
        d = self.resolve(d)
        if not isinstance(d, dict):
            return default
        if key not in d:
            return default
        return self.resolve(d[key])


def as_float(v: Any, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return default


def as_name(v: Any) -> str | None:
    if isinstance(v, Name):
        return str(v)
    if isinstance(v, Keyword):
        return str(v)
    return None
