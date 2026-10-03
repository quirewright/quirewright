"""Signing through the UI (dialogs are driven programmatically)."""

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from quirewright.core import signing
from quirewright.ui import theme


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, False)
    return a


@pytest.fixture
def window(app, tmp_path):
    from quirewright.ui.main_window import MainWindow

    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200).insert_text((20, 40), "Agreement", fontsize=14)
    p = str(tmp_path / "a.pdf")
    pdf.save(p)
    win = MainWindow()
    win.show()
    win.open_file(p)
    app.processEvents()
    yield win
    for v in list(win.views()):
        win._remove_view(v)
    win.close()


def test_sign_visible_from_window(app, window, tmp_path, monkeypatch):
    from quirewright.ui import main_window as mw

    cert = str(tmp_path / "c.p12")
    signing.generate_self_signed("UI Signer", cert, "pw")
    out = str(tmp_path / "a-signed.pdf")

    class FakeDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return FakeDialog.DialogCode.Accepted

        class DialogCode:
            Accepted = 1

        def values(self):
            return {"cert": cert, "password": "pw", "reason": "Approved", "location": "", "contact": "", "certify": False,
                    "mode": "visible", "position": "br", "width": 160, "height": 50, "field": ""}

    monkeypatch.setattr(mw, "SignDialog", FakeDialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    window.sign_document()
    app.processEvents()
    assert window.doc.path == out and window.tabs.count() == 2
    sigs = signing.signatures(open(out, "rb").read())
    assert len(sigs) == 1 and sigs[0].intact and sigs[0].reason == "Approved" and sigs[0].signer == "UI Signer"
    assert getattr(window.doc, "signed", False)
    assert "UI Signer" in window.doc.page_text(0)
    # editing a signed document and saving warns; cancelling keeps it unsaved
    window.doc.rotate_pages([0], 90)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
    assert window.save() is False and window.doc.is_modified
    # signatures dialog lists it
    from quirewright.ui.sign_dialogs import SignaturesDialog

    dlg = SignaturesDialog(signing.signatures(open(out, "rb").read()), lambda p: None, window)
    assert dlg.table.rowCount() == 1 and "VALID" in dlg.table.item(0, 0).text()
    assert "UI Signer" in dlg.details.toPlainText()


def test_sign_dialog_widgets(app, window):
    from quirewright.ui.sign_dialogs import CreateCertificateDialog, SignDialog

    d = SignDialog(1, 0, ["sig1"], window)
    assert d.field.isChecked() and d.values()["mode"] == "field" and d.values()["field"] == "sig1"
    d2 = SignDialog(1, 0, [], window)
    assert d2.visible.isChecked() and not d2.field.isEnabled()
    c = CreateCertificateDialog(window)
    assert c.path.text().endswith(".p12")
