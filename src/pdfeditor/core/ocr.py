"""Optical character recognition via Tesseract (through PyMuPDF), producing an
invisible text layer that makes scanned pages searchable and selectable."""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from typing import Iterable

import pymupdf

from pdfeditor.core.content.model import Color
from pdfeditor.core.content.writer import ContentEditor, text_width
from pdfeditor.core.geometry import Rect

INSTALL_HINT = (
    "OCR needs the Tesseract engine and at least one language pack.\n\n"
    "Arch:    sudo pacman -S tesseract tesseract-data-eng\n"
    "Debian:  sudo apt install tesseract-ocr tesseract-ocr-eng\n"
    "Fedora:  sudo dnf install tesseract tesseract-langpack-eng\n"
    "macOS:   brew install tesseract\n"
    "Windows: install from the UB Mannheim builds and set TESSDATA_PREFIX."
)


@dataclass
class OcrWord:
    text: str
    rect: Rect  # scene (rotated page) space


def tessdata_dir() -> str | None:
    env = os.environ.get("TESSDATA_PREFIX")
    candidates = [env] if env else []
    candidates += ["/usr/share/tessdata", "/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
                   "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata", "/usr/share/tesseract/tessdata"]
    for c in candidates:
        if c and os.path.isdir(c) and glob.glob(os.path.join(c, "*.traineddata")):
            return c
    return None


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None and tessdata_dir() is not None


def languages() -> list[str]:
    d = tessdata_dir()
    if not d:
        return []
    names = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(d, "*.traineddata")))
    return [n for n in names if n not in ("osd", "equ")]


def recognize(doc, index: int, language: str = "eng", dpi: int = 300) -> list[OcrWord]:
    """Run OCR on a page and return the recognised words with scene-space boxes."""
    if not tesseract_available():
        raise RuntimeError(INSTALL_HINT)
    d = tessdata_dir()
    if d and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = d
    page = doc.pdf[index]
    tp = page.get_textpage_ocr(flags=0, language=language, dpi=dpi, full=True)
    words = page.get_text("words", textpage=tp)
    rm = page.rotation_matrix
    out: list[OcrWord] = []
    for w in words:
        text = w[4].strip()
        if not text:
            continue
        r = pymupdf.Rect(w[:4]) * rm
        out.append(OcrWord(text=text, rect=Rect.normalized(r.x0, r.y0, r.x1, r.y1)))
    return out


def add_text_layer(doc, index: int, words: Iterable[OcrWord], font: str = "helv") -> int:
    """Append invisible text runs (render mode 3) fitted to each word box. Returns the count."""
    words = list(words)
    if not words:
        return 0
    name, fi = doc.ensure_substitute_font(index, font)
    pc = doc.content(index)
    ed = ContentEditor(pc)
    inv = doc.pdf_to_page_matrix(index).inverted()  # scene -> PDF space
    asc, dsc = fi.ascent, fi.descent
    n = 0
    for w in words:
        r = w.rect
        h = r.height
        if h <= 0.5 or r.width <= 0.5:
            continue
        size = h / max(asc - dsc, 0.1)
        natural = text_width(w.text, fi, size)
        hscale = r.width / natural if natural > 0 else 1.0
        hscale = max(0.1, min(hscale, 10.0))
        baseline_scene = r.y1 + dsc * size  # descent is negative
        x, y = inv.apply(r.x0, baseline_scene)
        import math

        angle = -math.degrees(math.atan2(inv.b, inv.a))
        if ed.append_text(x, y, w.text, name, fi, size * inv.expansion(), Color("DeviceGray", (0.0,)), rotation=angle, hscale=hscale, render_mode=3):
            n += 1
    if n:
        doc.apply_content_edit(index, ed.build(), "Recognize text (OCR)")
    return n


def page_has_text(doc, index: int) -> bool:
    return bool(doc.page_text(index).strip())
