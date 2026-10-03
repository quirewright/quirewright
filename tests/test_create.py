"""Creating new objects: paths, text, images and form fields."""

import pymupdf

from pdfeditor.core.content.model import Color
from pdfeditor.core.content.writer import ContentEditor
from pdfeditor.core.document import Document
from pdfeditor.core.geometry import Matrix, Rect


def make_doc(tmp_path, stream=b"0 0 1 rg 10 10 20 20 re f", rotate=0, n=1):
    pdf = pymupdf.open()
    for _ in range(n):
        page = pdf.new_page(width=300, height=200)
        xref = pdf.get_new_xref()
        pdf.update_object(xref, "<<>>")
        pdf.update_stream(xref, stream)
        page.set_contents(xref)
        page.set_rotation(rotate)
    p = str(tmp_path / "c.pdf")
    pdf.save(p)
    pdf.close()
    return p


def colour_bbox(pix, pred):
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            if pred(pix.pixel(x, y)):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None


def test_append_path_renders_where_expected(tmp_path):
    doc = Document(make_doc(tmp_path))
    ed = ContentEditor(doc.content(0))
    ed.append_path([[("m", 100, 100), ("l", 140, 100), ("l", 140, 120), ("l", 100, 120), ("h",)]],
                   fill_color=Color("DeviceRGB", (1, 0, 0)))
    doc.apply_content_edit(0, ed.build(), "Add rect")
    pix = doc.render(0, 1.0)
    assert colour_bbox(pix, lambda c: c[0] > 200 and c[1] < 60) == (100, 80, 140, 100)
    objs = doc.content(0).objects
    assert objs[-1].kind == "path" and objs[-1].fill and objs[-1].state.fill_color.to_rgb() == (1.0, 0.0, 0.0)


def test_append_under_unbalanced_state(tmp_path):
    # stream ends inside q with a cm and inside BT: appended objects must still land in device space
    stream = b"q 2 0 0 2 0 0 cm 0 0 1 rg 5 5 10 10 re f BT /F1 10 Tf (x) Tj"
    doc = Document(make_doc(tmp_path, stream))
    pc = doc.content(0)
    assert pc.end_depth == 1 and pc.end_in_text
    ed = ContentEditor(pc)
    ed.append_path([[("m", 100, 100), ("l", 140, 100), ("l", 140, 120), ("l", 100, 120), ("h",)]],
                   stroke_color=Color("DeviceRGB", (1, 0, 0)), line_width=2)
    doc.apply_content_edit(0, ed.build(), "Add rect")
    pc2 = doc.content(0)
    assert pc2.end_depth == 0 and not pc2.end_in_text
    new = pc2.objects[-1]
    assert new.kind == "path" and new.stroke
    assert abs(new.bbox.x0 - 99) < 0.01 and abs(new.bbox.x1 - 141) < 0.01  # includes half stroke width
    assert abs(new.state.line_width * new.state.ctm.expansion() - 2.0) < 1e-6


def test_append_text(tmp_path):
    doc = Document(make_doc(tmp_path))
    name, fi = doc.ensure_substitute_font(0, "hebo")
    ed = ContentEditor(doc.content(0))
    assert ed.append_text(50, 150, "Hello", name, fi, 14, Color("DeviceRGB", (0, 0.5, 0)))
    doc.apply_content_edit(0, ed.build(), "Add text")
    assert doc.pdf[0].get_text().strip() == "Hello"
    run = [o for o in doc.content(0).objects if o.kind == "text"][0]
    assert run.text == "Hello" and run.font == "hebo" and run.state.font_size == 14
    assert abs(run.tm.e - 50) < 1e-6 and abs(run.tm.f - 150) < 1e-6


def test_substitute_font_name():
    from pdfeditor.core.fonts import FontInfo

    d = Document()
    assert d.substitute_font_name(FontInfo.fallback("F", "Arial-BoldMT")) == "hebo"
    assert d.substitute_font_name(FontInfo.fallback("F", "TimesNewRoman-Italic")) == "tiit"
    assert d.substitute_font_name(FontInfo.fallback("F", "Symbol")) == "helv"
    assert d.substitute_font_name(None) == "helv"


def test_add_image(tmp_path):
    img = tmp_path / "img.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 10), False)
    pix.clear_with(0)
    for x in range(20):
        for y in range(10):
            pix.set_pixel(x, y, (0, 255, 0))
    pix.save(str(img))
    doc = Document(make_doc(tmp_path))
    doc.add_image(0, Rect(50, 50, 150, 100), str(img))
    pm = doc.render(0, 1.0)
    bb = colour_bbox(pm, lambda c: c[1] > 200 and c[0] < 60)
    assert bb is not None and bb[0] == 50 and bb[2] == 150
    assert doc.content(0).objects[-1].kind == "image"
    doc.undo_stack.undo()
    assert colour_bbox(doc.render(0, 1.0), lambda c: c[1] > 200 and c[0] < 60) is None


def test_widgets_roundtrip(tmp_path):
    doc = Document(make_doc(tmp_path, n=2))
    assert doc.widgets(0) == []
    doc.add_widget(0, 7, Rect(20, 30, 120, 60), value="hi")
    doc.add_widget(0, 2, Rect(150, 30, 170, 50))
    doc.add_widget(1, 3, Rect(20, 30, 120, 60), choices=["a", "b"])
    ws = doc.widgets(0)
    assert [w.type_name for w in ws] == ["Text field", "Checkbox"]
    assert ws[0].field_name == "Text1" and ws[0].value == "hi"
    assert ws[0].rect == Rect(20, 30, 120, 60)
    assert doc.widgets(1)[0].choices == ["a", "b"]
    doc.update_widget(0, ws[0].xref, value="changed", font_size=9, field_name="first")
    w0 = doc.widgets(0)[0]
    assert w0.value == "changed" and w0.font_size == 9 and w0.field_name == "first"
    doc.transform_widgets(0, [w0.xref], Matrix.translation(10, 5))
    assert doc.widgets(0)[0].rect == Rect(30, 35, 130, 65)
    doc.delete_widgets(0, [w0.xref])
    assert [w.type_name for w in doc.widgets(0)] == ["Checkbox"]
    for _ in range(3):
        doc.undo_stack.undo()
    assert doc.widgets(0)[0].value == "hi"


def test_widgets_on_rotated_page(tmp_path):
    doc = Document(make_doc(tmp_path, rotate=90))
    doc.add_widget(0, 7, Rect(20, 30, 120, 60), value="x", fill_color=(1, 1, 0))
    w = doc.widgets(0)[0]
    assert w.rect == Rect(20, 30, 120, 60)  # round-trips through derotation
    pm = doc.render(0, 1.0)
    bb = colour_bbox(pm, lambda c: c[0] > 230 and c[1] > 230 and c[2] < 80)
    assert bb is not None and abs(bb[0] - 20) <= 2 and abs(bb[1] - 30) <= 2


def test_radio_buttons(tmp_path):
    doc = Document(make_doc(tmp_path))
    doc.add_widget(0, 5, Rect(20, 20, 34, 34), name="grp")
    doc.add_widget(0, 5, Rect(60, 20, 74, 34), name="grp")
    ws = doc.widgets(0)
    assert [w.type_name for w in ws] == ["Radio button", "Radio button"]
    assert ws[0].field_name == ws[1].field_name == "grp"
    assert ws[0].on_state != ws[1].on_state
    pix = doc.render(0, 1.0)
    assert any(pix.pixel(x, y) != (255, 255, 255) for x in range(20, 34) for y in range(166, 180))
    doc.update_widget(0, ws[1].xref, value=True)
    assert doc.widgets(0)[1].value not in (False, "Off", "", None)


def test_append_text_block_wraps(tmp_path):
    from pdfeditor.core.content.writer import wrap_text

    doc = Document(make_doc(tmp_path))
    name, fi = doc.ensure_substitute_font(0, "helv")
    lines = wrap_text("The quick brown fox jumps over the lazy dog near the riverbank", fi, 12, 150)
    assert len(lines) >= 3 and all(lines)
    assert " ".join(lines) == "The quick brown fox jumps over the lazy dog near the riverbank"
    assert wrap_text("a\nb", fi, 12, 150) == ["a", "b"]
    ed = ContentEditor(doc.content(0))
    out = ed.append_text_block(20, 180, 150, "The quick brown fox jumps over the lazy dog", name, fi, 12, Color("DeviceGray", (0,)))
    doc.apply_content_edit(0, ed.build(), "Add text box")
    runs = [o for o in doc.content(0).objects if o.kind == "text"]
    assert [r.text for r in runs] == out and len(out) >= 2
    assert all(abs(r.tm.e - 20) < 1e-6 for r in runs)
    assert abs((runs[0].tm.f - runs[1].tm.f) - 14.4) < 1e-6
