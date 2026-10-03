"""UI tests for comments, find, crop/redact tools, arrangement, dialogs and panels."""

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pdfeditor.ui import theme
from pdfeditor.ui.canvas import TOOL_CROP, TOOL_MARKUP, TOOL_NOTE, TOOL_REDACT, TOOL_SELECT


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def pdf_path(tmp_path):
    pdf = pymupdf.open()
    for i in range(2):
        page = pdf.new_page(width=300, height=200)
        page.insert_text((20, 40), f"Alpha beta gamma {i + 1}", fontsize=12)
        xref = pdf.get_new_xref()
        pdf.update_object(xref, "<<>>")
        pdf.update_stream(xref, b"1 0 0 rg 20 20 40 20 re f 0 1 0 rg 100 20 40 20 re f 0 0 1 rg 200 20 40 20 re f")
        pdf[i].set_contents(xref)
        pdf[i].insert_text((20, 40), f"Alpha beta gamma {i + 1}", fontsize=12)
    p = str(tmp_path / "feat.pdf")
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def window(app, pdf_path):
    from pdfeditor.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
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


def test_welcome_and_stack(app, window):
    assert window.stack.currentIndex() == 1
    window._set_document(None)
    assert window.stack.currentIndex() == 0
    assert window.welcome.recent.count() >= 1


def test_find_bar(app, window):
    window.show_find()
    assert window.findbar.isVisible()
    window.findbar.edit.setText("gamma")
    pump(app)
    assert len(window.findbar.hits) == 2
    assert window.canvas.highlights and window.canvas.page_index == 0
    window.findbar.next()
    pump(app)
    assert window.canvas.page_index == 1
    window.findbar.hide_bar()
    assert window.canvas.highlights == []


def test_highlight_and_note_tools(app, window):
    c = window.canvas
    c.set_tool(f"{TOOL_MARKUP}:highlight")
    drag(c, QPointF(15, 25), QPointF(120, 45))
    pump(app)
    ann = window.doc.annotations(0)
    assert len(ann) == 1 and ann[0].type_name == "Highlight"
    assert c.annot_selection == [ann[0].xref]
    assert window.properties.annot_box.isVisible()
    c.set_tool(TOOL_NOTE)
    QTest.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(250, 100)))
    pump(app)
    ann = window.doc.annotations(0)
    assert [a.type_name for a in ann] == ["Highlight", "Text note"]
    note = ann[1]
    window.properties.a_contents.setPlainText("Please check")
    window.properties.a_author.setText("Me")
    window.properties._apply_annot()
    pump(app)
    note2 = [a for a in window.doc.annotations(0) if a.xref == note.xref][0]
    assert note2.contents == "Please check" and note2.author == "Me"
    # move the note with the select tool
    c.set_tool(TOOL_SELECT)
    center = c.annot_items[note.xref].sceneBoundingRect().center()
    drag(c, center, center + QPointF(-30, 10))
    pump(app)
    moved = [a for a in window.doc.annotations(0) if a.xref == note.xref][0]
    assert abs((moved.rect.x0 - note2.rect.x0) + 30) < 1
    c.select_annots([moved.xref])
    QTest.keyClick(c, Qt.Key.Key_Delete)
    pump(app)
    assert [a.type_name for a in window.doc.annotations(0)] == ["Highlight"]


def test_crop_and_redact_tools(app, window):
    c = window.canvas
    c.set_tool(TOOL_CROP)
    drag(c, QPointF(10, 10), QPointF(150, 100))
    pump(app, 10)
    assert abs(window.doc.page_rect(0).width - 140) < 0.5
    window.undo()
    pump(app)
    assert window.doc.page_rect(0).width == 300
    confirmed = []
    c.confirm_area = lambda tool, r: confirmed.append(tool) or True
    c.set_tool(TOOL_REDACT)
    drag(c, QPointF(10, 25), QPointF(120, 45))
    pump(app)
    assert confirmed == [TOOL_REDACT]
    assert "Alpha" not in window.doc.page_text(0)


def test_arrange_actions(app, window):
    c = window.canvas
    rects = sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "path"), key=lambda o: o.bbox.x0)
    assert len(rects) == 3
    c.select([r.id for r in rects])
    window.canvas.align_selection("top")
    pump(app)
    tops = {round(it.sceneBoundingRect().top(), 2) for it in c.items_by_id.values() if it.obj.kind == "path"}
    assert len(tops) == 1
    c.select([r.id for r in sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "path"), key=lambda o: o.bbox.x0)])
    c.distribute_selection(True)
    pump(app)
    xs = sorted(it.sceneBoundingRect().center().x() for it in c.items_by_id.values() if it.obj.kind == "path")
    assert abs((xs[1] - xs[0]) - (xs[2] - xs[1])) < 0.5
    first = sorted((it.obj for it in c.items_by_id.values() if it.obj.kind == "path"), key=lambda o: o.bbox.x0)[0]
    c.select([first.id])
    c.duplicate_selection(10)
    pump(app)
    assert sum(1 for it in c.items_by_id.values() if it.obj.kind == "path") == 4
    c.bring_to_front()
    pump(app)
    assert c.selection == [max(c.items_by_id)]
    c.send_to_back()
    pump(app)
    assert c.selection == [min(c.items_by_id)]
    c.flip_selection(True)
    pump(app)
    assert window.doc.undo_stack.undo_label == "Flip"
    text_ids = [i for i, it in c.items_by_id.items() if it.obj.kind == "text"]
    c.select(text_ids)
    assert "Alpha" in c.copy_selected_text()


def test_outline_panel(app, window):
    window.outline.current_page = 1
    from PySide6.QtWidgets import QInputDialog

    orig = QInputDialog.getText
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Chapter", True))
    try:
        window.outline.add_bookmark()
    finally:
        QInputDialog.getText = orig
    ol = window.doc.outline()
    assert len(ol) == 1 and ol[0].title == "Chapter" and ol[0].page == 2
    assert window.outline.tree.topLevelItemCount() == 1
    window.outline.tree.setCurrentItem(window.outline.tree.topLevelItem(0))
    window.outline._activate(window.outline.tree.topLevelItem(0))
    assert window.canvas.page_index == 1
    window.outline.delete_selected()
    assert window.doc.outline() == []


def test_dialogs_apply(app, window):
    from pdfeditor.ui.doc_dialogs import (
        ExportImageDialog,
        PageNumbersDialog,
        PropertiesDialog,
        ResourcesDialog,
        SecurityDialog,
        ShortcutsDialog,
        WatermarkDialog,
    )

    d = PropertiesDialog(window.doc, window)
    d.fields["title"].setText("Feature test")
    window.doc.set_metadata(d.values())
    assert window.doc.metadata()["title"] == "Feature test"
    s = SecurityDialog(window.doc, window)
    s.encrypt.setChecked(True)
    s.user_pw.setText("abc")
    st = s.settings()
    assert st.method == "aes256" and st.user_password == "abc"
    window.doc.set_security(st)
    assert window.doc.security_info()["pending"].user_password == "abc"
    s2 = SecurityDialog(window.doc, window)
    assert s2.encrypt.isChecked() and s2.user_pw.text() == "abc"
    r = ResourcesDialog(window.doc, window)
    assert r.font_table.rowCount() >= 1 and r.att_table.rowCount() == 0
    pn = PageNumbersDialog(window.doc.page_count, [0], 0, window)
    assert pn.pages(pn.scope) == [0, 1]
    wm = WatermarkDialog(window.doc.page_count, [0], 0, window)
    wm.scope.setCurrentIndex(wm.scope.findData("current"))
    assert wm.pages(wm.scope) == [0]
    ExportImageDialog(2, 0, window)
    ShortcutsDialog(window.findChildren(type(window.act_open)), window)


def test_page_entry_and_decorations(app, window):
    window.page_entry.setText("2")
    window._page_from_entry()
    assert window.canvas.page_index == 1
    window.doc.add_page_numbers([0, 1], "bottom-center", "{n}", 1)
    assert window.doc.page_text(1).strip().endswith("2")
    window.doc.add_watermark([0], "DRAFT")
    assert "DRAFT" in window.doc.page_text(0)
    window.toggle_dark(True)
    window.toggle_dark(False)
    window.properties.refresh_units()
