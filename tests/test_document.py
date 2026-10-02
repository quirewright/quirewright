import os

import pymupdf
import pytest

from pdfeditor.core.content.model import Color
from pdfeditor.core.content.writer import ContentEditor
from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Matrix, Rect


def make_doc(tmp_path, n=3):
    pdf = pymupdf.open()
    for i in range(n):
        page = pdf.new_page(width=300, height=200)
        xref = pdf.get_new_xref()
        pdf.update_object(xref, "<<>>")
        pdf.update_stream(xref, f"1 0 0 rg 20 30 40 10 re f 0 0 1 rg {100 + i * 10} 100 10 10 re f".encode())
        page.set_contents(xref)
        page.insert_text((150, 150), f"Page {i + 1}", fontname="helv", fontsize=14)
    p = str(tmp_path / "test.pdf")
    pdf.save(p)
    pdf.close()
    return p


def red_bbox(pix):
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            r, g, b = pix.pixel(x, y)
            if r > 200 and g < 80 and b < 80:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None


def test_open_parse_and_text(tmp_path):
    doc = Document(make_doc(tmp_path))
    assert doc.page_count == 3
    pc = doc.content(0)
    kinds = [o.kind for o in pc.objects]
    assert kinds.count("path") == 2 and "text" in kinds
    run = [o for o in pc.objects if o.kind == "text"][0]
    assert run.text == "Page 1"
    assert run.font_info is not None and run.font_info.builtin == "helv"


def test_move_object_and_render(tmp_path):
    doc = Document(make_doc(tmp_path))
    before = red_bbox(doc.render(0, 1.0))
    assert before == (20, 160, 60, 170)
    pc = doc.content(0)
    ed = ContentEditor(pc)
    ed.transform([0], Matrix.translation(100, 50))
    doc.apply_content_edit(0, ed.build(), "Move")
    after = red_bbox(doc.render(0, 1.0))
    assert after == (120, 110, 160, 120)
    assert doc.is_modified
    doc.undo_stack.undo()
    assert red_bbox(doc.render(0, 1.0)) == before
    doc.undo_stack.redo()
    assert red_bbox(doc.render(0, 1.0)) == after


def test_edit_text_with_substitute(tmp_path):
    doc = Document(make_doc(tmp_path))
    pc = doc.content(0)
    run = [o for o in pc.objects if o.kind == "text"][0]
    ed = ContentEditor(pc)
    assert ed.set_text(run.id, "Edited")
    doc.apply_content_edit(0, ed.build(), "Edit text")
    assert doc.pdf[0].get_text().strip() == "Edited"


def test_page_ops_and_undo(tmp_path):
    doc = Document(make_doc(tmp_path))
    texts = lambda: [doc.pdf[i].get_text().strip() for i in range(doc.page_count)]  # noqa: E731
    doc.rotate_pages([0], 90)
    assert doc.page_rotation(0) == 90
    doc.move_page(0, 2)
    assert texts() == ["Page 2", "Page 3", "Page 1"]
    doc.delete_pages([1])
    assert texts() == ["Page 2", "Page 1"]
    doc.duplicate_pages([0])
    assert texts() == ["Page 2", "Page 2", "Page 1"]
    doc.insert_blank_page(1, 100, 100)
    assert doc.page_count == 4 and doc.page_rect(1).width == 100
    doc.reverse_pages()
    assert texts()[0] == "Page 1"
    for _ in range(6):
        doc.undo_stack.undo()
    assert texts() == ["Page 1", "Page 2", "Page 3"] and doc.page_rotation(0) == 0
    doc.undo_stack.redo()
    assert doc.page_rotation(0) == 90


def test_move_pages_multi(tmp_path):
    doc = Document(make_doc(tmp_path, 5))
    doc.move_pages([0, 1], 4)
    assert [doc.pdf[i].get_text().strip() for i in range(5)] == ["Page 3", "Page 4", "Page 1", "Page 2", "Page 5"]


def test_insert_from_file_and_extract(tmp_path):
    p1 = make_doc(tmp_path, 2)
    p2 = str(tmp_path / "other.pdf")
    os.rename(make_doc(tmp_path / "x" if False else tmp_path, 1), p2) if False else None
    doc = Document(p1)
    doc.insert_pages_from(p1, 1, 0, 0)
    assert doc.page_count == 3
    out = str(tmp_path / "extract.pdf")
    doc.extract_pages([0, 2], out)
    assert pymupdf.open(out).page_count == 2


def test_crop_and_save(tmp_path):
    p = make_doc(tmp_path)
    doc = Document(p)
    doc.set_cropbox_margins([0], 10, 10, 10, 10)
    assert doc.page_rect(0).width == 280
    out = str(tmp_path / "saved.pdf")
    doc.save(out)
    assert not doc.is_modified and doc.path == out
    re = pymupdf.open(out)
    assert re[0].rect.width == 280
    doc.reset_cropbox([0])
    assert doc.page_rect(0).width == 300


def test_style_change_renders(tmp_path):
    doc = Document(make_doc(tmp_path))
    pc = doc.content(0)
    ed = ContentEditor(pc)
    ed.set_style(0, fill_color=Color("DeviceRGB", (0, 1, 0)))
    doc.apply_content_edit(0, ed.build(), "Colour")
    pix = doc.render(0, 1.0)
    assert pix.pixel(40, 165) == (0, 255, 0)


def test_save_in_place(tmp_path):
    p = make_doc(tmp_path)
    doc = Document(p)
    doc.rotate_pages([0], 90)
    doc.save()
    assert pymupdf.open(p)[0].rotation == 90
