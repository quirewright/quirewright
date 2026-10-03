"""Paragraph editing, text boxes, and the bezier pen."""

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from pdfeditor.ui import theme
from pdfeditor.ui.canvas import TOOL_PEN, TOOL_TEXT


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def pdf_path(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=400, height=300)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, "<<>>")
    # a three-line paragraph plus a separate heading far above it
    pdf.update_stream(xref, b"BT /helv 20 Tf 30 270 Td (Heading) Tj ET BT /helv 12 Tf 30 200 Td (The quick brown fox) Tj 0 -14 Td (jumps over the) Tj 0 -14 Td (lazy dog) Tj ET")
    page.set_contents(xref)
    page.insert_font(fontname="helv")
    p = str(tmp_path / "para.pdf")
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
    win.canvas.set_zoom(1.5)
    app.processEvents()
    yield win
    win._set_document(None)
    win.close()


def pump(app, n=5):
    for _ in range(n):
        app.processEvents()


def runs(c):
    return sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "text"), key=lambda r: -r.tm.f)


def test_paragraph_grouping(app, window):
    c = window.canvas
    rs = runs(c)
    assert [r.text for r in rs] == ["Heading", "The quick brown fox", "jumps over the", "lazy dog"]
    lines = c.paragraph_line_ids(rs[2].id)
    assert [c._line_text(ids) for ids in lines] == ["The quick brown fox", "jumps over the", "lazy dog"]
    assert c.paragraph_line_ids(rs[0].id) == [[rs[0].id]]


def test_paragraph_edit_rewraps(app, window):
    c = window.canvas
    rs = runs(c)
    c.select([rs[1].id])
    window.edit_selected_paragraph()
    assert c.text_proxy is not None and isinstance(c.text_proxy.widget(), QPlainTextEdit)
    assert c.text_proxy.widget().toPlainText() == "The quick brown fox\njumps over the\nlazy dog"
    c.text_proxy.widget().setPlainText("A completely different and somewhat longer paragraph that needs wrapping")
    QTest.keyClick(c.text_proxy.widget(), Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    assert c.text_proxy is None
    rs2 = runs(c)
    assert rs2[0].text == "Heading"
    body = [r.text for r in rs2[1:]]
    assert len(body) >= 3 and " ".join(body) == "A completely different and somewhat longer paragraph that needs wrapping"
    assert all(abs(r.tm.e - 30) < 1e-6 for r in rs2[1:])
    assert abs(rs2[1].tm.f - 200) < 1e-6 and abs((rs2[1].tm.f - rs2[2].tm.f) - 14) < 1e-6
    assert window.doc.undo_stack.undo_label == "Edit paragraph"
    window.undo()
    pump(app)
    assert [r.text for r in runs(c)] == ["Heading", "The quick brown fox", "jumps over the", "lazy dog"]


def test_text_box_creation(app, window):
    c = window.canvas
    c.draw_style.font_size = 12
    c.set_tool(TOOL_TEXT)
    vp = c.viewport()
    a, b = c.mapFromScene(QPointF(200, 40)), c.mapFromScene(QPointF(330, 120))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(vp, a + QPoint(6, 6))
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    assert c.text_proxy is not None and c.text_box is not None
    edit = c.text_proxy.widget()
    edit.setPlainText("Words that will wrap inside the box several times over")
    QTest.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    new = [r for r in runs(c) if r.tm.e > 150]
    assert len(new) >= 2
    assert abs(new[0].tm.e - 200) < 0.5 and abs(new[0].tm.f - (300 - 52)) < 0.5  # baseline = top + font size
    assert all(r.bbox.x1 <= 331 for r in new)


def test_pen_curves(app, window):
    c = window.canvas
    c.set_tool(TOOL_PEN)
    vp = c.viewport()
    # corner, then a smooth point made by click-drag, then a corner
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(50, 50)))
    a = c.mapFromScene(QPointF(150, 50))
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(vp, a + QPoint(10, 10))
    QTest.mouseMove(vp, c.mapFromScene(QPointF(190, 90)))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(190, 90)))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(250, 150)))
    assert c.pen_handles[1] is not None and c.pen_handles[0] is None
    QTest.keyClick(c, Qt.Key.Key_Return)
    pump(app)
    obj = c.items_by_id[c.selection[0]].obj
    assert obj.kind == "path"
    ops = [seg[0] for seg in obj.subpaths[0]]
    assert ops == ["m", "c", "c"]
