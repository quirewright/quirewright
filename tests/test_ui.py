"""Offscreen smoke tests for the Qt UI."""


import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from pdfeditor.core.geometry import Matrix
from pdfeditor.ui import theme
from pdfeditor.ui.canvas import TOOL_NODE, TOOL_SELECT
from pdfeditor.ui.dialogs import parse_page_ranges


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def pdf_path(tmp_path):
    pdf = pymupdf.open()
    for i in range(3):
        page = pdf.new_page(width=300, height=200)
        xref = pdf.get_new_xref()
        pdf.update_object(xref, "<<>>")
        pdf.update_stream(xref, b"1 0 0 rg 20 30 40 10 re f 0 0 1 RG 2 w 100 100 m 150 150 l S")
        page.set_contents(xref)
        page.insert_text((150, 50), f"Page {i + 1}", fontname="helv", fontsize=14)
    p = str(tmp_path / "ui.pdf")
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def window(app, pdf_path):
    from pdfeditor.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.open_file(pdf_path)
    app.processEvents()
    win.canvas.snap_enabled = False  # these tests drag by exact amounts
    yield win
    win._set_document(None)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_open_builds_overlay(app, window):
    c = window.canvas
    assert window.doc is not None and window.doc.page_count == 3
    kinds = sorted(it.obj.kind for it in c.items_by_id.values())
    assert kinds == ["path", "path", "text"]
    assert window.pages.count() == 3


def test_select_and_move_via_canvas(app, window):
    c = window.canvas
    rect_id = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.fill][0]
    c.select([rect_id])
    assert c.selection == [rect_id]
    assert not c.frame.rect.isNull()
    before = c.items_by_id[rect_id].sceneBoundingRect()
    c.transform_selection(Matrix.translation(10, 5), "Move")
    pump(app)
    after = c.items_by_id[rect_id].sceneBoundingRect()
    assert abs(after.x() - before.x() - 10) < 0.01 and abs(after.y() - before.y() - 5) < 0.01
    assert window.doc.is_modified
    window.undo()
    pump(app)
    assert abs(c.items_by_id[rect_id].sceneBoundingRect().x() - before.x()) < 0.01


def test_scene_to_pdf_matrix_roundtrip(app, window):
    c = window.canvas
    m = c.scene_matrix_to_pdf(Matrix.translation(0, 10))
    # moving down 10 on screen == moving down 10 in PDF space (y up => -10)
    assert abs(m.f + 10) < 1e-9 and abs(m.e) < 1e-9


def test_text_edit_and_properties(app, window):
    c = window.canvas
    tid = [i for i, it in c.items_by_id.items() if it.obj.kind == "text"][0]
    c.select([tid])
    pump(app)
    assert window.properties.text_box.isVisible()
    assert window.properties.text_edit.text() == "Page 1"
    assert c.set_text(tid, "Hello")
    pump(app)
    assert window.doc.pdf[0].get_text().strip() == "Hello"
    assert any(it.obj.kind == "text" and it.obj.text == "Hello" for it in c.items_by_id.values())


def test_inline_text_editor(app, window):
    c = window.canvas
    tid = [i for i, it in c.items_by_id.items() if it.obj.kind == "text"][0]
    c.select([tid])
    c.begin_text_edit(tid)
    assert c.text_proxy is not None
    c.text_proxy.widget().setText("Inline")
    c._end_text_edit(commit=True)
    pump(app)
    assert window.doc.pdf[0].get_text().strip() == "Inline"


def test_node_tool(app, window):
    c = window.canvas
    line_id = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.stroke][0]
    c.select([line_id])
    c.set_tool(TOOL_NODE)
    assert c.node_overlay is not None
    ov = c.node_overlay
    key = (0, 1, 0)  # the 'l' endpoint
    ov.move_point(key, ov.scene_point(150, 100) + QPointF(0, 0))
    from pdfeditor.core.content.writer import ContentEditor

    ed = ContentEditor(window.doc.content(0))
    ed.set_path_geometry(line_id, ov.subpaths)
    window.doc.apply_content_edit(0, ed.build(), "Edit nodes")
    pump(app)
    pc = window.doc.content(0)
    seg = [o for o in pc.objects if o.kind == "path" and o.stroke][0].subpaths[0][1]
    assert abs(seg[1] - 150) < 0.01 and abs(seg[2] - 100) < 0.01
    c.set_tool(TOOL_SELECT)
    assert c.node_overlay is None


def test_page_ops_from_window(app, window):
    window.rotate_pages(90)
    pump(app)
    assert window.doc.page_rotation(0) == 90
    assert window.canvas.page_rect.width() == 200
    window.go_to_page(1)
    window.delete_pages()
    pump(app)
    assert window.doc.page_count == 2
    window.duplicate_pages()
    pump(app)
    assert window.doc.page_count == 3
    window._move_pages_to([0], 3)
    pump(app)
    assert window.doc.page_rotation(2) == 90


def test_zoom_and_dark_mode(app, window):
    c = window.canvas
    c.set_zoom(2.0)
    assert abs(c.zoom - 2.0) < 1e-9
    c.zoom_fit()
    assert 0.1 < c.zoom < 16
    window.toggle_dark(True)
    assert theme.current().dark
    window.toggle_dark(False)
    assert not theme.current().dark


def test_parse_page_ranges():
    assert parse_page_ranges("all", 5) == [0, 1, 2, 3, 4]
    assert parse_page_ranges("1-2, 4", 5) == [0, 1, 3]
    assert parse_page_ranges("4-", 5) == [3, 4]
    assert parse_page_ranges("-2", 5) == [0, 1]
    assert parse_page_ranges("9", 5) == []


def test_mouse_drag_moves_object(app, window):
    from PySide6.QtTest import QTest

    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    rect_id = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.fill][0]
    item = c.items_by_id[rect_id]
    center = item.sceneBoundingRect().center()
    vp = c.viewport()
    p0 = c.mapFromScene(center)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    assert c.selection == [rect_id]
    p1 = p0 + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(40, 20)
    QTest.mouseMove(vp, p0 + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(5, 5))
    QTest.mouseMove(vp, p1)
    assert c.drag is not None and c.drag.moved
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    pump(app)
    moved = c.items_by_id[rect_id].sceneBoundingRect().center()
    assert abs(moved.x() - center.x() - 20) < 0.5 and abs(moved.y() - center.y() - 10) < 0.5
    assert window.doc.undo_stack.undo_label == "Move"


def test_mouse_rubber_band_and_handle_scale(app, window):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    vp = c.viewport()
    # rubber band around everything on the page
    tl = c.mapFromScene(QPointF(-5, -5))
    br = c.mapFromScene(QPointF(305, 205))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, tl)
    QTest.mouseMove(vp, tl + QPoint(10, 10))
    QTest.mouseMove(vp, br)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, br)
    assert len(c.selection) == 3
    # scale with the south-east handle
    rect_id = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.fill][0]
    c.select([rect_id])
    r = c.frame.rect
    se = c.mapFromScene(r.bottomRight())
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, se)
    assert c.drag is not None and c.drag.mode == "scale"
    target = c.mapFromScene(QPointF(r.right() + r.width(), r.bottom() + r.height()))
    QTest.mouseMove(vp, target)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    pump(app)
    r2 = c._selection_rect()
    assert abs(r2.width() - 2 * r.width()) < 0.5
    assert abs(r2.x() - r.x()) < 0.5


def test_double_click_text_opens_editor(app, window):
    from PySide6.QtTest import QTest

    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    tid = [i for i, it in c.items_by_id.items() if it.obj.kind == "text"][0]
    center = c.items_by_id[tid].sceneBoundingRect().center()
    p = c.mapFromScene(center)
    QTest.mouseDClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    assert c.text_proxy is not None and c.text_edit_ids == [tid]
    c._end_text_edit(commit=False)
    assert c.text_proxy is None
