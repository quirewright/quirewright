"""Self-signed certificates, signing, and validation."""

import pymupdf
import pytest

from quirewright.core import signing
from quirewright.core.document import Document
from quirewright.core.geometry import Rect


@pytest.fixture
def cert(tmp_path):
    p = str(tmp_path / "me.p12")
    signing.generate_self_signed("Test Signer", p, "secret", email="me@example.com", organization="Example")
    return p


@pytest.fixture
def pdf_bytes(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=200)
    page.insert_text((20, 40), "Contract", fontsize=16)
    return pdf.tobytes()


def test_certificate_summary(cert):
    info = signing.certificate_summary(cert, "secret")
    assert info["common_name"] == "Test Signer" and info["self_signed"]
    with pytest.raises((ValueError, TypeError)):
        signing.certificate_summary(cert, "wrong")


def test_sign_invisible_and_validate(cert, pdf_bytes, tmp_path):
    assert not signing.has_signatures(pdf_bytes)
    signed = signing.sign_pdf(pdf_bytes, cert, "secret", reason="Approval", location="Berlin")
    assert signing.has_signatures(signed)
    sigs = signing.signatures(signed)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.intact and s.covers_whole_document and not s.modified_after
    assert s.signer == "Test Signer" and s.reason == "Approval" and s.location == "Berlin"
    assert not s.trusted and "trust store" in s.errors[0]
    # trusting the certificate itself makes it trusted
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    _, c, _ = pkcs12.load_key_and_certificates(open(cert, "rb").read(), b"secret")
    pem = tmp_path / "root.pem"
    pem.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    assert signing.signatures(signed, [str(pem)])[0].trusted
    # tampering breaks the signature
    doc = pymupdf.open(stream=signed, filetype="pdf")
    doc[0].insert_text((20, 100), "tampered", fontsize=12)
    tampered = doc.tobytes()
    assert not signing.signatures(tampered)[0].intact or not signing.signatures(tampered)[0].covers_whole_document


def test_sign_visible_renders_stamp(cert, pdf_bytes):
    signed = signing.sign_pdf(pdf_bytes, cert, "secret", page=0, box_pdf=Rect(150, 20, 290, 70), reason="Reviewed")
    doc = pymupdf.open(stream=signed, filetype="pdf")
    page = doc[0]
    widgets = list(page.widgets())
    assert widgets and widgets[0].field_type_string == "Signature"
    assert "Test Signer" in page.get_text()
    sig = signing.signatures(signed)[0]
    assert sig.intact and sig.reason == "Reviewed"


def test_sign_existing_field_via_document(cert, tmp_path):
    pdf = pymupdf.open()
    pdf.new_page(width=300, height=200)
    p = str(tmp_path / "f.pdf")
    pdf.save(p)
    doc = Document(p)
    doc.add_widget(0, 6, Rect(20, 20, 160, 60), name="sig1")
    assert [w.type_name for w in doc.widgets(0)] == ["Signature"]
    data = doc.pdf.tobytes()
    signed = signing.sign_pdf(data, cert, "secret", field_name="sig1")
    sigs = signing.signatures(signed)
    assert len(sigs) == 1 and sigs[0].field_name == "sig1" and sigs[0].intact
