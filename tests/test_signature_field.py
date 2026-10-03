"""The visible signature-field tool."""

import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from quirewright.core import signing
from quirewright.core.document import Document
from quirewright.core.geometry import Rect
from quirewright.ui import theme
from quirewright.ui.canvas import TOOL_FIELD, TOOL_SELECT


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


def test_placeholder_appearance_and_signing(tmp_path):
    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200)
    p = str(tmp_path / "s.pdf")
    pdf.save(p)
    doc = Document(p)
    doc.add_widget(0, 6, Rect(20, 20, 180, 76), name="sig1")
    w = doc.widgets(0)[0]
    assert w.type_name == "Signature" and w.label == "Sign here"
    # The stored appearance stream (what other viewers draw) carries the placeholder;
    # MuPDF itself always synthesises an appearance for unsigned signature fields.
    def ap_stream(d):
        x = d.widgets(0)[0].xref
        ap = d.pdf.xref_get_key(x, "AP/N")
        return d.pdf.xref_stream(int(ap[1].split()[0]))

    assert b"(Sign here) Tj" in ap_stream(doc) and b"(sig1) Tj" in ap_stream(doc) and b"0.95 0.97 1 rg" in ap_stream(doc)
    doc.update_widget(0, w.xref, label="Please sign", border_color=(1, 0, 0))
    assert doc.widgets(0)[0].label == "Please sign"
    assert b"(Please sign) Tj" in ap_stream(doc) and b"1 0 0 RG" in ap_stream(doc)
    # moving keeps the placeholder
    doc.transform_widgets(0, [w.xref], __import__("quirewright.core.geometry", fromlist=["Matrix"]).Matrix.translation(20, 0))
    assert b"(Please sign) Tj" in ap_stream(doc)
    # the saved file keeps it too
    out_path = str(tmp_path / "saved.pdf")
    doc.save(out_path)
    assert b"(Please sign) Tj" in ap_stream(Document(out_path))
    # signing the field replaces the placeholder with the signature stamp
    cert = str(tmp_path / "c.p12")
    signing.generate_self_signed("Field Signer", cert, "pw")
    signed = signing.sign_pdf(doc.pdf.tobytes(), cert, "pw", field_name="sig1")
    s = signing.signatures(signed)[0]
    assert s.intact and s.field_name == "sig1"
    out = pymupdf.open(stream=signed, filetype="pdf")
    text = out[0].get_text()
    assert "Field Signer" in text and "Please sign" not in text
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert doc.widgets(0) == []


def test_tool_click_and_inspector(app, tmp_path):
    from quirewright.ui.main_window import MainWindow

    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200)
    p = str(tmp_path / "t.pdf")
    pdf.save(p)
    win = MainWindow()
    win.show()
    win.open_file(p)
    app.processEvents()
    c = win.canvas
    c.snap_enabled = False
    c.set_zoom(2.0)
    app.processEvents()
    win.act_tool_signature.trigger()
    assert c.tool == f"{TOOL_FIELD}:6" and win.act_tool_signature.isChecked() and not win.act_tool_field.isChecked()
    QTest.mouseClick(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(30, 30)))
    for _ in range(5):
        app.processEvents()
    ws = win.doc.widgets(0)
    assert len(ws) == 1 and ws[0].field_type == 6
    assert abs(ws[0].rect.width - 170) < 0.6 and abs(ws[0].rect.height - 56) < 0.6
    assert c.widget_selection == [ws[0].xref]
    assert win.properties.w_sign_btn.isVisible() and win.properties.w_caption.isVisible()
    assert win.properties.w_caption.text() == "Sign here"
    win.properties.w_caption.setText("Signature of applicant")
    win.properties._apply_widget()
    for _ in range(5):
        app.processEvents()
    assert win.doc.widgets(0)[0].label == "Signature of applicant"
    # drag-created field uses the dragged size
    QTest.mousePress(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(30, 120)))
    QTest.mouseMove(c.viewport(), c.mapFromScene(QPointF(40, 130)))
    QTest.mouseMove(c.viewport(), c.mapFromScene(QPointF(230, 180)))
    QTest.mouseRelease(c.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.mapFromScene(QPointF(230, 180)))
    for _ in range(5):
        app.processEvents()
    ws = win.doc.widgets(0)
    assert len(ws) == 2 and abs(ws[1].rect.width - 200) < 0.6 and abs(ws[1].rect.height - 60) < 0.6
    c.set_tool(TOOL_SELECT)
    for v in list(win.views()):
        win._remove_view(v)
    win.close()


def test_signed_field_state_and_overlay(tmp_path, app):
    from quirewright.ui.canvas import WidgetItem

    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200)
    p = str(tmp_path / "u.pdf")
    pdf.save(p)
    doc = Document(p)
    doc.add_widget(0, 6, Rect(20, 20, 180, 76), name="sig1")
    info = doc.widgets(0)[0]
    assert not info.signed and WidgetItem(info).is_unsigned_signature
    cert = str(tmp_path / "c.p12")
    signing.generate_self_signed("Field Signer", cert, "pw")
    signed = signing.sign_pdf(doc.pdf.tobytes(), cert, "pw", field_name="sig1")
    out = str(tmp_path / "signed.pdf")
    open(out, "wb").write(signed)
    doc2 = Document(out)
    info2 = doc2.widgets(0)[0]
    assert info2.field_type == 6 and info2.signed
    assert not WidgetItem(info2).is_unsigned_signature  # the stamp is shown, not the placeholder
    assert "Field Signer" in doc2.page_text(0)
    # editing the field's caption must not regenerate the placeholder over the signature
    doc2.update_widget(0, info2.xref, label="x")
    assert "Field Signer" in doc2.page_text(0) and doc2.widgets(0)[0].signed
