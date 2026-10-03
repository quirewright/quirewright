#!/usr/bin/env python3
"""Take the screenshots used by the project site, headless.

    python scripts/site_screenshots.py demo.pdf site/static/img

Writes hero-light.png, hero-dark.png, nodes-light.png, forms-light.png and
help-light.png. Run with the demo document from scripts/make_demo_pdf.py.
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_cfg = tempfile.mkdtemp(prefix="quirewright-site-")
os.environ["XDG_CONFIG_HOME"] = _cfg
os.environ["XDG_DATA_HOME"] = _cfg

from PySide6.QtWidgets import QApplication  # noqa: E402

from quirewright.core.content.model import PathObject  # noqa: E402
from quirewright.ui import theme  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pdf, outdir = sys.argv[1], sys.argv[2]
    app = QApplication(sys.argv[:1])
    theme.apply_theme(app, False)
    from quirewright.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    win.open_file(pdf)
    canvas = win.canvas
    canvas.snap_enabled = False

    def pump(n: int = 10) -> None:
        for _ in range(n):
            app.processEvents()

    def shoot(widget, name: str) -> None:
        pump()
        widget.grab().save(os.path.join(outdir, name))
        print("saved", name)

    pump()
    # The wide, shallow stroked path on the first page is the trend curve.
    curve = None
    for item in canvas.items_by_id.values():
        obj, bb = item.obj, item.obj.visible_bbox
        if isinstance(obj, PathObject) and bb is not None and bb.width > 300 and 40 < bb.height < 200:
            curve = obj
    if curve is not None:
        canvas.select([curve.id])
    shoot(win, "hero-light.png")
    canvas.set_tool("node")
    shoot(win, "nodes-light.png")
    canvas.set_tool("select")

    win.toggle_dark(True, persist=False)
    shoot(win, "hero-dark.png")
    win.toggle_dark(False, persist=False)

    widgets = list(canvas.widget_items)
    if widgets:
        canvas.select_widgets([widgets[0]])
        shoot(win, "forms-light.png")
    canvas.select([])

    win.open_guide()
    win.help_window.resize(1100, 760)
    shoot(win.help_window, "help-light.png")


if __name__ == "__main__":
    main()
