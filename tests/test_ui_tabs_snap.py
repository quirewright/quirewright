"""Document tabs, rulers, guides and snapping."""

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdfeditor.ui import theme
from pdfeditor.ui.canvas import TOOL_RECT, TOOL_SELECT


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


def make_pdf(path, label):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, "<<>>")
    pdf.update_stream(xref, b"1 0 0 rg 20 20 40 20 re f 0 0 1 rg 150 100 40 20 re f")
    page.set_contents(xref)
    page.insert_text((200, 60), label, fontsize=12)
    pdf.save(path)
    pdf.close()
    return str(path)


@pytest.fixture
def two_pdfs(tmp_path):
    return make_pdf(tmp_path / "a.pdf", "Doc A"), make_pdf(tmp_path / "b.pdf", "Doc B")


@pytest.fixture
def window(app):
    from pdfeditor.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    yield win
    for v in list(win.views()):
        win._remove_view(v)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_tabs_open_switch_close(app, window, two_pdfs):
    a, b = two_pdfs
    assert window.tabs.count() == 0 and window.stack.currentIndex() == 0
    window.open_file(a)
    window.open_file(b)
    pump(app)
    assert window.tabs.count() == 2 and window.stack.currentIndex() == 1
    assert window.doc.title == "b.pdf" and window.tabs.tabText(1) == "b.pdf"
    assert window.pages.doc is window.doc
    window.open_file(a)  # already open -> switches
    assert window.tabs.currentIndex() == 0 and window.doc.title == "a.pdf"
    assert window.properties.canvas is window.canvas
    # per-tab tool and zoom state
    window.canvas.set_tool(TOOL_RECT)
    window.canvas.set_zoom(2.0)
    window._cycle_tab(1)
    assert window.doc.title == "b.pdf" and window.canvas.tool == TOOL_SELECT and window.act_tool_select.isChecked()
    window._cycle_tab(1)
    assert window.doc.title == "a.pdf" and window.canvas.tool == TOOL_RECT and window.act_tool_rect.isChecked()
    assert window.zoom_combo.currentText() == "200%"
    # modified marker in the tab title
    window.doc.rotate_pages([0], 90)
    pump(app)
    assert window.tabs.tabText(0).startswith("•")
    window.undo()
    pump(app)
    assert window.tabs.tabText(0) == "a.pdf"
    window.close_tab(0)
    assert window.tabs.count() == 1 and window.doc.title == "b.pdf"
    window.close_document()
    assert window.tabs.count() == 0 and window.stack.currentIndex() == 0 and window.doc is None


def test_guides_and_snapping(app, window, two_pdfs):
    window.open_file(two_pdfs[0])
    pump(app)
    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    # a vertical guide at x = 100 (page-local), via the ruler API
    c.add_guide("v", 100 + c.page_offset.x())
    assert c.page_guides() == [("v", 100.0)] and len(c.guide_items) == 1
    # move the red rect (x 20..60) so that its left edge comes within tolerance of the guide
    red = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    c.select([red])
    center = c.items_by_id[red].sceneBoundingRect().center()
    vp = c.viewport()
    start = c.mapFromScene(center)
    end = c.mapFromScene(center + QPointF(78, 0))  # left edge would land at 98 -> snaps to 100
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(vp, start + QPoint(5, 0))
    QTest.mouseMove(vp, end)
    assert c.smart_items  # alignment line shown while snapped
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    pump(app)
    obj = [o for o in window.doc.content(0).objects if o.kind == "path" and o.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    assert abs(obj.bbox.x0 - 100) < 0.01
    assert not c.smart_items
    # Alt disables snapping (QTest cannot hold modifiers through mouse moves, so check the snap function directly)
    from PySide6.QtCore import QRectF

    red = [i for i, it in c.items_by_id.items() if it.obj.kind == "path" and it.obj.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    rect = c.items_by_id[red].sceneTransform().mapRect(c.items_by_id[red].shape().boundingRect())
    assert c.snap_rect_delta(QRectF(rect), -2.0, 0.0) == (0.0, 0.0)  # pulled back onto the guide
    assert c.snap_rect_delta(QRectF(rect), -2.0, 0.0, Qt.KeyboardModifier.AltModifier) == (-2.0, 0.0)
    c._clear_smart()
    # snapping to another object's edge while drawing a rectangle
    c.set_tool(TOOL_RECT)
    a = c.mapFromScene(QPointF(148.5, 40))  # near the blue rect's left edge x=150
    b = c.mapFromScene(QPointF(200, 70))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(vp, a + QPoint(5, 5))
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(app)
    new = window.doc.content(0).objects[-1]
    pts = [seg[1] for seg in new.subpaths[0] if seg[0] in ("m", "l")]
    assert abs(min(pts) - 150) < 0.01
    # grid snapping
    c.set_tool(TOOL_SELECT)
    c.set_snapping(objects=False, grid=True, grid_size=25)
    c.clear_guides()
    sel = [i for i, it in c.items_by_id.items() if it.obj.kind == "path"][0]
    c.select([sel])
    r = c.items_by_id[sel].sceneBoundingRect()
    start = c.mapFromScene(r.center())
    end = c.mapFromScene(r.center() + QPointF(-9, 6))  # away from the page centre; only the grid is in range
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(vp, start + QPoint(5, 5))
    QTest.mouseMove(vp, end)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    pump(app)
    r2 = c._selection_rect()
    assert abs(r2.left() % 25) < 0.6 or abs(25 - r2.left() % 25) < 0.6


def test_guide_drag_off_page_removes_it(app, window, two_pdfs):
    window.open_file(two_pdfs[0])
    pump(app)
    c = window.canvas
    c.set_zoom(2.0)
    pump(app)
    c.add_guide("h", 50 + c.page_offset.y())
    vp = c.viewport()
    start = c.mapFromScene(QPointF(250, 50 + c.page_offset.y()))
    end = c.mapFromScene(QPointF(250, -30 + c.page_offset.y()))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(vp, start + QPoint(0, -5))
    QTest.mouseMove(vp, end)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    assert c.page_guides() == []


def test_rulers_paint_and_options(app, window, two_pdfs):
    window.open_file(two_pdfs[0])
    pump(app)
    v = window.view
    assert v.hruler.isVisible() and v.vruler.isVisible()
    v.hruler.grab()
    v.vruler.grab()
    window.act_rulers.setChecked(False)
    window._apply_view_option("rulers", False)
    assert not v.hruler.isVisible()
    window.act_grid.setChecked(True)
    window._apply_view_option("grid", True)
    assert v.canvas.grid_item is not None
    window._apply_view_option("grid", False)
    assert v.canvas.grid_item is None
