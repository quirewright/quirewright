# User guide

PDF Editor (working title) edits the *content* of PDF pages the way a vector
drawing program edits shapes, and manages pages, forms and comments the way a
PDF tool does. This guide walks through the interface and every feature.

## The window

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Menu bar                                                                  │
│ Toolbar: file · undo/redo · tools · drawing · fields · comments · zoom … │
├────────────┬──────────────────────────────────────────┬──────────────────┤
│ Navigation │ Find bar (Ctrl+F)                        │ Inspector        │
│  Pages     │                                          │  page info, or   │
│  Bookmarks │              page canvas                 │  properties of   │
│            │                                          │  the selection   │
├────────────┴──────────────────────────────────────────┴──────────────────┤
│ Status bar: messages                                      hints per tool │
└──────────────────────────────────────────────────────────────────────────┘
```

* **Navigation** (left): page thumbnails you can multi-select and drag to
  reorder, and a Bookmarks tab for the document outline.
* **Canvas** (centre): one page at a time, rendered exactly as other viewers
  render it. Everything on it can be selected.
* **Inspector** (right): shows details for whatever is selected and lets you
  change them. With nothing selected it shows page and document information,
  or the style for new objects when a drawing tool is active.

Both side panels can be hidden from the View menu or the toolbar.

## Opening, saving, security

* **Open**: File › Open, drag a PDF onto the window, the welcome screen, or
  pass a path on the command line (`pdfeditor file.pdf`).
* Encrypted files ask for their password.
* **Save** writes to the same file atomically (a temporary file is written
  first and then swapped in). **Save As** writes elsewhere.
* **Save Reduced Size Copy** rewrites images at up to 150 dpi, recompresses
  streams and removes unused objects.
* **Document › Security** sets an *open password* (needed to open the file),
  an *owner password* (needed to change permissions) and the permissions
  granted to readers. Choose "No password or restrictions" to remove existing
  security. Changes take effect when you save.
* **Document › Properties** edits title, author, subject, keywords, creator,
  producer and dates, and shows file details (PDF version, size, encryption,
  attachments, whether the file contains a form).

## Selecting and editing objects

Use the **Select** tool (S):

| Action | How |
|---|---|
| Select | click an object; Shift+click adds or removes; drag on empty space for a rubber band; Ctrl+A selects all |
| Move | drag the selection, or use the arrow keys (Shift = 10 pt) |
| Resize | drag a handle; corners keep the aspect ratio, hold Shift to stretch freely |
| Rotate | enter an angle in the Inspector, or Object › Rotate Selection 90° |
| Exact geometry | type X, Y, W, H in the Inspector (units are configurable in Preferences) |
| Colours | Inspector › Fill & Stroke: toggle fill/stroke, pick colours, set stroke width |
| Duplicate | Ctrl+Shift+D |
| Order | Object › Bring to Front / Send to Back |
| Align / distribute | Object › Align (a single object aligns to the page) |
| Flip | Object › Flip Horizontal / Vertical |
| Copy text | Ctrl+C copies the text of selected text objects |
| Delete | Delete or Backspace |

Everything is undoable (Ctrl+Z / Ctrl+Shift+Z).

### Editing text

Double-click a line of text, press Enter or F2 with it selected, or use the
**Text** tool (T) and click it. An inline editor opens with the whole visual
line (PDFs often split lines into several pieces; the editor merges them).
Enter applies, Esc cancels. The Inspector also offers a text field, size and
colour.

Text is re-encoded with the document's own font whenever possible. Embedded
fonts are usually *subsets* that only contain the glyphs already used in the
file; if you type a character the subset lacks, the editor substitutes a
built-in font with the same weight and style and tells you in the status bar.

### Editing shapes (nodes)

Double-click a shape, or select it and press N, to enter the **Node** tool.
Square handles are anchor points, circles are bezier control points; drag
them. Esc returns to the Select tool.

## Creating objects

| Tool | Key | Use |
|---|---|---|
| Rectangle | R | drag; Shift for a square |
| Ellipse | E | drag; Shift for a circle |
| Line | L | drag; Shift snaps to 45° |
| Pen | P | click to add points; Enter or double-click finishes, clicking the first point closes the shape; Esc cancels |
| Text | T | click on empty space, type, Enter |
| Image | Ctrl+Shift+M | choose a file; it is placed in the middle of the view, then move/resize it |

With a drawing tool active and nothing selected, the Inspector shows the
**New object style**: fill, stroke, width, font, size and text colour.

## Pages

Right-click a thumbnail or use the Page menu:

* Rotate 90°/180°, delete, duplicate, move up/down, reverse the order, or drag
  thumbnails to reorder (multi-select works).
* **Insert Blank Page** offers common paper sizes; **Insert Pages from File**
  takes any page range from another PDF.
* **Extract Pages** saves chosen pages to a new file; **Split Document**
  writes the document as files of N pages each.
* **Crop**: use the Crop tool (C) and drag a rectangle, or Crop by Margins.
  Cropping hides content outside the box; **Reset Crop** restores it.
* **Add Page Numbers** and **Add Watermark** stamp text on a range of pages.
* **Export › Page as Image** writes PNG, JPEG or SVG; **Export › Text**
  writes the plain text of all pages.

## Forms

Use the form-field toolbar button (F) or Insert › Form Field to add text
fields, checkboxes, radio buttons, dropdowns, list boxes and push buttons:
drag to size the field, or click for a default size. Fields are selected,
moved, resized and deleted like other objects. The Inspector edits the field's
name, value, options, caption, font size, colours, border and flags
(read-only, required, multiline). Filling a form is just selecting a field
and typing its value.

**Document › Flatten** bakes fields and comments into the page content.

## Comments

Insert › Comment (or the comment toolbar button): **Highlight**, **Underline**
and **Strike Out** work by dragging a rectangle over words; **Sticky Note**
places a note where you click. Select a comment to edit its author, text,
icon, colour and opacity in the Inspector, move notes by dragging, and delete
with the Delete key. Set your name under Edit › Preferences so new comments
carry it.

## Find

Ctrl+F opens the find bar. Matches are highlighted on the page; Enter and
Shift+Enter move between them across all pages.

## Resources and attachments

**Document › Resources** lists every image (with preview), font (with its type
and whether it is embedded) and attachment in the file. Select rows and
extract them to disk; attach new files or remove attachments from the same
dialog, or use Document › Attach File.

## Redaction

Document › Redact Area: drag a rectangle; after confirmation the text and
images inside it are removed from the page (not just covered) and the area is
painted black. This is destructive by design; undo is available until you
save.

## Preferences

Edit › Preferences: theme (system, light, dark), units for the Inspector
(points, millimetres, centimetres, inches), whether stroke widths scale when
you resize objects, your name for comments, and the zoom used when a file is
opened.

## Keyboard shortcuts

Help › Keyboard Shortcuts lists everything. The most used:

| Keys | Command |
|---|---|
| Ctrl+O / Ctrl+S / Ctrl+P | open / save / print |
| Ctrl+Z / Ctrl+Shift+Z | undo / redo |
| S, N, T, H | Select, Node, Text, Hand tools |
| R, E, L, P | Rectangle, Ellipse, Line, Pen tools |
| F, C | Form field, Crop tools |
| Ctrl+F | find |
| Ctrl+G | go to page; PgUp / PgDn previous / next page |
| Ctrl+0 / Ctrl+1 / Ctrl+2 | fit page / actual size / fit width |
| Ctrl+I | document properties |
| Ctrl+Shift+O | resources (images, fonts, attachments) |
| Ctrl+/ | keyboard shortcut reference |
| Ctrl+Shift+D | duplicate selection |
| Ctrl+Shift+] / [ | bring to front / send to back |
| Ctrl+R / Ctrl+Shift+R | rotate page clockwise / counter-clockwise |
| Esc | cancel editing, or back to the Select tool |

## Installing a launcher (Linux)

```bash
packaging/install-desktop.sh
```

installs a desktop entry and icon for the current user so the editor appears
in application menus and can be chosen for PDF files.
