# Changelog

## Unreleased

### Changed
- The project is now **Quirewright** (package `quirewright`, app id `io.github.quirewright.Quirewright`). Settings from the pre-release name are migrated on first start.
- New icon (a quire of folded sheets with an awl; oxblood, parchment and brass) and an oxblood UI accent.

### Added
- Signature Field tool (G) with a visible 'sign here' placeholder, editable caption and colours, and a Sign-this-field shortcut in the Inspector
- Digital signatures via pyHanko: sign (invisible / visible / existing field), self-signed certificate creation, signature verification with a personal trust store, signature fields in the form tool
- French and Spanish translations
- Complete German translation
- AppImage build script, Flatpak manifest, AppStream metadata
- GitHub Actions CI: lint + tests on Linux/Windows/macOS, AppImage and Flatpak builds, release artefacts
- Form field calculations, number/percent/date formats and range validation (Acrobat-compatible scripts), evaluated locally
- OCR text layer via Tesseract (Document › Recognize Text)
- Interface translations (gettext) with a German catalogue and a language preference
- Group / ungroup (groups are form XObjects) and editing inside form XObjects, nested
- Document tabs
- Rulers, draggable guides, grid, and smart snapping to page edges, objects, guides and grid (Alt bypasses)
- Continuous multi-page scrolling view (toggle in the View menu)
- In-app help viewer with contents and search (F1)
- Paragraph editing with re-wrapping (Ctrl+E) and multi-line text boxes (drag with the Text tool)
- Curves in the Pen tool (click-drag for handles)
- Page labels dialog
- Radio buttons
- Document properties dialog (metadata editing, file details)
- Security dialog: passwords, permissions, AES-256; remove security
- Resources dialog: browse and extract images, fonts and attachments; attach / remove files
- Bookmarks panel with add / rename / delete
- Find text with highlighting across pages
- Comments: highlight, underline, strike-out, sticky notes; edit in the Inspector; flatten
- Crop tool, redact tool, page numbers, watermarks
- Export pages as PNG / JPEG / SVG, export text, print, reduced-size copies
- Duplicate, bring to front / send to back, flip, rotate, align, distribute, copy text
- Welcome screen, go-to-page entry, preferences (theme, units, author, stroke scaling)
- Desktop launcher and icon

### Fixed
- Push-button captions set from the Inspector were not stored (parameter name collision)
- Crop by margins trimmed the wrong edge (top/bottom swapped)
