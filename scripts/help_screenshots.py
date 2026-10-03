#!/usr/bin/env python3
"""Capture the annotated window screenshot used in the user guide, headless.

    python scripts/help_screenshots.py demo.pdf src/quirewright/help/window.png

Numbered callouts mark the parts of the window that the guide's "The window"
section describes. Use the demo document from scripts/make_demo_pdf.py.
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_cfg = tempfile.mkdtemp(prefix="quirewright-help-")
os.environ["XDG_CONFIG_HOME"] = _cfg
os.environ["XDG_DATA_HOME"] = _cfg

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabBar, QWidget  # noqa: E402

from quirewright.ui import theme  # noqa: E402

ACCENT = QColor("#7a1f2b")


def rect_in(win: QWidget, w: QWidget) -> QRect:
    return QRect(w.mapTo(win, QPoint(0, 0)), w.size())


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    pdf, out = sys.argv[1], sys.argv[2]
    app = QApplication(sys.argv[:1])
    theme.apply_theme(app, False)
    from quirewright.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    win.open_file(pdf)
    win.canvas.snap_enabled = False
    win.show_find()
    for _ in range(15):
        app.processEvents()

    view = win.view
    tabbar = win.tabs.findChild(QTabBar)
    parts = [
        ("1", win.menuBar()),
        ("2", win.toolbar),
        ("3", win.pages_dock),
        ("4", tabbar),
        ("5", view.findbar),
        ("6", view.hruler),
        ("7", view.canvas),
        ("8", win.props_dock),
        ("9", win.statusBar()),
    ]
    shot = win.grab().toImage()
    margin = 48
    image = QImage(shot.width() + 2 * margin, shot.height() + 2 * margin, QImage.Format.Format_ARGB32)
    image.fill(QColor("#f6ecd6"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawImage(margin, margin, shot)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(16)
    painter.setFont(font)
    # Badges sit in the margins so they never cover the interface; a short line
    # leads to the outlined part. Panels on the left get left-hand badges.
    left_side = {win.menuBar(), win.toolbar, win.pages_dock, win.statusBar()}
    fb = view.findbar
    inside = {
        # empty spots inside the interface: right of the last tab, the gap in the
        # find bar before its arrows, the corner square between the rulers, and
        # the grey margin of the canvas left of the page
        tabbar: (lambda r: (r.right() - 22, r.center().y())),
        fb: (lambda r: ((rect_in(win, fb.case).right() + rect_in(win, fb.prev_btn).left()) // 2 + margin, r.center().y())),
        view.hruler: (lambda r: (r.left() - 12, r.center().y())),
        view.canvas: (lambda r: (r.left() + 22, r.top() + 22)),
    }
    for label, widget in parts:
        r = rect_in(win, widget).translated(margin, margin)
        painter.setPen(QPen(ACCENT, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(r.adjusted(1, 1, -2, -2), 4, 4)
        if widget in inside:
            cx, cy = inside[widget](r)
        else:
            cy = r.top() + 16 if r.height() > 60 else r.center().y()
            cx = margin // 2 if widget in left_side else image.width() - margin // 2
            painter.drawLine(cx, cy, r.left() if widget in left_side else r.right(), cy)
        badge = QRect(cx - 14, cy - 14, 28, 28)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(ACCENT)
        painter.drawEllipse(badge)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    image.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
