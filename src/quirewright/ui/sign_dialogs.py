"""Dialogs for digital signatures: create a certificate, sign, and inspect signatures."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from quirewright import APP_ID
from quirewright.core import signing
from quirewright.i18n import tr
from quirewright.ui.doc_dialogs import _Base

POSITIONS = [("Bottom left", "bl"), ("Bottom right", "br"), ("Top left", "tl"), ("Top right", "tr")]


class CreateCertificateDialog(_Base):
    def __init__(self, parent=None):
        super().__init__(tr("Create a signing certificate"), parent)
        info = QLabel(tr("Creates a self-signed certificate for signing documents. Readers will see your name and that the document "
                         "has not been changed since signing, but a self-signed certificate is not vouched for by a certificate "
                         "authority. For legally recognised signatures use a certificate issued by a trusted provider."))
        info.setWordWrap(True)
        self.body.addWidget(info)
        form = QFormLayout()
        settings = QSettings(APP_ID, APP_ID)
        self.name = QLineEdit(settings.value("user/author", "", type=str))
        form.addRow(tr("Full name"), self.name)
        self.email = QLineEdit()
        form.addRow(tr("E-mail"), self.email)
        self.org = QLineEdit()
        form.addRow(tr("Organisation"), self.org)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("Password"), self.password)
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("Repeat password"), self.password2)
        self.years = QSpinBox()
        self.years.setRange(1, 20)
        self.years.setValue(3)
        self.years.setSuffix(" " + tr("years"))
        form.addRow(tr("Valid for"), self.years)
        row = QHBoxLayout()
        self.path = QLineEdit(os.path.join(signing.default_cert_dir(), "my-certificate.p12"))
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.path)
        row.addWidget(browse)
        form.addRow(tr("Save as"), row)
        self.body.addLayout(form)
        self.add_buttons(tr("Create"))

    def _browse(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, tr("Save certificate"), self.path.text(), "PKCS#12 (*.p12 *.pfx)")
        if p:
            self.path.setText(p)

    def accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, tr("Create certificate"), tr("Please enter your name."))
            return
        if self.password.text() != self.password2.text():
            QMessageBox.warning(self, tr("Create certificate"), tr("The passwords do not match."))
            return
        try:
            signing.generate_self_signed(self.name.text().strip(), self.path.text(), self.password.text(), self.email.text().strip(),
                                         self.org.text().strip(), days=365 * self.years.value())
        except Exception as exc:
            QMessageBox.critical(self, tr("Create certificate"), str(exc))
            return
        super().accept()


class SignDialog(_Base):
    def __init__(self, page_count: int, current: int, signature_fields: list[str], parent=None):
        super().__init__(tr("Sign document"), parent, 520)
        settings = QSettings(APP_ID, APP_ID)
        cert_box = QGroupBox(tr("Certificate"))
        cf = QFormLayout(cert_box)
        row = QHBoxLayout()
        self.cert_path = QLineEdit(settings.value("sign/lastCert", "", type=str))
        self.cert_path.setPlaceholderText(tr("PKCS#12 file (.p12 / .pfx)"))
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._browse)
        create = QPushButton(tr("Create new…"))
        create.clicked.connect(self._create)
        row.addWidget(self.cert_path)
        row.addWidget(browse)
        row.addWidget(create)
        cf.addRow(tr("File"), row)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        cf.addRow(tr("Password"), self.password)
        self.cert_info = QLabel("")
        self.cert_info.setProperty("role", "muted")
        self.cert_info.setWordWrap(True)
        cf.addRow("", self.cert_info)
        check = QPushButton(tr("Check certificate"))
        check.clicked.connect(self._check)
        cf.addRow("", check)
        self.body.addWidget(cert_box)

        det = QGroupBox(tr("Details (optional)"))
        df = QFormLayout(det)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(tr("e.g. I approve this document"))
        df.addRow(tr("Reason"), self.reason)
        self.location = QLineEdit()
        df.addRow(tr("Location"), self.location)
        self.contact = QLineEdit()
        df.addRow(tr("Contact"), self.contact)
        self.certify = QCheckBox(tr("Certify: mark the document so that further changes invalidate the signature"))
        df.addRow("", self.certify)
        self.body.addWidget(det)

        app = QGroupBox(tr("Appearance"))
        af = QVBoxLayout(app)
        self.invisible = QRadioButton(tr("Invisible signature (no stamp on the page)"))
        self.visible = QRadioButton(tr("Visible stamp on the current page"))
        self.field = QRadioButton(tr("Sign an existing signature field"))
        af.addWidget(self.invisible)
        af.addWidget(self.visible)
        vrow = QHBoxLayout()
        vrow.addSpacing(24)
        self.position = QComboBox()
        for label, key in POSITIONS:
            self.position.addItem(tr(label), key)
        vrow.addWidget(QLabel(tr("Position")))
        vrow.addWidget(self.position)
        self.width = QSpinBox()
        self.width.setRange(60, 600)
        self.width.setValue(180)
        self.width.setSuffix(" pt")
        self.height = QSpinBox()
        self.height.setRange(30, 400)
        self.height.setValue(60)
        self.height.setSuffix(" pt")
        vrow.addWidget(QLabel(tr("Size")))
        vrow.addWidget(self.width)
        vrow.addWidget(QLabel("×"))
        vrow.addWidget(self.height)
        vrow.addStretch()
        af.addLayout(vrow)
        af.addWidget(self.field)
        frow = QHBoxLayout()
        frow.addSpacing(24)
        self.field_combo = QComboBox()
        self.field_combo.addItems(signature_fields)
        frow.addWidget(self.field_combo)
        frow.addStretch()
        af.addLayout(frow)
        self.body.addWidget(app)
        if signature_fields:
            self.field.setChecked(True)
        else:
            self.field.setEnabled(False)
            self.field_combo.setEnabled(False)
            self.visible.setChecked(True)
        note = QLabel(tr("The signed document is written to a new file. Signing is the final step: any later edit that is saved "
                         "rewrites the file and invalidates the signature."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        self.body.addWidget(note)
        self.add_buttons(tr("Sign and save as…"))

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, tr("Choose certificate"), signing.default_cert_dir(), "PKCS#12 (*.p12 *.pfx);;All files (*)")
        if p:
            self.cert_path.setText(p)

    def _create(self) -> None:
        dlg = CreateCertificateDialog(self)
        if dlg.exec() == CreateCertificateDialog.DialogCode.Accepted:
            self.cert_path.setText(dlg.path.text())
            self.password.setText(dlg.password.text())
            self._check()

    def _check(self) -> None:
        try:
            info = signing.certificate_summary(self.cert_path.text(), self.password.text())
        except Exception as exc:
            self.cert_info.setText(tr("Cannot read the certificate: {error}").format(error=exc))
            return
        kind = tr("self-signed") if info["self_signed"] else tr("issued by {issuer}").format(issuer=info["issuer"])
        self.cert_info.setText(f"{info['common_name']} · {kind} · {tr('valid')} {info['valid_from']} – {info['valid_to']}")

    def values(self) -> dict:
        QSettings(APP_ID, APP_ID).setValue("sign/lastCert", self.cert_path.text())
        mode = "field" if self.field.isChecked() else ("visible" if self.visible.isChecked() else "invisible")
        return {
            "cert": self.cert_path.text(), "password": self.password.text(), "reason": self.reason.text().strip(),
            "location": self.location.text().strip(), "contact": self.contact.text().strip(), "certify": self.certify.isChecked(),
            "mode": mode, "position": self.position.currentData(), "width": self.width.value(), "height": self.height.value(),
            "field": self.field_combo.currentText(),
        }


class SignaturesDialog(_Base):
    def __init__(self, sigs: list[signing.SignatureInfo], on_add_trust, parent=None):
        super().__init__(tr("Signatures"), parent, 720)
        self.setMinimumHeight(380)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("Status"), tr("Signed by"), tr("Date"), tr("Reason"), tr("Field")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.body.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        self.body.addWidget(self.details)
        self.sigs = sigs
        for s in sigs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            status = QTableWidgetItem(("✔ " if s.intact else "✖ ") + tr(s.summary))
            self.table.setItem(r, 0, status)
            self.table.setItem(r, 1, QTableWidgetItem(s.signer))
            self.table.setItem(r, 2, QTableWidgetItem(s.signed_at))
            self.table.setItem(r, 3, QTableWidgetItem(s.reason))
            self.table.setItem(r, 4, QTableWidgetItem(s.field_name))
        self.table.currentCellChanged.connect(lambda r, c, pr, pc: self._show(r))
        if sigs:
            self.table.setCurrentCell(0, 0)
        else:
            self.details.setPlainText(tr("This document has no digital signatures."))
        row = QHBoxLayout()
        trust = QPushButton(tr("Trust a certificate…"))
        trust.setToolTip(tr("Add a certificate file (.pem/.cer/.crt) to your trust store so signatures made with it show as trusted"))
        trust.clicked.connect(lambda: on_add_trust(self))
        row.addWidget(trust)
        row.addStretch()
        self.body.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        self.body.addWidget(box)

    def _show(self, r: int) -> None:
        if r < 0 or r >= len(self.sigs):
            return
        s = self.sigs[r]
        lines = [
            f"{tr('Signed by')}: {s.signer}" + (f" ({tr('issued by')} {s.issuer})" if s.issuer and s.issuer != s.signer else ""),
            f"{tr('Certificate valid')}: {s.valid_from} – {s.valid_to}",
            f"{tr('Document intact')}: {tr('yes') if s.intact else tr('no')}",
            f"{tr('Covers whole document')}: {tr('yes') if s.covers_whole_document else tr('no, later changes were appended')}",
            f"{tr('Trusted')}: {tr('yes') if s.trusted else tr('no')}",
        ]
        if s.location:
            lines.append(f"{tr('Location')}: {s.location}")
        if s.contact:
            lines.append(f"{tr('Contact')}: {s.contact}")
        for e in s.errors:
            lines.append(f"⚠ {e}")
        self.details.setPlainText("\n".join(lines))
