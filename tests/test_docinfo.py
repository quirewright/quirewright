"""Metadata, security, resources, attachments, outline, decorations, search, export, redaction, annotations."""


import pymupdf
import pytest

from quirewright.core.docinfo import ALL_PERMISSIONS, SecuritySettings, pdf_date_to_datetime
from quirewright.core.document import Document
from quirewright.core.geometry import Matrix, Rect


@pytest.fixture
def doc(tmp_path):
    pdf = pymupdf.open()
    for i in range(3):
        page = pdf.new_page(width=300, height=200)
        page.insert_text((20, 30), f"Hello page {i + 1}", fontsize=12)
        page.insert_text((20, 100), "secret words here", fontsize=12)
    img = tmp_path / "i.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 30, 20), False)
    pix.clear_with(120)
    pix.save(str(img))
    pdf[0].insert_image(pymupdf.Rect(150, 50, 250, 120), filename=str(img))
    p = str(tmp_path / "info.pdf")
    pdf.save(p)
    pdf.close()
    return Document(p)


def test_metadata_roundtrip_and_undo(doc):
    assert doc.metadata()["title"] == ""
    doc.set_metadata({"title": "My Title", "author": "Me", "keywords": "a, b"})
    md = doc.metadata()
    assert md["title"] == "My Title" and md["author"] == "Me" and md["keywords"] == "a, b"
    assert doc.undo_stack.undo_label == "Edit metadata"
    doc.undo_stack.undo()
    assert doc.metadata()["title"] == ""
    info = doc.document_info()
    assert info["pages"] == 3 and info["format"].startswith("PDF")
    assert pdf_date_to_datetime("D:20260102030405Z").year == 2026


def test_security_save_and_remove(doc, tmp_path):
    doc.set_security(SecuritySettings(method="aes256", user_password="pw", owner_password="own", permissions=ALL_PERMISSIONS & ~16))
    assert doc.is_modified
    out = str(tmp_path / "enc.pdf")
    doc.save(out)
    check = pymupdf.open(out)
    assert check.needs_pass and check.authenticate("pw")
    assert not (check.permissions & 16)
    assert check[0].get_text().startswith("Hello")
    # the document stays usable after saving encrypted
    assert doc.page_count == 3 and doc.security_info()["encrypted"]
    doc.set_security(SecuritySettings(method="none"))
    out2 = str(tmp_path / "plain.pdf")
    doc.save(out2)
    assert not pymupdf.open(out2).needs_pass


def test_images_and_fonts(doc, tmp_path):
    imgs = doc.list_images()
    assert len(imgs) == 1 and imgs[0].width == 30 and imgs[0].pages == [0]
    ext, data = doc.extract_image(imgs[0].xref)
    assert ext in ("png", "jpg", "jpeg") and len(data) > 50
    fonts = doc.list_fonts()
    assert fonts and fonts[0].base_font.lower().startswith("helvetica")
    assert fonts[0].pages == [0, 1, 2]
    with pytest.raises(ValueError):
        doc.extract_font(fonts[0].xref)  # base-14, not embedded


def test_attachments(doc, tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n")
    assert doc.attachments() == []
    doc.add_attachment(str(f), "table")
    atts = doc.attachments()
    assert len(atts) == 1 and atts[0].filename == "data.csv" and atts[0].description == "table"
    assert doc.extract_attachment(atts[0].name) == b"a,b\n1,2\n"
    doc.add_attachment(str(f))
    assert len(doc.attachments()) == 2 and doc.attachments()[1].name == "data-1.csv"
    doc.delete_attachment(atts[0].name)
    assert len(doc.attachments()) == 1
    doc.undo_stack.undo()
    assert len(doc.attachments()) == 2


def test_outline(doc):
    from quirewright.core.docinfo import OutlineItem

    assert doc.outline() == []
    doc.set_outline([OutlineItem(1, "Intro", 1), OutlineItem(2, "Detail", 2), OutlineItem(1, "End", 3)])
    ol = doc.outline()
    assert [(o.level, o.title, o.page) for o in ol] == [(1, "Intro", 1), (2, "Detail", 2), (1, "End", 3)]
    doc.undo_stack.undo()
    assert doc.outline() == []


def test_page_numbers_and_watermark(doc):
    doc.add_page_numbers(range(3), position="bottom-right", fmt="Page {n} of {total}", start=1)
    assert "Page 2 of 3" in doc.page_text(1)
    doc.rotate_pages([2], 90)
    doc.add_watermark([2], "DRAFT", opacity=0.3)
    assert "DRAFT" in doc.page_text(2)
    hits = doc.search_page(2, "DRAFT")
    assert hits and 0 < hits[0].x0 < doc.page_rect(2).width


def test_search_and_words(doc):
    hits = doc.search("secret")
    assert len(hits) == 3 and hits[0][0] == 0
    r = hits[1][1]
    assert 15 < r.x0 < 25 and r.width > 20
    words = doc.words_in_rect(1, Rect(10, 85, 70, 105))
    assert 1 <= len(words) <= 2


def test_export_and_optimize(doc, tmp_path):
    png = str(tmp_path / "p.png")
    doc.export_page_image(0, png, dpi=72)
    assert pymupdf.Pixmap(png).width == 300
    svg = str(tmp_path / "p.svg")
    doc.export_page_image(0, svg)
    assert open(svg).read().startswith("<svg")
    txt = str(tmp_path / "t.txt")
    doc.export_text(txt)
    assert "Hello page 3" in open(txt).read()
    opt = str(tmp_path / "small.pdf")
    size = doc.save_optimized(opt)
    assert size > 0 and pymupdf.open(opt).page_count == 3


def test_redact_and_crop_scene(doc):
    doc.redact_area(1, Rect(10, 85, 200, 110))
    assert "secret" not in doc.page_text(1)
    assert "Hello page 2" in doc.page_text(1)
    doc.undo_stack.undo()
    assert "secret" in doc.page_text(1)
    doc.set_cropbox_scene(0, Rect(0, 50, 300, 200))
    assert doc.page_rect(0).height == 150
    assert "Hello" not in doc.page_text(0)  # top text cropped away


def test_crop_margins_top_left_origin(doc):
    doc.set_cropbox_margins([0], 0, 50, 0, 0)
    assert "Hello" not in doc.page_text(0) and "secret" in doc.page_text(0)


def test_annotations(doc):
    words = doc.words_in_rect(0, Rect(10, 85, 200, 110))
    doc.add_markup(0, "highlight", words)
    doc.add_note(0, (250, 30), "Check this", author="Reviewer")
    ann = doc.annotations(0)
    assert [a.type_name for a in ann] == ["Highlight", "Text note"]
    note = ann[1]
    assert note.contents == "Check this" and note.author == "Reviewer"
    doc.update_annotation(0, note.xref, contents="Done", color=(0, 1, 0))
    assert doc.annotations(0)[1].contents == "Done"
    doc.transform_annotations(0, [note.xref], Matrix.translation(-100, 0))
    moved = doc.annotations(0)[1]
    assert abs(moved.rect.x0 - (note.rect.x0 - 100)) < 0.01
    doc.delete_annotations(0, [ann[0].xref])
    assert [a.type_name for a in doc.annotations(0)] == ["Text note"]
    doc.flatten()
    assert doc.annotations(0) == []
    for _ in range(5):
        doc.undo_stack.undo()
    assert len(doc.annotations(0)) == 1


def test_page_labels(doc):
    assert doc.page_label_rules() == []
    doc.set_page_label_rules([{"startpage": 0, "style": "r", "prefix": "", "firstpagenum": 1}, {"startpage": 2, "style": "D", "prefix": "A-", "firstpagenum": 1}])
    assert [doc.page_label(i) for i in range(3)] == ["i", "ii", "A-1"]
    assert doc.page_label_rules()[1]["prefix"] == "A-"
    doc.set_page_label_rules([])
    assert [doc.page_label(i) for i in range(3)] == ["1", "2", "3"]
    doc.undo_stack.undo()
    assert doc.page_label(0) == "i"
