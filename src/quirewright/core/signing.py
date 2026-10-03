"""Digital signatures: create self-signed certificates, sign documents (PAdES/CMS via
pyHanko) with optional visible signature appearances, and validate existing signatures."""

from __future__ import annotations

import datetime as _dt
import io
import os
from dataclasses import dataclass, field

from quirewright.core.geometry import Rect


@dataclass
class SignatureInfo:
    field_name: str
    signer: str = ""
    signed_at: str = ""
    reason: str = ""
    location: str = ""
    contact: str = ""
    intact: bool = False  # cryptographic signature verifies and the signed bytes are unchanged
    modified_after: bool = False  # incremental updates were appended after signing
    covers_whole_document: bool = False
    trusted: bool = False  # certificate chains to a trusted root (none configured by default)
    certified: bool = False
    issuer: str = ""
    valid_from: str = ""
    valid_to: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.intact:
            return "INVALID"
        if self.modified_after:
            return "VALID (document modified after signing)"
        return "VALID" + ("" if self.trusted else " (signer not in trust store)")


# --- certificates ------------------------------------------------------------------

def generate_self_signed(common_name: str, path: str, password: str, email: str = "", organization: str = "", days: int = 1095) -> str:
    """Create a self-signed certificate + private key and store them in a PKCS#12 file."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if organization:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    name = x509.Name(attrs)
    now = _dt.datetime.now(_dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .sign(key, hashes.SHA256())
    )
    enc = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
    data = pkcs12.serialize_key_and_certificates(common_name.encode()[:60], key, cert, None, enc)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def certificate_summary(p12_path: str, password: str) -> dict:
    from cryptography.hazmat.primitives.serialization import pkcs12

    key, cert, extra = pkcs12.load_key_and_certificates(open(p12_path, "rb").read(), password.encode() if password else None)
    if cert is None:
        raise ValueError("The file does not contain a certificate")
    return {
        "subject": cert.subject.rfc4514_string(),
        "common_name": _cn(cert.subject),
        "issuer": cert.issuer.rfc4514_string(),
        "valid_from": cert.not_valid_before_utc.strftime("%Y-%m-%d"),
        "valid_to": cert.not_valid_after_utc.strftime("%Y-%m-%d"),
        "self_signed": cert.subject == cert.issuer,
    }


def _cn(name) -> str:
    from cryptography.x509.oid import NameOID

    try:
        vals = name.get_attributes_for_oid(NameOID.COMMON_NAME)
        return vals[0].value if vals else name.rfc4514_string()
    except Exception:
        return str(name)


# --- signing ----------------------------------------------------------------------------

def sign_pdf(
    pdf_bytes: bytes,
    p12_path: str,
    password: str,
    *,
    field_name: str | None = None,
    page: int | None = None,
    box_pdf: Rect | None = None,
    reason: str = "",
    location: str = "",
    contact: str = "",
    certify: bool = False,
    stamp_text: str | None = None,
) -> bytes:
    """Sign a PDF and return the signed bytes.

    * ``field_name`` signs an existing (empty) signature field;
    * otherwise a new field is created, visible on ``page`` inside ``box_pdf``
      (PDF user-space coordinates) when given, invisible when not.
    """
    from pyhanko import stamp
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.text import TextBoxStyle
    from pyhanko.sign import fields, signers

    signer = signers.SimpleSigner.load_pkcs12(pfx_file=p12_path, passphrase=password.encode() if password else None)
    if signer is None:
        raise ValueError("Could not load the certificate (wrong password?)")
    new_field = None
    name = field_name or f"Signature{int(_dt.datetime.now().timestamp())}"
    if field_name is None:
        if page is not None and box_pdf is not None:
            new_field = fields.SigFieldSpec(sig_field_name=name, on_page=page, box=(box_pdf.x0, box_pdf.y0, box_pdf.x1, box_pdf.y1))
        else:
            new_field = fields.SigFieldSpec(sig_field_name=name)
    meta = signers.PdfSignatureMetadata(field_name=name, reason=reason or None, location=location or None, contact_info=contact or None,
                                        certify=certify, md_algorithm="sha256")
    text = stamp_text or "Digitally signed by %(signer)s\nDate: %(ts)s" + ("\nReason: " + reason if reason else "")
    style = stamp.TextStampStyle(stamp_text=text, border_width=1, text_box_style=TextBoxStyle(font_size=9), background_opacity=0.0)
    pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style, new_field_spec=new_field)
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))
    out = io.BytesIO()
    pdf_signer.sign_pdf(writer, output=out, existing_fields_only=field_name is not None)
    return out.getvalue()


# --- validation ------------------------------------------------------------------------------

def signatures(pdf_bytes: bytes, trust_roots: list[str] | None = None) -> list[SignatureInfo]:
    """List and validate the signatures in a PDF. ``trust_roots`` are PEM/DER certificate files."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    roots = []
    for p in trust_roots or []:
        try:
            from asn1crypto import x509 as a_x509

            data = open(p, "rb").read()
            if b"-----BEGIN" in data:
                from asn1crypto import pem

                _, _, data = next(pem.unarmor(data, multiple=True))
            roots.append(a_x509.Certificate.load(data))
        except Exception:
            continue
    ctx = ValidationContext(trust_roots=roots, allow_fetching=False) if roots else ValidationContext(allow_fetching=False)
    out: list[SignatureInfo] = []
    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes))
        embedded = list(reader.embedded_signatures)
    except Exception as exc:
        return [SignatureInfo(field_name="?", errors=[f"Could not read signatures: {exc}"])]
    for sig in embedded:
        info = SignatureInfo(field_name=sig.field_name or "")
        try:
            status = validate_pdf_signature(sig, signer_validation_context=ctx)
            cert = status.signing_cert
            info.signer = _cn_asn1(cert.subject) if cert is not None else ""
            info.issuer = _cn_asn1(cert.issuer) if cert is not None else ""
            if cert is not None:
                info.valid_from = cert.not_valid_before.strftime("%Y-%m-%d")
                info.valid_to = cert.not_valid_after.strftime("%Y-%m-%d")
            info.intact = bool(status.intact and status.valid)
            info.trusted = bool(status.trusted)
            info.modified_after = str(getattr(status, "modification_level", "")).endswith("OTHER") or (
                status.coverage is not None and status.coverage.name != "ENTIRE_FILE" and bool(status.intact)
            )
            info.covers_whole_document = status.coverage is not None and status.coverage.name == "ENTIRE_FILE"
            info.certified = bool(getattr(status, "docmdp_ok", False)) and sig.sig_object.get("/Reference") is not None
            dt = status.signer_reported_dt
            info.signed_at = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
            so = sig.sig_object
            info.reason = str(so.get("/Reason", "") or "")
            info.location = str(so.get("/Location", "") or "")
            info.contact = str(so.get("/ContactInfo", "") or "")
            if not info.trusted:
                info.errors.append("Certificate is not in the trust store")
        except Exception as exc:
            info.errors.append(str(exc))
        out.append(info)
    return out


def _cn_asn1(name) -> str:
    try:
        return name.native.get("common_name") or name.human_friendly
    except Exception:
        return str(name)


def has_signatures(pdf_bytes: bytes) -> bool:
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader

        return bool(list(PdfFileReader(io.BytesIO(pdf_bytes)).embedded_signatures))
    except Exception:
        return False


def default_cert_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "quirewright", "certificates")
    os.makedirs(d, exist_ok=True)
    return d
