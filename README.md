# PDF Editor (working title)

A free and open-source PDF editor that combines **vector-level editing of page
content** (in the spirit of Inkscape) with **page management** (rotate, reorder,
delete, insert, extract, split, crop). Linux native, built on cross-platform
libraries so Windows and macOS ports are straightforward.

> The name "PDF Editor" / package `pdfeditor` is a placeholder. The final name
> is set in one place: `APP_NAME` in `src/pdfeditor/__init__.py` (plus the
> package directory and `pyproject.toml`).

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

**Forms** – create AcroForm fields (text, checkbox, radio, dropdown, list box,
push button) by dragging on the page; move, resize and delete them like any
object; edit name, value, options, caption, font size, colours, border and
flags (read-only, required, multiline) in the Inspector. Filling a form is just
selecting a field and typing its value.

**UI** – light and dark themes, consistent custom icons, Inspector panel with
contextual properties, keyboard shortcuts for every tool and command.

## Install & run

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pdfeditor some-file.pdf
```

On Arch Linux the Qt bindings are also available as the `pyside6` package;
create the venv with `--system-site-packages` to reuse them.

Run the tests (the UI tests run headless with the `offscreen` Qt platform):

```bash
.venv/bin/python -m pytest
```

## Architecture

```
src/pdfeditor/
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

## Licence

GNU Affero General Public License v3.0 or later (see `LICENSE`). PyMuPDF/MuPDF
are AGPL-licensed; Qt via PySide6 is LGPL.

## Roadmap

- multi-line text boxes with wrapping; bezier drawing in the Pen tool
- grouping, z-order changes, alignment & distribution
- editing inside form XObjects
- annotations, forms, OCR, redaction
- continuous multi-page view, background rendering, print
