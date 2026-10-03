"""Grouping into form XObjects, ungrouping, and editing inside forms."""

import pymupdf
import pytest

from pdfeditor.core.content.writer import ContentEditor
from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Matrix


def render_bytes(doc, index=0):
    pix = doc.render(index, 1.0)
    return bytes(pix.samples)


def colour_bbox(pix, pred):
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            if pred(pix.pixel(x, y)):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None


@pytest.fixture
def doc(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, "<<>>")
    pdf.update_stream(xref, b"1 0 0 rg 20 20 40 20 re f 0 0 1 rg 100 20 40 20 re f 0 1 0 rg 200 150 30 30 re f")
    page.set_contents(xref)
    page.insert_text((20, 100), "label", fontsize=12)
    p = str(tmp_path / "g.pdf")
    pdf.save(p)
    pdf.close()
    return Document(p)


def test_group_and_ungroup_roundtrip(doc):
    before = render_bytes(doc)
    pc = doc.content(0)
    ids = [o.id for o in pc.objects if o.kind == "path"][:2]  # red + blue
    doc.group_objects(0, (), ids)
    pc2 = doc.content(0)
    forms = [o for o in pc2.objects if o.kind == "form"]
    assert len(forms) == 1 and forms[0].xref > 0
    assert sum(1 for o in pc2.objects if o.kind == "path") == 1  # only the green one stays inline
    assert render_bytes(doc) == before  # pixel-identical
    bb = forms[0].bbox
    assert bb.x0 <= 20 and bb.x1 >= 140 and bb.y0 <= 20 and bb.y1 >= 40
    # the group moves as one
    ed = ContentEditor(pc2)
    ed.transform([forms[0].id], Matrix.translation(0, 50))
    doc.apply_content_edit(0, ed.build(), "Move group")
    pix = doc.render(0, 1.0)
    assert colour_bbox(pix, lambda c: c[0] > 200 and c[1] < 60) == (20, 110, 60, 130)
    # ungroup brings the objects back inline at the moved position
    pc3 = doc.content(0)
    form = [o for o in pc3.objects if o.kind == "form"][0]
    doc.ungroup_object(0, (), form.id)
    pc4 = doc.content(0)
    assert not [o for o in pc4.objects if o.kind == "form"]
    assert sum(1 for o in pc4.objects if o.kind == "path") == 3
    assert colour_bbox(doc.render(0, 1.0), lambda c: c[0] > 200 and c[1] < 60) == (20, 110, 60, 130)
    for _ in range(3):
        doc.undo_stack.undo()
    assert render_bytes(doc) == before


def test_edit_inside_form(doc):
    pc = doc.content(0)
    ids = [o.id for o in pc.objects if o.kind == "path"][:2]
    doc.group_objects(0, (), ids)
    form = [o for o in doc.content(0).objects if o.kind == "form"][0]
    path = ((form.xref, form.form_matrix * form.state.ctm),)
    inner = doc.content(0, path)
    kinds = [o.kind for o in inner.objects]
    assert kinds == ["path", "path"]
    red = [o for o in inner.objects if o.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    assert (red.bbox.x0, red.bbox.y0) == (20, 20)  # device-space bbox through the base matrix
    assert inner.objects[0].state.clip_bbox is not None
    ed = ContentEditor(inner)
    ed.transform([red.id], Matrix.translation(0, 100))
    doc.apply_content_edit(0, ed.build(), "Move inside group", path)
    assert doc.undo_stack.undo_label == "Move inside group"
    pix = doc.render(0, 1.0)
    assert colour_bbox(pix, lambda c: c[0] > 200 and c[1] < 60) == (20, 60, 60, 80)
    # blue stayed, group object still there
    assert colour_bbox(pix, lambda c: c[2] > 200 and c[0] < 60) == (100, 160, 140, 180)
    assert [o.kind for o in doc.content(0).objects if o.kind == "form"] == ["form"]
    # add a new object inside the form
    inner = doc.content(0, path)
    ed = ContentEditor(inner)
    from pdfeditor.core.content.model import Color

    ed.append_path([[("m", 150, 150), ("l", 170, 150), ("l", 170, 170), ("h",)]], fill_color=Color("DeviceRGB", (1, 0, 1)))
    doc.apply_content_edit(0, ed.build(), "Add inside", path)
    assert len(doc.content(0, path).objects) == 3
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert colour_bbox(doc.render(0, 1.0), lambda c: c[0] > 200 and c[1] < 60) == (20, 160, 60, 180)


def test_nested_group_and_base_matrix(doc):
    pc = doc.content(0)
    doc.group_objects(0, (), [o.id for o in pc.objects if o.kind == "path"][:2])
    form = [o for o in doc.content(0).objects if o.kind == "form"][0]
    ed = ContentEditor(doc.content(0))
    ed.transform([form.id], Matrix.scale(2, 2) * Matrix.translation(-20, -20))  # scale about origin then shift
    doc.apply_content_edit(0, ed.build(), "Scale group")
    form = [o for o in doc.content(0).objects if o.kind == "form"][0]
    path = ((form.xref, form.form_matrix * form.state.ctm),)
    inner = doc.content(0, path)
    red = [o for o in inner.objects if o.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    assert abs(red.bbox.x0 - 20) < 1e-6 and abs(red.bbox.x1 - 100) < 1e-6  # (20..60)*2 - 20
    # group inside the group
    doc.group_objects(0, path, [red.id])
    inner2 = doc.content(0, path)
    assert [o.kind for o in inner2.objects] == ["path", "form"]


def test_ungroup_foreign_form_renames_conflicting_resources(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_font(fontname="helv")  # page has /helv = Helvetica
    # a form with its own /helv that is actually Courier, plus text drawn with it
    cour = page.insert_font(fontname="cour")
    fx = pdf.get_new_xref()
    pdf.update_object(fx, f"<< /Type /XObject /Subtype /Form /BBox [0 0 300 200] /Resources << /Font << /helv {cour} 0 R >> >> >>")
    pdf.update_stream(fx, b"BT /helv 14 Tf 20 100 Td (inside) Tj ET")
    res = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
    pdf.xref_set_key(res, "XObject/Fm1", f"{fx} 0 R")
    cx = pdf.get_new_xref()
    pdf.update_object(cx, "<<>>")
    pdf.update_stream(cx, b"BT /helv 14 Tf 20 150 Td (outside) Tj ET q /Fm1 Do Q")
    page.set_contents(cx)
    p = str(tmp_path / "f.pdf")
    pdf.save(p)
    pdf.close()
    doc = Document(p)
    before = render_bytes(doc)
    form = [o for o in doc.content(0).objects if o.kind == "form"][0]
    doc.ungroup_object(0, (), form.id)
    assert render_bytes(doc) == before
    runs = [o for o in doc.content(0).objects if o.kind == "text"]
    fonts = {r.text: r.font for r in runs}
    assert fonts["outside"] == "helv" and fonts["inside"] != "helv"
    assert runs[1].font_info.base_font.lower().startswith("courier")
