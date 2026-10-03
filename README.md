# Quirewright

<img src="src/quirewright/assets/quirewright.svg" width="96" align="right" alt="Quirewright icon">

A free and open-source PDF editor that combines **vector-level editing of page
content** (in the spirit of Inkscape) with **page management** (rotate, reorder,
delete, insert, extract, split, crop). Linux native, built on cross-platform
libraries so Windows and macOS ports are straightforward.

> **Quirewright**: a *quire* is a gathering of folded sheets, the basic unit of
> a bound book; a *wright* is a maker. A craftsman who assembles gathered
> pages, which is what this tool does.

## Features (first pass)

**Object editing** – every path, text run, image and form XObject on a page is
selectable directly on the rendered page:

- select (click, Shift+click, rubber band), move by dragging or arrow keys
- resize with handles (corners keep aspect ratio; hold Shift to stretch)
- rotate and set exact position/size from the Inspector
- edit path nodes and bezier control handles (Node tool, or double-click a shape)
- change fill / stroke colour, toggle fill or stroke, set stroke width
- edit text in place (Text tool, double-click, F2 or Enter): the whole visual
  line is edited even when the PDF splits it into several runs; size and colour
- draw new rectangles, ellipses, lines and polylines (Pen tool), add new text,
  insert images; defaults for new objects live in the Inspector
- delete objects
- full undo/redo

Edits are written back into the page's content stream, so the rest of the
page is untouched byte-for-byte and the result renders identically in every
viewer.

**Page management** – thumbnails panel with drag-to-reorder, multi-select and a
context menu:

- rotate 90°/180°, delete, duplicate, move up/down, reverse order
- insert blank pages (common paper sizes) or pages from another PDF (any range)
- extract pages to a new file, split the document into chunks
- crop pages by margins (non-destructive, resettable)
- open encrypted PDFs, save / save as, recent files, drag-and-drop to open

**Comments** – highlight, underline and strike out text, add sticky notes;
edit author, text, colour and opacity in the Inspector; flatten when done.

**Signatures** – sign with a PKCS#12 certificate (or create a self-signed
one), invisible or as a visible stamp or in a signature field; verify
signatures and manage a personal trust store.

**Document** – edit metadata (title, author, keywords, dates); set or remove
passwords and permissions (AES-256); browse and extract images, fonts and
attachments; attach files; find text across pages; bookmarks panel; page
numbers, watermarks, redaction; export pages as PNG/JPEG/SVG or text; print;
save a reduced-size copy.

**Forms** – create AcroForm fields (text, checkbox, radio, dropdown, list box,
push button) by dragging on the page; move, resize and delete them like any
object; edit name, value, options, caption, font size, colours, border and
flags (read-only, required, multiline) in the Inspector. Filling a form is just
selecting a field and typing its value.

**UI** – light and dark themes, consistent custom icons, Inspector panel with
contextual properties, welcome screen, configurable units, keyboard shortcuts
for every tool and command (Help › Keyboard Shortcuts), and a user guide in
[docs/USER_GUIDE.md](docs/USER_GUIDE.md). The feature checklist and roadmap
live in [docs/FEATURES.md](docs/FEATURES.md).

## Install & run

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/quirewright some-file.pdf
```

On Arch Linux the Qt bindings are also available as the `pyside6` package;
create the venv with `--system-site-packages` to reuse them.

Run the tests (the UI tests run headless with the `offscreen` Qt platform):

```bash
.venv/bin/python -m pytest
```

## Architecture

```
src/quirewright/
├── core/                 Qt-free: all PDF logic, fully unit-tested
│   ├── content/
│   │   ├── lexer.py      tokenizer for content streams and PDF object syntax
│   │   ├── model.py      GraphicsState, PathObject, TextRun, XObjectRef, ...
│   │   ├── interpreter.py  operators -> objects with byte spans & bboxes
│   │   └── writer.py     edits -> new content stream (span replacement)
│   ├── fonts.py          widths, encodings, ToUnicode, re-encoding of text
│   ├── encodings.py      Standard/WinAnsi/MacRoman tables, glyph names
│   ├── pdfobj.py         PDF object parser + reference resolver
│   ├── document.py       PyMuPDF wrapper: resources, render, page ops, save
│   ├── commands.py       undo stack (stream edits + document snapshots)
│   └── geometry.py       Matrix / Rect
└── ui/                   PySide6
    ├── canvas.py         page view, selection, tools, node editor, text editor
    ├── thumbnails.py     pages panel
    ├── properties.py     inspector
    ├── main_window.py    menus, toolbar, actions, dialogs wiring
    ├── dialogs.py        insert/extract/split/crop/password/about
    ├── theme.py          palette, stylesheet, built-in SVG icons
    └── render.py         PyMuPDF pixmap -> QPixmap, cache
```

### How editing works

1. The page's content stream is parsed by the **interpreter**, which tracks the
   full graphics state (`q`/`Q` stack, CTM, colours, line and text state) and
   emits one object per painting operation. Each object records the byte span
   that produced it, the state in effect, and the "base" state it will be
   diffed against when rewritten. When a `q … Q` pair contains exactly one
   object and only state operators, the object "owns" that wrapper and can be
   regenerated atomically.
2. The **writer** applies edits as span replacements:
   - paths: points are rewritten in the object's own user space (so transforms
     are exact under any CTM), wrapped in `q <state diff> … Q` when the style
     or CTM differs from the surrounding state;
   - images / form XObjects / shadings: a `cm` diff inside `q … Q`;
   - text: the enclosing `BT … ET` block is regenerated with an absolute `Tm`
     per run; untracked operators (marked content, `gs`, …) are copied verbatim
     in their original order, and the state at `ET` is restored so following
     content is unaffected.
3. The **document** layer writes the new stream (collapsing content arrays to a
   single stream on first edit), re-renders through MuPDF, and the canvas
   rebuilds its hit-test overlay. The rendered bitmap is always MuPDF's own
   output, so what you see is what every other viewer will see.

Text editing re-encodes the new string with the run's own font when every
character is available (via ToUnicode / the font's encoding). For subset fonts
only glyphs already used in the document exist; other characters fall back to
a built-in Helvetica resource added to the page, and the status bar says so.

### Coordinate systems

- *PDF user space*: origin bottom-left, y up (what content streams use).
- *Scene space*: PyMuPDF page space, origin top-left of the rotated, cropped
  page, y down, in points. `Document.pdf_to_page_matrix(page)` maps between
  them; the canvas converts screen transforms to PDF space with
  `S · M · S⁻¹`.

## Porting to Windows / macOS

Nothing in the code is Linux-specific: PySide6 and PyMuPDF both ship wheels for
all three platforms. Packaging with PyInstaller/briefcase is the expected route;
file dialogs, shortcuts (`QKeySequence.StandardKey`) and settings (`QSettings`)
already follow platform conventions.

## Translating

```bash
python scripts/extract_strings.py      # refresh src/quirewright/locale/quirewright.pot
cp src/quirewright/locale/quirewright.pot src/quirewright/locale/fr/LC_MESSAGES/quirewright.po   # new language
python scripts/compile_catalogs.py     # build .mo files
```

Then pick the language in Edit › Preferences.

## Licence

GNU Affero General Public License v3.0 or later (see `LICENSE`). PyMuPDF/MuPDF
are AGPL-licensed; Qt via PySide6 is LGPL.

## Packaging

**AppImage** (self-contained, any x86_64/aarch64 Linux):

```bash
pip install pyinstaller
packaging/build-appimage.sh          # -> dist/Quirewright-<version>-<arch>.AppImage
```

**Flatpak** (manifest in `packaging/flatpak`, built on Flathub's PySide base app):

```bash
flatpak install flathub org.flatpak.Builder org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
flatpak run org.flatpak.Builder --user --install --force-clean build-dir packaging/flatpak/io.github.quirewright.Quirewright.yml
flatpak run io.github.quirewright.Quirewright
```

**Desktop entry** for a source checkout: `packaging/install-desktop.sh`
installs a launcher and icon for the current user.

## Continuous integration

`.github/workflows/ci.yml` lints with ruff and runs the test suite on Linux,
Windows and macOS for Python 3.11 and 3.12, then builds the AppImage and the
Flatpak. Tagging `vX.Y.Z` attaches the AppImage to a GitHub release.

## Roadmap

See [docs/FEATURES.md](docs/FEATURES.md) for the full checklist. Everything on
it is implemented, including digital signatures (via pyHanko).
