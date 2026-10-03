"""Grouping and editing inside groups through the UI."""

import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdfeditor.ui import theme


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def pdf_path(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, "<<>>")
    pdf.update_stream(xref, b"1 0 0 rg 20 20 40 20 re f 0 0 1 rg 100 20 40 20 re f 0 1 0 rg 200 150 30 30 re f")
    page.set_contents(xref)
    p = str(tmp_path / "ug.pdf")
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
    win.canvas.snap_enabled = False
    win.canvas.set_zoom(2.0)
    app.processEvents()
    yield win
    win._set_document(None)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def test_group_enter_edit_exit(app, window):
    c = window.canvas
    paths = sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "path"), key=lambda o: o.bbox.x0)
    c.select([paths[0].id, paths[1].id])
    window.act_group.trigger()
    pump(app)
    groups = [it.obj for it in c.items_by_id.values() if it.obj.kind == "form"]
    assert len(groups) == 1 and c.selection == [groups[0].id]
    assert window.act_enter_group.isEnabled() and window.act_ungroup.isEnabled()
    # enter by double-click
    center = c.items_by_id[groups[0].id].sceneBoundingRect().center()
    QTest.mouseDClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(center))
    pump(app)
    assert c.in_group and len(c.edit_path) == 1 and c.context_items
    assert sorted(it.obj.kind for it in c.items_by_id.values()) == ["path", "path"]  # only the group's members
    # move the red one inside the group
    red = [i for i, it in c.items_by_id.items() if it.obj.state.fill_color.to_rgb() == (1.0, 0.0, 0.0)][0]
    c.select([red])
    c.nudge(0, -100)
    pump(app)
    assert c.in_group  # still inside after the edit
    assert window.doc.undo_stack.undo_label == "Nudge"
    pix = window.doc.render(0, 1.0)
    reds = [(x, y) for y in range(pix.height) for x in range(pix.width) if pix.pixel(x, y)[0] > 200 and pix.pixel(x, y)[1] < 60]
    assert reds and min(p[1] for p in reds) == 60  # moved up by 100 on screen and not clipped
    # Esc leaves the group
    QTest.keyClick(c, Qt.Key.Key_Escape)  # first Esc clears the selection
    QTest.keyClick(c, Qt.Key.Key_Escape)
    pump(app)
    assert not c.in_group and not c.context_items
    assert [it.obj.kind for it in c.items_by_id.values()].count("form") == 1
    # ungroup
    g = [i for i, it in c.items_by_id.items() if it.obj.kind == "form"][0]
    c.select([g])
    window.act_ungroup.trigger()
    pump(app)
    assert [it.obj.kind for it in c.items_by_id.values()].count("form") == 0
    assert sum(1 for it in c.items_by_id.values() if it.obj.kind == "path") == 3
