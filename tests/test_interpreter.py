from quirewright.core.content.interpreter import interpret
from quirewright.core.content.model import PathObject, TextRun, XObjectRef
from quirewright.core.geometry import Matrix

SAMPLE = b"""q 1 0 0 rg 10 10 m 50 10 l 50 50 l h f Q
q 2 0 0 2 100 100 cm 0 0 1 RG 3 w 0 0 m 10 10 l S Q
BT /F1 12 Tf 72 700 Td (Hello World) Tj 0 -14 Td [(Kern) -250 (ed)] TJ ET
q 50 0 0 30 200 200 cm /Im1 Do Q
0 0 100 100 re W n 0 g 20 20 10 10 re f
"""


def test_objects_and_spans():
    pc = interpret(SAMPLE)
    kinds = [o.kind for o in pc.objects]
    assert kinds == ["path", "path", "text", "text", "image", "clip", "path"]
    p0 = pc.objects[0]
    assert SAMPLE[p0.span[0]:p0.span[1]] == b"10 10 m 50 10 l 50 50 l h f"
    assert p0.wrapper_span == (0, 40)
    assert SAMPLE[p0.wrapper_span[0]:p0.wrapper_span[1]].startswith(b"q") and SAMPLE[p0.wrapper_span[1]-1:p0.wrapper_span[1]] == b"Q"
    assert p0.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)
    assert p0.bbox.x0 == 10 and p0.bbox.y1 == 50


def test_state_restored_after_Q_without_aliasing():
    pc = interpret(SAMPLE)
    p0 = pc.objects[0]
    # base state is the state outside the wrapper and must be untouched by later ops
    assert p0.base_state.ctm == Matrix()
    assert p0.base_state.line_width == 1.0
    assert p0.base_state.stroke_color.to_rgb() == (0.0, 0.0, 0.0)
    p1 = pc.objects[1]
    assert p1.state.ctm == Matrix(2, 0, 0, 2, 100, 100)
    assert p1.base_state.ctm == Matrix()
    assert p1.state.line_width == 3.0


def test_text_runs():
    pc = interpret(SAMPLE)
    runs = [o for o in pc.objects if isinstance(o, TextRun)]
    assert [r.text for r in runs] == ["Hello World", "Kerned"]
    assert runs[0].tm == Matrix(1, 0, 0, 1, 72, 700)
    assert runs[1].tm == Matrix(1, 0, 0, 1, 72, 686)
    assert runs[0].state.font == "F1" and runs[0].state.font_size == 12
    assert len(pc.blocks) == 1 and len(pc.blocks[0].items) == 2
    assert runs[0].bbox.x0 == 72 and runs[0].bbox.x1 > 100


def test_image_bbox_and_clip():
    pc = interpret(SAMPLE)
    img = pc.objects[4]
    assert isinstance(img, XObjectRef)
    assert (img.bbox.x0, img.bbox.y0, img.bbox.x1, img.bbox.y1) == (200, 200, 250, 230)
    last = pc.objects[6]
    assert last.state.clip_bbox is not None
    assert last.visible_bbox.x1 == 30


def test_curves_and_rect_conversion():
    pc = interpret(b"0 0 m 10 10 20 10 30 0 c 40 0 50 10 v 60 10 70 0 y h S 5 5 2 2 re f")
    p = pc.objects[0]
    assert isinstance(p, PathObject)
    assert p.subpaths[0][0] == ("m", 0, 0)
    assert p.subpaths[0][1][0] == "c"
    assert p.subpaths[0][2] == ("c", 30, 0, 40, 0, 50, 10)  # v: first control = current point
    assert p.subpaths[0][3] == ("c", 60, 10, 70, 0, 70, 0)  # y: second control = end point
    assert p.subpaths[0][4] == ("h",)
    r = pc.objects[1]
    assert len(r.subpaths[0]) == 5 and r.subpaths[0][-1] == ("h",)


def test_impure_wrapper_not_owned():
    pc = interpret(b"q /P <</MCID 1>> BDC 0 0 10 10 re f EMC Q")
    assert pc.objects[0].wrapper_span is None


def test_no_paint_path_is_dropped():
    pc = interpret(b"0 0 10 10 re n 1 g")
    assert pc.objects == []


def test_text_outside_bt_tolerated():
    pc = interpret(b"/F1 10 Tf (x) Tj")
    assert len(pc.objects) == 1 and pc.objects[0].kind == "text"
