"""UI tests for creation tools, line text editing and form fields."""

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from quirewright.ui import theme
from quirewright.ui.canvas import TOOL_ELLIPSE, TOOL_FIELD, TOOL_LINE, TOOL_PEN, TOOL_RECT, TOOL_SELECT, TOOL_TEXT


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def pdf_path(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    # a line of text made of three runs with a kerning gap (word split)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, "<<>>")
    pdf.update_stream(xref, b"BT /helv 12 Tf 20 150 Td (Hello) Tj 3 0 Td ( wor) Tj (ld) Tj ET 0 0 1 rg 200 20 50 30 re f")
    page.set_contents(xref)
    page.insert_font(fontname="helv")  # built-in Helvetica as /helv
    p = str(tmp_path / "ui2.pdf")
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def window(app, pdf_path):
    from quirewright.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.open_file(pdf_path)
    app.processEvents()
    win.canvas.snap_enabled = False  # these tests drag by exact amounts
    win.canvas.set_zoom(2.0)
    app.processEvents()
    yield win
    win._set_document(None)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def drag(c, a: QPointF, b: QPointF, mods=Qt.KeyboardModifier.NoModifier):
    vp = c.viewport()
    pa, pb = c.mapFromScene(a), c.mapFromScene(b)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, mods, pa)
    QTest.mouseMove(vp, pa + QPoint(4, 4))
    QTest.mouseMove(vp, pb)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, mods, pb)


def kinds(c):
    return sorted(it.obj.kind for it in c.items_by_id.values())


def test_draw_rect_ellipse_line(app, window):
    c = window.canvas
    n0 = len(c.items_by_id)
    c.set_tool(TOOL_RECT)
    drag(c, QPointF(20, 20), QPointF(80, 60))
    pump(app)
    assert len(c.items_by_id) == n0 + 1
    new = c.items_by_id[c.selection[0]].obj
    assert new.kind == "path" and new.fill and new.stroke
    m = new.state.ctm * c.pdf_to_scene
    pts = [m.apply(seg[1], seg[2]) for seg in new.subpaths[0] if seg[0] != "h"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert abs(min(xs) - 20) < 0.01 and abs(max(xs) - 80) < 0.01 and abs(min(ys) - 20) < 0.01 and abs(max(ys) - 60) < 0.01
    assert window.doc.undo_stack.undo_label == "Draw rectangle"
    c.set_tool(TOOL_ELLIPSE)
    drag(c, QPointF(100, 20), QPointF(140, 60))
    pump(app)
    e = c.items_by_id[c.selection[0]].obj
    assert e.kind == "path" and len(e.subpaths[0]) == 6
    c.set_tool(TOOL_LINE)
    drag(c, QPointF(20, 100), QPointF(120, 100))
    pump(app)
    ln = c.items_by_id[c.selection[0]].obj
    assert ln.kind == "path" and ln.stroke and not ln.fill
    assert len(c.items_by_id) == n0 + 3
    for _ in range(3):
        window.undo()
    pump(app)
    assert len(c.items_by_id) == n0


def test_pen_tool(app, window):
    c = window.canvas
    n0 = len(c.items_by_id)
    c.set_tool(TOOL_PEN)
    vp = c.viewport()
    for pt in (QPointF(30, 30), QPointF(90, 40), QPointF(60, 90)):
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(pt))
    assert len(c.pen_points) == 3 and c.pen_preview is not None
    QTest.keyClick(c, Qt.Key.Key_Return)
    pump(app)
    assert len(c.items_by_id) == n0 + 1
    obj = c.items_by_id[c.selection[0]].obj
    assert obj.kind == "path" and not obj.fill and obj.stroke and len(obj.subpaths[0]) == 3
    # closed shape by clicking the first point
    for pt in (QPointF(150, 30), QPointF(190, 30), QPointF(170, 70), QPointF(150, 30)):
        QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(pt))
    pump(app)
    obj = c.items_by_id[c.selection[0]].obj
    assert obj.fill and obj.subpaths[0][-1] == ("h",)


def test_new_text_via_keyboard(app, window):
    c = window.canvas
    c.draw_style.font = "hebo"
    c.draw_style.font_size = 14
    c.set_tool(TOOL_TEXT)
    QTest.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(40, 100)))
    assert c.text_proxy is not None and c.text_edit_new is not None
    edit = c.text_proxy.widget()
    QTest.keyClicks(edit, "New words")
    assert edit.text() == "New words"
    QTest.keyClick(edit, Qt.Key.Key_Return)
    pump(app)
    assert c.text_proxy is None
    texts = [it.obj for it in c.items_by_id.values() if it.obj.kind == "text"]
    new = [t for t in texts if t.text == "New words"]
    assert len(new) == 1 and new[0].font == "hebo" and abs(new[0].state.font_size - 14) < 1e-6
    assert "New words" in window.doc.pdf[0].get_text()


def test_line_editing_merges_runs(app, window):
    c = window.canvas
    runs = sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "text"), key=lambda r: r.tm.e)
    assert [r.text for r in runs] == ["Hello", " wor", "ld"]
    ids = c.text_line_ids(runs[1].id)
    assert ids == [r.id for r in runs]
    assert c._line_text(ids) == "Hello world"
    c.begin_text_edit(runs[2].id)
    assert c.text_proxy is not None and c.text_proxy.widget().text() == "Hello world"
    c.text_proxy.widget().setText("Goodbye world")
    c._end_text_edit(commit=True)
    pump(app)
    texts = [it.obj.text for it in c.items_by_id.values() if it.obj.kind == "text"]
    assert texts == ["Goodbye world"]
    assert window.doc.pdf[0].get_text().strip() == "Goodbye world"
    window.undo()
    pump(app)
    assert sorted(it.obj.text for it in c.items_by_id.values() if it.obj.kind == "text") == [" wor", "Hello", "ld"]


def test_inline_editor_receives_keys_after_double_click(app, window):
    c = window.canvas
    run = next(it.obj for it in c.items_by_id.values() if it.obj.kind == "text" and it.obj.text == "Hello")
    p = c.mapFromScene(c.items_by_id[run.id].sceneBoundingRect().center())
    QTest.mouseDClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert c.text_proxy is not None
    edit = c.text_proxy.widget()
    assert edit.hasFocus()
    QTest.keyClicks(edit, "Z")
    assert edit.text() == "Z"  # selected-all text replaced by typing
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    assert c.text_proxy is None


def test_form_fields_create_select_move_delete(app, window):
    c = window.canvas
    c.set_tool(f"{TOOL_FIELD}:7")
    drag(c, QPointF(20, 20), QPointF(140, 42))
    pump(app)
    ws = window.doc.widgets(0)
    assert len(ws) == 1 and ws[0].type_name == "Text field"
    assert c.widget_selection == [ws[0].xref]
    assert window.properties.widget_box.isVisible()
    # edit via inspector
    window.properties.w_value.setText("filled in")
    window.properties.w_name.setText("name_field")
    window.properties._apply_widget()
    pump(app)
    w = window.doc.widgets(0)[0]
    assert w.value == "filled in" and w.field_name == "name_field"
    # checkbox with a click (default size)
    c.set_tool(f"{TOOL_FIELD}:2")
    QTest.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(200, 100)))
    pump(app)
    ws = window.doc.widgets(0)
    assert [w.type_name for w in ws] == ["Text field", "Checkbox"]
    assert abs(ws[1].rect.width - 14) < 0.01
    # move the text field with the select tool
    c.set_tool(TOOL_SELECT)
    center = c.widget_items[ws[0].xref].sceneBoundingRect().center()
    drag(c, center, center + QPointF(10, 20))
    pump(app)
    moved = window.doc.widgets(0)[0]
    assert abs(moved.rect.x0 - 30) < 0.6 and abs(moved.rect.y0 - 40) < 0.6
    # delete via keyboard
    c.select_widgets([moved.xref])
    QTest.keyClick(c, Qt.Key.Key_Delete)
    pump(app)
    assert [w.type_name for w in window.doc.widgets(0)] == ["Checkbox"]
    window.undo()
    pump(app)
    assert len(window.doc.widgets(0)) == 2


def test_insert_image(app, window, tmp_path):
    img = tmp_path / "i.png"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.clear_with(200)
    pix.save(str(img))
    c = window.canvas
    c.insert_image(str(img))
    pump(app)
    assert c.selection and c.items_by_id[c.selection[0]].obj.kind == "image"
    bb = c.items_by_id[c.selection[0]].obj.bbox
    assert abs(bb.width / bb.height - 2) < 0.01
