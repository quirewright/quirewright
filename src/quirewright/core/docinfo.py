"""Document-level features: metadata, security, resources, attachments,
outline, page decorations, search, export, redaction and optimisation.

Implemented as a mixin for :class:`quirewright.core.document.Document`.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pymupdf

from quirewright.core.commands import Command
from quirewright.core.geometry import Rect

METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")

PERMISSIONS = {
    "print": pymupdf.PDF_PERM_PRINT,
    "print_hq": pymupdf.PDF_PERM_PRINT_HQ,
    "copy": pymupdf.PDF_PERM_COPY,
    "modify": pymupdf.PDF_PERM_MODIFY,
    "annotate": pymupdf.PDF_PERM_ANNOTATE,
    "form": pymupdf.PDF_PERM_FORM,
    "accessibility": pymupdf.PDF_PERM_ACCESSIBILITY,
    "assemble": pymupdf.PDF_PERM_ASSEMBLE,
}
ALL_PERMISSIONS = sum(PERMISSIONS.values())


@dataclass
class SecuritySettings:
    """Encryption to apply at the next save. ``None`` method keeps the file as is."""

    method: str = "keep"  # "keep", "none", "aes256", "aes128", "rc4_128"
    user_password: str = ""
    owner_password: str = ""
    permissions: int = ALL_PERMISSIONS

    def to_save_args(self) -> dict:
        table = {
            "keep": pymupdf.PDF_ENCRYPT_KEEP,
            "none": pymupdf.PDF_ENCRYPT_NONE,
            "aes256": pymupdf.PDF_ENCRYPT_AES_256,
            "aes128": pymupdf.PDF_ENCRYPT_AES_128,
            "rc4_128": pymupdf.PDF_ENCRYPT_RC4_128,
        }
        enc = table.get(self.method, pymupdf.PDF_ENCRYPT_KEEP)
        args: dict[str, Any] = {"encryption": enc}
        if enc not in (pymupdf.PDF_ENCRYPT_KEEP, pymupdf.PDF_ENCRYPT_NONE):
            args["user_pw"] = self.user_password or None
            args["owner_pw"] = self.owner_password or self.user_password or None
            args["permissions"] = self.permissions
        return args


@dataclass
class SecurityCommand(Command):
    label: str
    old: SecuritySettings
    new: SecuritySettings

    def redo(self, doc) -> None:
        doc.security = self.new
        doc._emit("security", None)

    def undo(self, doc) -> None:
        doc.security = self.old
        doc._emit("security", None)


@dataclass
class ImageInfo:
    xref: int
    name: str
    width: int
    height: int
    bpc: int
    colorspace: str
    pages: list[int] = field(default_factory=list)
    size: int = 0
    ext: str = ""


@dataclass
class FontResourceInfo:
    xref: int
    name: str
    base_font: str
    subtype: str
    encoding: str
    embedded: bool
    ext: str
    pages: list[int] = field(default_factory=list)


@dataclass
class AttachmentInfo:
    name: str
    filename: str
    description: str
    size: int
    modified: str = ""


@dataclass
class OutlineItem:
    level: int
    title: str
    page: int  # 1-based, 0 = no destination


def pdf_date_to_datetime(value: str) -> _dt.datetime | None:
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", value or "")
    if not m:
        return None
    parts = [int(g) if g else 1 for g in m.groups()[:3]] + [int(g) if g else 0 for g in m.groups()[3:]]
    try:
        return _dt.datetime(*parts)
    except ValueError:
        return None


def datetime_to_pdf_date(dt: _dt.datetime) -> str:
    return dt.strftime("D:%Y%m%d%H%M%S")


class DocInfoMixin:
    security: SecuritySettings

    # -- metadata ------------------------------------------------------------------
    def metadata(self) -> dict[str, str]:
        md = self.pdf.metadata or {}
        return {k: (md.get(k) or "") for k in METADATA_KEYS}

    def document_info(self) -> dict[str, Any]:
        md = self.pdf.metadata or {}
        size = 0
        if self.path and os.path.exists(self.path):
            size = os.path.getsize(self.path)
        return {
            "format": md.get("format", ""),
            "encryption": md.get("encryption") or "",
            "pages": self.pdf.page_count,
            "file_size": size,
            "has_xml_metadata": bool(self.pdf.xref_xml_metadata()),
            "is_form": bool(self.pdf.is_form_pdf),
            "permissions": int(self.pdf.permissions),
        }

    def set_metadata(self, values: dict[str, str]) -> None:
        current = self.metadata()
        new = dict(current)
        new.update({k: v for k, v in values.items() if k in METADATA_KEYS})
        if new == current:
            return

        def action(doc) -> None:
            doc.pdf.set_metadata(new)

        self._structure_op("Edit metadata", action)

    # -- security --------------------------------------------------------------------
    def security_info(self) -> dict[str, Any]:
        md = self.pdf.metadata or {}
        perms = int(self.pdf.permissions)
        return {
            "encrypted": bool(md.get("encryption")),
            "method": md.get("encryption") or "",
            "permissions": {name: bool(perms & bit) for name, bit in PERMISSIONS.items()},
            "pending": self.security,
        }

    def set_security(self, settings: SecuritySettings) -> None:
        self.undo_stack.push(SecurityCommand("Change security", self.security, settings))

    # -- resources -------------------------------------------------------------------
    def list_images(self) -> list[ImageInfo]:
        found: dict[int, ImageInfo] = {}
        for i in range(self.pdf.page_count):
            try:
                entries = self.pdf[i].get_images(full=True)
            except Exception:
                continue
            for e in entries:
                xref = e[0]
                if xref in found:
                    found[xref].pages.append(i)
                    continue
                info = ImageInfo(xref=xref, name=e[7], width=e[2], height=e[3], bpc=e[4], colorspace=e[5], pages=[i])
                try:
                    info.size = int(self.pdf.xref_get_key(xref, "Length")[1] or 0)
                except Exception:
                    info.size = 0
                found[xref] = info
        return list(found.values())

    def extract_image(self, xref: int) -> tuple[str, bytes]:
        info = self.pdf.extract_image(xref)
        if not info:
            raise ValueError("not an image")
        ext = info.get("ext", "png")
        data = info.get("image", b"")
        if info.get("smask") or ext not in ("png", "jpg", "jpeg", "jpx", "gif", "bmp", "tif", "tiff", "pnm", "pam"):
            pix = pymupdf.Pixmap(self.pdf, xref)
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            data = pix.tobytes("png")
            ext = "png"
        return ext, data

    def image_pixmap_bytes(self, xref: int, max_px: int = 256) -> bytes | None:
        try:
            pix = pymupdf.Pixmap(self.pdf, xref)
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            scale = min(1.0, max_px / max(pix.width, pix.height, 1))
            if scale < 1.0:
                pix = pymupdf.Pixmap(pix, pymupdf.Matrix(scale, scale)) if hasattr(pymupdf.Pixmap, "__init__") else pix
            return pix.tobytes("png")
        except Exception:
            return None

    def list_fonts(self) -> list[FontResourceInfo]:
        found: dict[int, FontResourceInfo] = {}
        for i in range(self.pdf.page_count):
            try:
                entries = self.pdf[i].get_fonts(full=True)
            except Exception:
                continue
            for e in entries:
                xref, ext, subtype, base, name, enc = e[0], e[1], e[2], e[3], e[4], e[5]
                if xref in found:
                    if i not in found[xref].pages:
                        found[xref].pages.append(i)
                    continue
                found[xref] = FontResourceInfo(
                    xref=xref, name=name, base_font=base, subtype=subtype, encoding=enc,
                    embedded=ext not in ("n/a", ""), ext=ext, pages=[i],
                )
        return list(found.values())

    def extract_font(self, xref: int) -> tuple[str, str, bytes]:
        name, ext, _subtype, buf = self.pdf.extract_font(xref)
        if not buf:
            raise ValueError("font is not embedded")
        return name, ext, buf

    # -- attachments -----------------------------------------------------------------
    def attachments(self) -> list[AttachmentInfo]:
        out: list[AttachmentInfo] = []
        try:
            names = self.pdf.embfile_names()
        except Exception:
            return out
        for n in names:
            try:
                info = self.pdf.embfile_info(n)
            except Exception:
                continue
            out.append(AttachmentInfo(
                name=n, filename=info.get("filename") or n, description=info.get("description") or "",
                size=int(info.get("size") or info.get("length") or 0), modified=info.get("modDate") or "",
            ))
        return out

    def add_attachment(self, path: str, description: str = "") -> None:
        data = open(path, "rb").read()
        base = os.path.basename(path)
        name = base
        existing = {a.name for a in self.attachments()}
        k = 1
        while name in existing:
            stem, ext = os.path.splitext(base)
            name = f"{stem}-{k}{ext}"
            k += 1

        def action(doc) -> None:
            doc.pdf.embfile_add(name, data, filename=base, ufilename=base, desc=description)

        self._structure_op("Attach file", action)

    def extract_attachment(self, name: str) -> bytes:
        return self.pdf.embfile_get(name)

    def delete_attachment(self, name: str) -> None:
        def action(doc) -> None:
            doc.pdf.embfile_del(name)

        self._structure_op("Remove attachment", action)

    # -- outline ---------------------------------------------------------------------
    def outline(self) -> list[OutlineItem]:
        try:
            toc = self.pdf.get_toc(simple=True)
        except Exception:
            return []
        return [OutlineItem(level=int(t[0]), title=str(t[1]), page=int(t[2])) for t in toc]

    def set_outline(self, items: Sequence[OutlineItem], label: str = "Edit bookmarks") -> None:
        toc = [[max(1, it.level), it.title, it.page if it.page > 0 else -1] for it in items]
        # levels may only increase by one at a time
        fixed: list[list] = []
        prev = 0
        for lvl, title, page in toc:
            lvl = min(lvl, prev + 1) if prev else 1
            fixed.append([lvl, title, page])
            prev = lvl

        def action(doc) -> None:
            doc.pdf.set_toc(fixed)

        self._structure_op(label, action)

    # -- page labels -----------------------------------------------------------------
    def page_label_rules(self) -> list[dict]:
        try:
            return list(self.pdf.get_page_labels())
        except Exception:
            return []

    def set_page_label_rules(self, rules: list[dict]) -> None:
        """``rules``: list of {startpage, prefix, style, firstpagenum}; empty list removes labels."""
        clean = []
        for r in sorted(rules, key=lambda r: int(r.get("startpage", 0))):
            clean.append({
                "startpage": int(r.get("startpage", 0)), "prefix": str(r.get("prefix", "") or ""),
                "style": str(r.get("style", "D") or ""), "firstpagenum": int(r.get("firstpagenum", 1)),
            })

        def action(doc) -> None:
            doc.pdf.set_page_labels(clean)

        self._structure_op("Edit page labels", action)

    # -- page decorations ------------------------------------------------------------
    def add_page_numbers(
        self, pages: Iterable[int], position: str = "bottom-center", fmt: str = "{n}", start: int = 1,
        fontsize: float = 10, margin: float = 28, fontname: str = "helv", color=(0, 0, 0),
    ) -> None:
        idx = list(pages)

        def action(doc) -> None:
            for k, i in enumerate(idx):
                page = doc.pdf[i]
                text = fmt.replace("{n}", str(start + k)).replace("{total}", str(len(idx))).replace("{page}", str(i + 1)).replace("{pages}", str(doc.pdf.page_count))
                _place_text(page, text, position, fontsize, margin, fontname, color, 1.0, 0)

        self._structure_op("Add page numbers", action)

    def add_watermark(
        self, pages: Iterable[int], text: str, fontsize: float = 48, color=(0.6, 0.6, 0.6), opacity: float = 0.3,
        rotation: int = 45, fontname: str = "hebo",
    ) -> None:
        idx = list(pages)

        def action(doc) -> None:
            for i in idx:
                page = doc.pdf[i]
                _place_text(page, text, "center", fontsize, 0, fontname, color, opacity, rotation)

        self._structure_op("Add watermark", action)

    # -- search ------------------------------------------------------------------------
    def search_page(self, index: int, text: str, case_sensitive: bool = False) -> list[Rect]:
        if not text:
            return []
        page = self.pdf[index]
        flags = 0
        try:
            if not case_sensitive:
                flags |= pymupdf.TEXT_DEHYPHENATE | pymupdf.TEXT_IGNORECASE if hasattr(pymupdf, "TEXT_IGNORECASE") else 0
            hits = page.search_for(text, flags=flags) if flags else page.search_for(text)
        except TypeError:
            hits = page.search_for(text)
        rm = page.rotation_matrix
        out = []
        for r in hits:
            rr = pymupdf.Rect(r) * rm
            out.append(Rect.normalized(rr.x0, rr.y0, rr.x1, rr.y1))
        return out

    def search(self, text: str, case_sensitive: bool = False) -> list[tuple[int, Rect]]:
        out: list[tuple[int, Rect]] = []
        for i in range(self.pdf.page_count):
            for r in self.search_page(i, text, case_sensitive):
                out.append((i, r))
        return out

    def words_in_rect(self, index: int, rect_scene: Rect) -> list[Rect]:
        """Word boxes (scene space) intersecting a scene-space rectangle."""
        page = self.pdf[index]
        rm = page.rotation_matrix
        target = pymupdf.Rect(rect_scene.x0, rect_scene.y0, rect_scene.x1, rect_scene.y1)
        out: list[Rect] = []
        for w in page.get_text("words"):
            wr = pymupdf.Rect(w[:4]) * rm
            if wr.intersects(target):
                inter = wr & target
                if inter.width > 0.3 * wr.width or inter.height > 0.5 * wr.height:
                    out.append(Rect.normalized(wr.x0, wr.y0, wr.x1, wr.y1))
        return out

    def page_text(self, index: int) -> str:
        return self.pdf[index].get_text()

    # -- export ------------------------------------------------------------------------
    def export_page_image(self, index: int, path: str, dpi: int = 150, with_annots: bool = True) -> None:
        page = self.pdf[index]
        ext = os.path.splitext(path)[1].lower()
        if ext == ".svg":
            svg = page.get_svg_image(matrix=pymupdf.Matrix(1, 1), text_as_path=False)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            return
        pix = page.get_pixmap(dpi=dpi, annots=with_annots, alpha=False)
        pix.save(path)

    def export_text(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for i in range(self.pdf.page_count):
                fh.write(self.pdf[i].get_text())
                fh.write("\f\n")

    # -- redaction ---------------------------------------------------------------------
    def redact_area(self, index: int, rect_scene: Rect, fill=(0, 0, 0), remove_images: bool = True) -> None:
        def action(doc) -> None:
            page = doc.pdf[index]
            r = pymupdf.Rect(rect_scene.x0, rect_scene.y0, rect_scene.x1, rect_scene.y1) * page.derotation_matrix
            r.normalize()
            page.add_redact_annot(r, fill=fill)
            page.apply_redactions(images=2 if remove_images else 0, graphics=1)

        self._structure_op("Redact area", action)

    # -- crop ------------------------------------------------------------------------------
    def set_cropbox_scene(self, index: int, rect_scene: Rect) -> None:
        def action(doc) -> None:
            page = doc.pdf[index]
            r = pymupdf.Rect(rect_scene.x0, rect_scene.y0, rect_scene.x1, rect_scene.y1) * page.derotation_matrix
            r.normalize()
            # derotation gives coordinates relative to the current cropbox origin
            cb = page.cropbox
            r = pymupdf.Rect(r.x0 + cb.x0, r.y0 + cb.y0, r.x1 + cb.x0, r.y1 + cb.y0) & page.mediabox
            if r.width > 1 and r.height > 1:
                page.set_cropbox(r)

        self._structure_op("Crop page", action)

    # -- flatten / optimise ---------------------------------------------------------------
    def flatten(self, annots: bool = True, widgets: bool = True) -> None:
        def action(doc) -> None:
            doc.pdf.bake(annots=annots, widgets=widgets)

        self._structure_op("Flatten", action)

    def save_optimized(self, path: str, image_quality: int = 70, max_dpi: int = 150) -> int:
        """Write a size-reduced copy; returns the resulting file size in bytes."""
        tmp = pymupdf.open(stream=self.pdf.tobytes(garbage=0, deflate=False), filetype="pdf")
        try:
            try:
                tmp.rewrite_images(dpi_threshold=max_dpi, dpi_target=max_dpi, quality=image_quality, lossy=True, lossless=True)
            except Exception:
                pass
            tmp.save(path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1, **self.security.to_save_args())
        finally:
            tmp.close()
        return os.path.getsize(path)


def _place_text(page, text: str, position: str, fontsize: float, margin: float, fontname: str, color, opacity: float, rotation: int) -> None:
    """Draw ``text`` on the (rotated, visible) page at a named position, upright on screen."""
    width = pymupdf.get_text_length(text, fontname=fontname, fontsize=fontsize)
    rect = page.rect  # rotated/visible page space
    asc = fontsize * 0.8
    if position == "center":
        x = rect.width / 2 - width / 2
        y = rect.height / 2 + asc / 2
    else:
        vert, _, horiz = position.partition("-")
        if horiz == "left":
            x = margin
        elif horiz == "right":
            x = rect.width - margin - width
        else:
            x = rect.width / 2 - width / 2
        y = margin + asc if vert == "top" else rect.height - margin
    # map from rotated page space back to the page's own coordinate system; the
    # text is drawn with rotate=page.rotation so it reads upright on screen
    pt = pymupdf.Point(x, y) * page.derotation_matrix
    kwargs = dict(fontsize=fontsize, fontname=fontname, color=color, fill_opacity=opacity,
                  stroke_opacity=opacity, rotate=page.rotation)
    if rotation:
        # rotate about the centre of the text (computed in visible space, mapped back)
        pivot = pymupdf.Point(x + width / 2, y - asc / 2) * page.derotation_matrix
        kwargs["morph"] = (pivot, pymupdf.Matrix(rotation))
    page.insert_text(pt, text, **kwargs)
