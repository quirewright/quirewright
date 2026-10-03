"""Form field scripts, local calculation, and the OCR text layer."""

import pymupdf
import pytest

from quirewright.core import ocr
from quirewright.core.document import (
    Document,
    calc_script,
    date_format_script,
    format_number,
    number_format_script,
    percent_format_script,
    range_validate_script,
)
from quirewright.core.geometry import Rect


@pytest.fixture
def doc(tmp_path):
    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200)
    p = str(tmp_path / "s.pdf")
    pdf.save(p)
    pdf.close()
    d = Document(p)
    for name, x in (("a", 20), ("b", 120), ("total", 220)):
        d.add_widget(0, 7, Rect(x, 20, x + 70, 40), name=name)
    return d


def test_script_generators():
    assert calc_script("sum", ["a", "b"]) == 'AFSimple_Calculate("SUM", new Array("a", "b"));'
    assert number_format_script(2) == 'AFNumber_Format(2, 0, 0, 0, "", true);'
    assert percent_format_script(1) == "AFPercent_Format(1, 0);"
    assert date_format_script("dd/mm/yyyy") == 'AFDate_FormatEx("dd/mm/yyyy");'
    assert range_validate_script(0, 100) == "AFRange_Validate(true, 0, true, 100);"
    assert range_validate_script(None, 5) == "AFRange_Validate(false, 0, true, 5);"
    assert format_number(1234.5, number_format_script(2)) == "1,234.50"
    assert format_number(0.256, percent_format_script(1)) == "25.6%"
    assert format_number(3.0, "") == "3"


def test_scripts_roundtrip_and_recalculate(doc):
    ws = {w.field_name: w for w in doc.widgets(0)}
    doc.update_widget(0, ws["total"].xref, script_calc=calc_script("sum", ["a", "b"]), script_format=number_format_script(2),
                      script_validate=range_validate_script(0, 1000), script_keystroke="AFNumber_Keystroke(2, 0, 0, 0, \"\", true);")
    t = {w.field_name: w for w in doc.widgets(0)}["total"]
    assert t.script_calc.startswith("AFSimple_Calculate") and t.script_format.startswith("AFNumber_Format")
    assert t.script_validate.startswith("AFRange_Validate") and t.script_keystroke.startswith("AFNumber_Keystroke")
    cat = doc.pdf.pdf_catalog()
    assert "CO" in doc.pdf.xref_get_key(cat, "AcroForm")[1]
    doc.update_widget(0, ws["a"].xref, value="12.5")
    doc.update_widget(0, ws["b"].xref, value="7")
    assert doc.recalculate(0) == 1
    assert {w.field_name: w.value for w in doc.widgets(0)}["total"] == "19.50"
    doc.update_widget(0, ws["total"].xref, script_calc="")
    assert {w.field_name: w for w in doc.widgets(0)}["total"].script_calc == ""
    assert doc.recalculate(0) == 0
    # saved file keeps the actions
    out = str(doc.path).replace("s.pdf", "s2.pdf")
    doc.undo_stack.undo()
    doc.save(out)
    re = pymupdf.open(out)
    scripts = [w.script_calc for w in re[0].widgets() if w.field_name == "total"]
    assert scripts and scripts[0].startswith("AFSimple_Calculate")


def test_ocr_text_layer(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 20), False)
    pix.clear_with(90)
    img = tmp_path / "scan.png"
    pix.save(str(img))
    page.insert_image(pymupdf.Rect(20, 20, 140, 60), filename=str(img))
    p = str(tmp_path / "scan.pdf")
    pdf.save(p)
    pdf.close()
    doc = Document(p)
    assert not ocr.page_has_text(doc, 0)
    words = [ocr.OcrWord("Hello", Rect(20, 20, 70, 40)), ocr.OcrWord("world", Rect(80, 20, 140, 40))]
    assert ocr.add_text_layer(doc, 0, words) == 2
    assert doc.page_text(0).split() == ["Hello", "world"]
    runs = [o for o in doc.content(0).objects if o.kind == "text"]
    assert len(runs) == 2 and all(r.invisible for r in runs)
    # fitted to the word boxes (scene y 20..40 -> pdf y 160..180)
    r0 = runs[0]
    assert abs(r0.bbox.x0 - 20) < 0.6 and abs(r0.bbox.x1 - 70) < 1.0
    assert abs(r0.bbox.y0 - 160) < 1.5 and abs(r0.bbox.y1 - 180) < 1.5
    hits = doc.search("world")
    assert hits and abs(hits[0][1].x0 - 80) < 1.0
    # pixels unchanged (invisible)
    pm = doc.render(0, 1.0)
    assert pm.pixel(30, 30) == (90, 90, 90)  # image still intact (text is invisible)
    doc.undo_stack.undo()
    assert not ocr.page_has_text(doc, 0)


def test_ocr_unavailable_message(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    d = Document()
    with pytest.raises(RuntimeError) as exc:
        ocr.recognize(d, 0)
    assert "Tesseract" in str(exc.value)


@pytest.mark.skipif(not ocr.tesseract_available(), reason="tesseract not installed")
def test_ocr_real(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=100)
    page.insert_text((20, 50), "HELLO OCR", fontsize=28)
    pix = page.get_pixmap(dpi=200)
    img = tmp_path / "t.png"
    pix.save(str(img))
    pdf2 = pymupdf.open()
    p2 = pdf2.new_page(width=300, height=100)
    p2.insert_image(p2.rect, filename=str(img))
    p = str(tmp_path / "scan2.pdf")
    pdf2.save(p)
    doc = Document(p)
    words = ocr.recognize(doc, 0, "eng", 300)
    assert any("HELLO" in w.text.upper() for w in words)
