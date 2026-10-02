from pdfeditor.core.content.interpreter import interpret
from pdfeditor.core.content.model import Color
from pdfeditor.core.content.writer import ContentEditor, fmt, fmt_string
from pdfeditor.core.geometry import Matrix

SAMPLE = b"""q 1 0 0 rg 10 10 m 50 10 l 50 50 l h f Q
q 2 0 0 2 100 100 cm 0 0 1 RG 3 w 0 0 m 10 10 l S Q
BT /F1 12 Tf 72 700 Td (Hello World) Tj 0 -14 Td [(Kern) -250 (ed)] TJ ET
q 50 0 0 30 200 200 cm /Im1 Do Q
0 0 100 100 re W n 0 g 20 20 10 10 re f
"""


def reparse(stream: bytes):
    return interpret(stream)


def test_fmt():
    assert fmt(1.0) == b"1"
    assert fmt(0.12345) == b"0.1235"
    assert fmt(-0.00001) == b"0"
    assert fmt_string(b"a(b)") == b"(a\\(b\\))"
    assert fmt_string(b"\x00\x41") == b"<0041>"


def test_move_path_rewrites_points_and_keeps_state():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([0], Matrix.translation(5, -5))
    out = ed.build()
    pc2 = reparse(out)
    p = pc2.objects[0]
    assert p.kind == "path"
    assert (p.bbox.x0, p.bbox.y0, p.bbox.x1, p.bbox.y1) == (15, 5, 55, 45)
    assert p.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)
    # untouched objects keep their bytes
    assert b"0 0 m 10 10 l S" in out
    assert b"(Hello World) Tj" in out


def test_move_path_under_cm_uses_user_space():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([1], Matrix.translation(10, 0))
    pc2 = reparse(ed.build())
    p = pc2.objects[1]
    assert p.state.ctm == Matrix(2, 0, 0, 2, 100, 100)
    assert p.subpaths[0][0] == ("m", 5, 0)  # 10 device units == 5 user units
    assert p.state.line_width == 3.0


def test_scale_path_scales_stroke():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([1], Matrix.scale(2, 2))
    pc2 = reparse(ed.build())
    assert abs(pc2.objects[1].state.line_width - 6.0) < 1e-6


def test_move_image_adjusts_ctm():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([4], Matrix.translation(-100, 20))
    pc2 = reparse(ed.build())
    img = pc2.objects[4]
    assert (img.bbox.x0, img.bbox.y0, img.bbox.x1, img.bbox.y1) == (100, 220, 150, 250)


def test_move_text_run_absolute_positioning():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([2], Matrix.translation(0, 10))
    pc2 = reparse(ed.build())
    runs = [o for o in pc2.objects if o.kind == "text"]
    assert runs[0].tm == Matrix(1, 0, 0, 1, 72, 710)
    assert runs[1].tm == Matrix(1, 0, 0, 1, 72, 686)  # neighbour unaffected
    assert runs[1].text == "Kerned"


def test_edit_text():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    assert ed.set_text(3, "Changed")
    pc2 = reparse(ed.build())
    runs = [o for o in pc2.objects if o.kind == "text"]
    assert [r.text for r in runs] == ["Hello World", "Changed"]


def test_delete_objects():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.delete([0, 2, 4])
    out = ed.build()
    pc2 = reparse(out)
    kinds = [o.kind for o in pc2.objects]
    assert kinds == ["path", "text", "clip", "path"]
    assert b"Hello" not in out and b"/Im1" not in out and b"1 0 0 rg" not in out


def test_delete_clip_path_keeps_clip():
    pc = interpret(b"0 0 50 50 re W f 60 60 5 5 re f")
    ed = ContentEditor(pc)
    ed.delete([0])
    out = ed.build()
    pc2 = reparse(out)
    assert pc2.objects[0].kind == "clip"
    assert pc2.objects[1].state.clip_bbox is not None


def test_style_change_wraps_unowned_object():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.set_style(6, fill_color=Color("DeviceRGB", (0, 1, 0)), stroke=True, stroke_color=Color("DeviceGray", (0.5,)), line_width=2)
    out = ed.build()
    pc2 = reparse(out)
    p = pc2.objects[6]
    assert p.fill and p.stroke
    assert p.state.fill_color.to_rgb() == (0.0, 1.0, 0.0)
    assert p.state.line_width == 2
    assert p.wrapper_span is not None
    assert p.state.clip_bbox is not None  # clip from before still applies


def test_node_edit():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.set_path_geometry(0, [[("m", 0, 0), ("l", 100, 0), ("l", 100, 100), ("h",)]])
    pc2 = reparse(ed.build())
    assert pc2.objects[0].bbox.x1 == 100


def test_text_block_preserves_opaque_ops_and_end_state():
    src = b"BT /F1 10 Tf /Span <</MCID 0>> BDC 0 0 1 rg 10 10 Td (a) Tj EMC 1 0 0 rg (b) Tj 0.5 w ET 0 0 1 1 re f"
    pc = interpret(src)
    ed = ContentEditor(pc)
    ed.transform([0], Matrix.translation(1, 1))
    out = ed.build()
    assert b"BDC" in out and b"EMC" in out
    pc2 = reparse(out)
    runs = [o for o in pc2.objects if o.kind == "text"]
    assert runs[0].state.fill_color.to_rgb() == (0.0, 0.0, 1.0)
    assert runs[1].state.fill_color.to_rgb() == (1.0, 0.0, 0.0)
    assert runs[0].tm == Matrix(1, 0, 0, 1, 11, 11)
    assert runs[1].tm.f == 10 and runs[1].tm.e > 10  # second run keeps its original advanced position
    rect = [o for o in pc2.objects if o.kind == "path"][0]
    assert rect.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)
    assert rect.state.line_width == 0.5


def test_multiple_edits_in_one_block():
    pc = interpret(SAMPLE)
    ed = ContentEditor(pc)
    ed.transform([2, 3], Matrix.translation(3, 0))
    ed.set_text(2, "Hi")
    pc2 = reparse(ed.build())
    runs = [o for o in pc2.objects if o.kind == "text"]
    assert runs[0].text == "Hi" and runs[0].tm.e == 75
    assert runs[1].tm.e == 75
