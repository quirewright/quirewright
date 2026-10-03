# Security policy

Quirewright was developed almost entirely by AI with very limited human
review, and none of its security-relevant features have been independently
audited. Please take the following into account before relying on it.

## What has not been audited

- **Encryption and passwords.** Password protection and permission flags are
  applied through MuPDF. The implementation has not been reviewed for
  correctness and no claim is made about the strength of the result.
- **Digital signatures.** Signing and signature verification are implemented
  with pyHanko. Neither the integration nor the trust-store handling has been
  audited. Do not treat a signature that Quirewright reports as valid as proof
  of anything that matters; verify it with an independent tool.
- **Redaction.** The redaction tool removes text and images under the marked
  area through MuPDF. It has not been verified against every way content can
  be stored in a PDF, and residual data (metadata, attachments, form values,
  incremental-update history, OCR layers) may remain. Do not use it to remove
  sensitive information from documents that will be published.
- **Parsing untrusted files.** Quirewright parses PDF content streams with its
  own code and hands files to MuPDF, Tesseract and pyHanko. Opening a
  malicious PDF may crash the application; it has not been fuzzed or hardened.
- **Form scripts.** Calculation and format scripts are interpreted by a small
  local evaluator, not a JavaScript engine. It is limited by design, but has
  not been reviewed for abuse through crafted scripts.

## Supported versions

Only the latest release and the `main` branch receive fixes.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting on the repository's **Security** tab
("Report a vulnerability"). Include a description of the impact, steps or a
file that reproduces it, and the version and platform you used. You will get
an acknowledgement, and a fix or a published advisory once the problem is
understood. Reports about problems in MuPDF, Qt, pyHanko or Tesseract
themselves should go to those projects.
