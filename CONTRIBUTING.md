# Contributing to Quirewright

Thank you for your interest. Bug reports, example files, translations,
documentation fixes and code are all welcome. Quirewright is licensed under
the GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later),
and every contribution is accepted under that same licence.

Please note the warning at the top of the README: this project was developed
almost entirely by AI with very limited human review. Bug reports and code
review are therefore among the most useful contributions. Security problems
should be reported as described in [SECURITY.md](SECURITY.md).

## Reporting bugs

Open an issue on GitHub. The more of the following you include, the faster the
problem can be reproduced and fixed:

- **What you did, what you expected, and what happened**, as a numbered list of
  steps. Screenshots or a short screen recording help for anything visual.
- **Platform**: operating system and version, desktop environment (GNOME, KDE,
  …) and whether the session is Wayland or X11.
- **How you installed it**: AppImage, Flatpak, or a source checkout (with the
  git commit).
- **Versions** of Quirewright, Python, PySide6/Qt, MuPDF, pyHanko and
  Tesseract. Help › About lists all of them.
- **Log output**. Run with `quirewright -v file.pdf` (or
  `./Quirewright-*.AppImage -v file.pdf`) and paste anything printed to the
  terminal, including full tracebacks.

**Problems with a particular PDF must come with an example file** that
reproduces the issue. PDFs vary enormously and most content-stream, font,
form and signature bugs cannot be reproduced without one. Keep it as small as
you can and make sure it contains nothing confidential: a single extracted
page is often enough (Page › Extract Pages), or recreate the structure in a
fresh document. If the file cannot be shared at all, say so and describe how it
was produced (the Producer and Creator fields in Document › Properties), which
can still point to the cause.

Before filing, search the existing issues; add details to an open issue rather
than opening a duplicate.

### Security issues

For anything that could compromise a user, such as a crafted PDF that executes
code, a flaw in password handling, or a signature that validates when it should
not, please use GitHub's private vulnerability reporting on the repository's
Security tab instead of a public issue.

## Suggesting features

Feature requests are welcome as issues. Describe the task you are trying to
accomplish rather than only the control you would like to see; there may be a
better fit with the existing tools. The current checklist and roadmap are in
[docs/FEATURES.md](docs/FEATURES.md).

## Submitting changes

All changes come in as pull requests against `main`.

1. Fork the repository and create a branch for the change.
2. Set up a development environment:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   ```

3. Make the change, with tests where the behaviour can be tested.
4. Check lint and run the test suite (UI tests run headless):

   ```bash
   .venv/bin/ruff check .
   .venv/bin/python -m pytest
   ```

5. If the change is user-visible, add a line to `CHANGELOG.md` under
   *Unreleased*, update `src/quirewright/help/USER_GUIDE.md` and
   `docs/FEATURES.md` if they are affected, and run
   `python scripts/extract_strings.py` so new strings reach the translation
   catalogues.
6. Open the pull request. Explain what the change does and why, link the issue
   it addresses, and include an example PDF when the change concerns a specific
   kind of document.

Keep pull requests focused: one bug fix or one feature each. Large changes are
easier to review when they are proposed in an issue first.

### Certifying your contribution

By opening a pull request you certify the
[Developer Certificate of Origin](https://developercertificate.org/): that you
wrote the change or otherwise have the right to submit it under
AGPL-3.0-or-later. Please add a `Signed-off-by:` line to each commit
(`git commit -s`). You remain responsible for what you submit, whatever tools
you used to produce it.

### Contributions made with AI assistance

Contributions produced with the help of AI tools are welcome. They are subject
to the same review as every other contribution: tested, understood by the
person submitting them, and accompanied by a pull request that explains the
change.

## Project structure

```
src/quirewright/
├── core/        PDF logic with no Qt dependency; fully unit-tested
│   ├── content/ lexer, object model, interpreter and writer for content streams
│   ├── document.py, docinfo.py, annotations.py, signing.py, ocr.py, fonts.py, ...
│   └── commands.py  undo stack (stream edits and document snapshots)
├── ui/          PySide6: canvas, main window, inspector, dialogs, theme, help
├── help/        the user guide shown in-app and published on the site
├── locale/      gettext catalogues (de, fr, es) and the .pot template
└── assets/      icons
tests/           pytest; UI tests use the offscreen Qt platform
packaging/       AppImage, Flatpak, desktop entry, AppStream metadata
site/, scripts/  project site sources and helper scripts
```

How editing works is described in the README under *Architecture*. The two
rules that matter most when touching `core/content`:

- edits are **span replacements** in the original content stream, so untouched
  bytes stay untouched and the page renders identically elsewhere;
- every change goes through the undo stack (`ContentEditCommand` for stream
  edits, `SnapshotCommand` for structural changes).

## Coding standards

- Python 3.11+, type hints on all public functions, `from __future__ import
  annotations` at the top of modules.
- `ruff` is the linter and import sorter; its configuration is in
  `ruff.toml` (line length 140). A clean `ruff check .` is required.
- `core/` must not import Qt. Anything that can be tested without a window
  belongs there, with tests in `tests/`.
- UI code uses the existing theme (`ui/theme.py`), icon set and widget styles;
  do not hard-code colours or fonts in widgets.
- Every user-visible string goes through `tr()` (or `N_()` for strings that are
  translated later), including menu text, tooltips and status messages.
- Coordinates: PDF user space is y-up; the canvas scene is PyMuPDF page space,
  y-down. Convert with the helpers in `core/document.py` and `ui/canvas.py`
  rather than by hand.
- New document features need a user guide section and, where it fits, a line
  in the feature checklist.
- Commit messages: a short imperative summary line, then a blank line and the
  reasoning if it is not obvious.

## Translations

Catalogues live in `src/quirewright/locale/<lang>/LC_MESSAGES/quirewright.po`.
To add or update a language:

```bash
python scripts/extract_strings.py       # refresh the .pot template
# edit or create the .po file (Poedit or any editor)
python scripts/compile_catalogs.py      # build .mo files
```

Then start Quirewright with `--lang <code>` or choose the language in
Edit › Preferences and check the dialogs you touched.

## Conduct

Be courteous and constructive in issues and reviews. Maintainers may close or
edit contributions that do not follow these guidelines.
