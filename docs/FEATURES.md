# Feature checklist

What people expect from a desktop PDF editor, and where this project stands.
Checked items are implemented and covered by tests.

## Viewing & navigation
- [x] Open PDFs (including password-protected), drag-and-drop, recent files
- [x] Zoom (in/out/fit page/fit width/actual size, Ctrl+wheel), pan (Hand tool, middle mouse)
- [x] Page thumbnails with multi-select and drag-to-reorder
- [x] Go to page by number, first/previous/next/last
- [x] Outline (bookmarks) panel with add/rename/delete
- [x] Find text (Ctrl+F) with hit highlighting and next/previous across pages
- [x] Light and dark themes, system theme detection
- [x] Welcome screen when no document is open
- [x] Continuous (multi-page) scrolling view (single-page mode available)
- [x] Tabs for several open documents

## Content editing (Inkscape-like)
- [x] Select objects on the rendered page (click, Shift+click, rubber band)
- [x] Move, resize with handles, rotate, exact geometry in the Inspector
- [x] Edit path nodes and bezier handles
- [x] Fill / stroke colour, stroke width, toggle fill or stroke
- [x] Edit text in place (whole visual line), size, colour; font substitution when glyphs are missing
- [x] Draw rectangles, ellipses, lines, polylines; add text; insert images
- [x] Duplicate, bring to front / send to back, flip horizontal / vertical
- [x] Align (left/centre/right/top/middle/bottom) and distribute multiple objects
- [x] Copy selected text to the clipboard
- [x] Nudge with arrow keys, delete, undo/redo for everything
- [x] Multi-line text boxes with wrapping; paragraph editing with re-wrap
- [x] Curves in the Pen tool (click-drag for handles)
- [x] Grouping (as form XObjects) and editing inside any form XObject, nested
- [x] Snapping to page, objects, guides and grid; rulers; draggable guides

## Pages
- [x] Rotate, delete, duplicate, move, reverse order
- [x] Insert blank pages (paper sizes) or pages from another PDF (ranges)
- [x] Extract pages to a file, split document into chunks
- [x] Crop by margins, crop to a dragged rectangle, reset crop
- [x] Add page numbers (position, format, start value, range)
- [x] Add a text watermark (opacity, rotation, size, colour)
- [x] Export a page as PNG / JPEG / SVG
- [x] Page labels (roman numerals, letters, prefixes)
- [ ] N-up / booklet imposition

## Forms
- [x] Create text fields, checkboxes, radio buttons, dropdowns, list boxes, push buttons
- [x] Move, resize, delete fields; edit name, value, options, fonts, colours, flags
- [x] Fill forms (set values)
- [x] Flatten forms and annotations into page content
- [x] Radio buttons (shared name = group; created via a checkbox workaround for a PyMuPDF limitation)
- [x] Calculation, format and validation scripts (Acrobat-compatible), evaluated locally for preview

## Annotations (comments)
- [x] Highlight, underline, strike-out text (drag over words)
- [x] Sticky notes with editable contents and colour
- [x] Select, move (notes), delete annotations; flatten
- [ ] Free-hand ink, shapes, free text, stamps, replies

## Document
- [x] Metadata editing (title, author, subject, keywords, creator, producer, dates)
- [x] Security: set user/owner passwords, permissions, AES-256; remove security
- [x] Resources browser: images, fonts, attachments — extract any of them
- [x] Attach files to the document, remove attachments
- [x] Reduce file size (garbage collection, stream compression, image recompression)
- [x] Redact an area (removes underlying text and images)
- [x] Print
- [ ] Digital signatures / certificates (out of scope for now)
- [x] OCR via Tesseract (invisible text layer)

## Quality of life
- [x] Keyboard shortcuts for every tool; shortcut reference dialog; in-app help viewer (F1)
- [x] Preferences: theme, units (pt / mm / in), stroke scaling
- [x] Status bar hints per tool, unsaved-changes guard, save-in-place safety (atomic write)
- [x] Desktop integration files (launcher, icon)
- [ ] Autosave / crash recovery
- [x] Localisation (gettext; German sample catalogue; Qt dialog translations)
