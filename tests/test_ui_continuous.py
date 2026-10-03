"""Continuous (multi-page) view behaviour."""

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdfeditor.ui import theme
from pdfeditor.ui.canvas import PAGE_GAP, TOOL_FIELD, TOOL_RECT


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
        pdf.update_stream(xref, f"{i / 3:.2f} 0 0 rg 20 30 40 20 re f".encode())
        page.set_contents(xref)
        page.insert_text((150, 100), f"Page {i + 1}", fontsize=14)
    p = str(tmp_path / "cont.pdf")
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def window(app, pdf_path):
    from pdfeditor.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    win.act_continuous.setChecked(True)
    win.canvas.continuous = True
    win.open_file(pdf_path)
    app.processEvents()
    win.canvas.snap_enabled = False  # these tests drag by exact amounts
    win.canvas.set_zoom(1.0)
    app.processEvents()
    yield win
    win._set_document(None)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_layout_and_offsets(app, window):
    c = window.canvas
    assert len(c.page_rects) == 3
    assert c.page_rects[1].top() == 200 + PAGE_GAP and c.page_rects[2].top() == 2 * (200 + PAGE_GAP)
    assert c.page_index == 0 and c.page_offset == QPointF(0, 0)
    assert c.layout_rect.height() == 3 * 200 + 2 * PAGE_GAP


def test_click_on_other_page_activates_it(app, window):
    c = window.canvas
    second_top = c.page_rects[1].top()
    # scroll so page 2 is visible, then click its red rectangle
    c.scroll_to_page(1)
    pump(app)
    pos = QPointF(40, second_top + 200 - 40)  # rect at pdf y 30..50 -> scene y 150..170
    QTest.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(pos))
    pump(app)
    assert c.page_index == 1 and window.page_entry.text() == "2"
    assert c.page_offset.y() == second_top
    assert c.selection and c.items_by_id[c.selection[0]].obj.kind == "path"
    # inspector shows page-local coordinates
    assert abs(window.properties.y.value_pt() - 150) < 0.5 and abs(window.properties.x.value_pt() - 20) < 0.5
    # moving it edits page 2, not page 1
    c.nudge(10, 0)
    pump(app)
    assert window.doc.undo_stack.undo_label == "Nudge"
    objs = window.doc.content(1).objects
    assert any(o.kind == "path" and abs(o.bbox.x0 - 30) < 0.01 for o in objs)
    assert all(not (o.kind == "path" and abs(o.bbox.x0 - 30) < 0.01) for o in window.doc.content(0).objects)


def test_scroll_changes_active_page(app, window):
    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    assert c.verticalScrollBar().maximum() > 0
    c.verticalScrollBar().setValue(c.verticalScrollBar().maximum())
    pump(app)
    c._on_scrolled()
    pump(app)
    assert c.page_index == 2 and window.pages.currentRow() == 2
    c.verticalScrollBar().setValue(0)
    pump(app)
    c._on_scrolled()
    pump(app)
    assert c.page_index == 0


def test_create_on_second_page_uses_local_coords(app, window):
    c = window.canvas
    c.scroll_to_page(1)
    pump(app)
    c.set_page(1)
    c.set_tool(f"{TOOL_FIELD}:7")
    top = c.page_rects[1].top()
    vp = c.viewport()
    a, b = c.mapFromScene(QPointF(20, top + 20)), c.mapFromScene(QPointF(140, top + 42))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(vp, a + QPoint(5, 5))
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(app)
    assert window.doc.widgets(0) == []
    w = window.doc.widgets(1)
    assert len(w) == 1 and abs(w[0].rect.y0 - 20) < 0.6 and abs(w[0].rect.x0 - 20) < 0.6
    c.set_tool(TOOL_RECT)
    a, b = c.mapFromScene(QPointF(200, top + 20)), c.mapFromScene(QPointF(260, top + 60))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(vp, a + QPoint(5, 5))
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(app)
    new = window.doc.content(1).objects[-1]
    assert new.kind == "path" and abs(new.bbox.y1 - 180) < 1.0  # scene y 20 -> pdf y 180


def test_single_page_mode_toggle(app, window):
    c = window.canvas
    c.set_page(2)
    window.act_continuous.setChecked(False)
    window._toggle_continuous(False)
    pump(app)
    assert not c.continuous and len(c.page_items) == 1 and c.page_index == 2
    assert c.page_offset == QPointF(0, 0)
    window._toggle_continuous(True)
    pump(app)
    assert c.continuous and len(c.page_items) == 3 and c.page_index == 2
