"""Visual theme: palette, stylesheet and a small built-in icon set.

The app uses the Fusion style as a neutral base and layers a stylesheet on top
so it looks the same on every desktop. Icons are simple stroke-based SVGs
tinted to the current text colour, so they stay crisp at any DPI and in both
light and dark mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


@dataclass
class Theme:
    dark: bool
    window: str
    panel: str
    panel_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    canvas: str
    selection: str
    hover: str
    handle_fill: str
    danger: str

    def qcolor(self, name: str) -> QColor:
        return QColor(getattr(self, name))


LIGHT = Theme(
    dark=False,
    window="#f3f4f6",
    panel="#ffffff",
    panel_alt="#f9fafb",
    border="#e2e5ea",
    text="#1f2937",
    text_muted="#6b7280",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_text="#ffffff",
    accent_soft="rgba(37, 99, 235, 0.12)",
    canvas="#e5e7eb",
    selection="#2563eb",
    hover="#60a5fa",
    handle_fill="#ffffff",
    danger="#dc2626",
)

DARK = Theme(
    dark=True,
    window="#1b1d21",
    panel="#24272d",
    panel_alt="#2a2e35",
    border="#363a43",
    text="#e5e7eb",
    text_muted="#9ca3af",
    accent="#3b82f6",
    accent_hover="#60a5fa",
    accent_text="#ffffff",
    accent_soft="rgba(96, 165, 250, 0.18)",
    canvas="#121417",
    selection="#60a5fa",
    hover="#93c5fd",
    handle_fill="#1b1d21",
    danger="#f87171",
)

_current: Theme = LIGHT


def current() -> Theme:
    return _current


def system_prefers_dark() -> bool:
    try:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        pal = QGuiApplication.palette()
        return pal.color(QPalette.ColorRole.Window).lightness() < 128


def build_stylesheet(t: Theme) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {t.window}; }}
    QWidget {{ color: {t.text}; font-size: 13px; }}
    QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px; border-radius: 4px; }}

    QMenuBar {{ background: {t.window}; border-bottom: 1px solid {t.border}; padding: 2px 4px; }}
    QMenuBar::item {{ padding: 4px 8px; border-radius: 4px; }}
    QMenuBar::item:selected {{ background: {t.panel_alt}; }}
    QMenu {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 6px; padding: 6px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu::item:disabled {{ color: {t.text_muted}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

    QToolBar {{ background: {t.window}; border: none; border-bottom: 1px solid {t.border}; padding: 4px 6px; spacing: 2px; }}
    QToolBar::separator {{ width: 1px; background: {t.border}; margin: 6px 6px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px; }}
    QToolButton:hover {{ background: {t.panel_alt}; border-color: {t.border}; }}
    QToolButton:pressed {{ background: {t.border}; }}
    QToolButton:checked {{ background: {t.accent}; color: {t.accent_text}; }}
    QToolButton:disabled {{ color: {t.text_muted}; }}
    QToolButton::menu-indicator {{ image: none; }}

    QDockWidget {{ background: {t.panel}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
    QDockWidget::title {{ background: {t.panel}; padding: 8px 10px; border-bottom: 1px solid {t.border}; font-weight: 600; text-align: left; }}
    QDockWidget > QWidget {{ background: {t.panel}; }}

    QStatusBar {{ background: {t.window}; border-top: 1px solid {t.border}; color: {t.text_muted}; }}
    QStatusBar::item {{ border: none; }}

    QListWidget {{ background: {t.panel}; border: none; outline: none; padding: 8px; }}
    QListWidget::item {{ color: {t.text_muted}; border-radius: 6px; padding: 6px 2px; }}
    QListWidget::item:hover {{ background: {t.panel_alt}; }}
    QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.accent}; border: 1px solid {t.accent}; }}

    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.text_muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t.text_muted}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px 8px;
        selection-background-color: {t.accent}; selection-color: {t.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {t.text_muted}; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {t.panel}; border: 1px solid {t.border}; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}

    QPushButton {{ background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {t.text_muted}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:default, QPushButton[primary="true"] {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QPushButton:default:hover, QPushButton[primary="true"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[danger="true"] {{ color: {t.danger}; }}
    QPushButton:disabled {{ color: {t.text_muted}; }}

    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QGroupBox {{ border: 1px solid {t.border}; border-radius: 8px; margin-top: 12px; padding: 10px 6px 6px 6px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {t.text_muted}; }}

    QLabel[role="heading"] {{ font-size: 12px; font-weight: 600; color: {t.text_muted}; letter-spacing: 0.5px; text-transform: uppercase; }}
    QLabel[role="muted"] {{ color: {t.text_muted}; }}
    QLabel[role="title"] {{ font-size: 15px; font-weight: 600; }}
    QFrame[role="card"] {{ background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 8px; }}
    QFrame[role="hline"] {{ background: {t.border}; max-height: 1px; min-height: 1px; border: none; }}
    QSplitter::handle {{ background: {t.border}; }}
    QTabBar::tab {{ padding: 6px 12px; }}
    QMessageBox {{ background: {t.panel}; }}
    """


def apply_theme(app: QApplication, dark: bool | None = None) -> Theme:
    global _current
    if dark is None:
        dark = system_prefers_dark()
    t = DARK if dark else LIGHT
    _current = t
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.window))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.panel))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.panel_alt))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Button, QColor(t.panel_alt))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.panel))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.text_muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.text_muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.text_muted))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(t))
    _icon_cache.clear()
    return t


# --- icons ---------------------------------------------------------------

# 24x24 viewBox, stroke-based (currentColor), inspired by common open icon sets.
_ICON_PATHS: dict[str, str] = {
    "select": '<path d="M5 3l14 8-6 2-3 6z"/>',
    "node": '<path d="M4 18L12 6l8 12"/><rect x="2" y="16" width="4" height="4" rx="1"/><rect x="10" y="4" width="4" height="4" rx="1"/><rect x="18" y="16" width="4" height="4" rx="1"/>',
    "text": '<path d="M5 5h14M12 5v14M9 19h6"/>',
    "hand": '<path d="M18 11V7a1.5 1.5 0 0 0-3 0M15 10V5a1.5 1.5 0 0 0-3 0v5M12 10V6a1.5 1.5 0 0 0-3 0v8L6.5 11.5a1.6 1.6 0 0 0-2.3 2.2L8 19a5 5 0 0 0 4 2h2a5 5 0 0 0 5-5v-5a1.5 1.5 0 0 0-3 0"/>',
    "zoom-in": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5M11 8v6M8 11h6"/>',
    "zoom-out": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5M8 11h6"/>',
    "zoom-fit": '<path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"/><rect x="8" y="8" width="8" height="8" rx="1"/>',
    "zoom-width": '<path d="M3 12h18M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "new": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v6M9 15h6"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    "undo": '<path d="M3 7v6h6"/><path d="M3.5 13a9 9 0 1 1 2.6 6.4"/>',
    "redo": '<path d="M21 7v6h-6"/><path d="M20.5 13a9 9 0 1 0-2.6 6.4"/>',
    "rotate-left": '<path d="M3 4v6h6"/><path d="M3.5 10a9 9 0 1 1 2.1 9.4"/>',
    "rotate-right": '<path d="M21 4v6h-6"/><path d="M20.5 10a9 9 0 1 0-2.1 9.4"/>',
    "trash": '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1L5 6M10 11v6M14 11v6"/>',
    "add-page": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 11v6M9 14h6"/>',
    "duplicate": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "pages": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "inspector": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "extract": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
    "insert": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    "reverse": '<path d="M7 16V4M7 4L3 8M7 4l4 4M17 8v12M17 20l4-4M17 20l-4-4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "split": '<path d="M4 4h6v6H4zM14 14h6v6h-6z"/><path d="M10 7h4M14 17h-4"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "path": '<path d="M4 20c4-12 12-12 16 0"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/>',
    "shape": '<rect x="4" y="4" width="16" height="16" rx="3"/>',
    "font": '<path d="M4 20l6-16h4l6 16M7 14h10"/>',
    "edit": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "close": '<path d="M18 6L6 18M6 6l12 12"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    "more": '<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>',
}

_icon_cache: dict[tuple[str, str, int], QIcon] = {}


def icon_svg(name: str, color: str, stroke_width: float = 1.8) -> bytes:
    body = _ICON_PATHS.get(name, _ICON_PATHS["more"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    return svg.encode()


def _render(name: str, color: str, px: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color)))
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    return QPixmap.fromImage(img)


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    t = current()
    color = color or t.text
    key = (name, color, size)
    ic = _icon_cache.get(key)
    if ic is not None:
        return ic
    ic = QIcon()
    for px in (size, size * 2, size * 3):
        ic.addPixmap(_render(name, color, px), QIcon.Mode.Normal, QIcon.State.Off)
    # checked/active variants in accent text colour
    for px in (size, size * 2, size * 3):
        ic.addPixmap(_render(name, t.accent_text, px), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_render(name, t.accent_text, px), QIcon.Mode.Active, QIcon.State.On)
        ic.addPixmap(_render(name, t.text_muted, px), QIcon.Mode.Disabled, QIcon.State.Off)
    _icon_cache[key] = ic
    return ic


def icon_size() -> QSize:
    return QSize(20, 20)
