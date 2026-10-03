"""Visual theme: palette, stylesheet and a small built-in icon set.

The app uses the Fusion style as a neutral base and layers a stylesheet on top
so it looks the same on every desktop. Icons are simple stroke-based SVGs
tinted to the current text colour, so they stay crisp at any DPI and in both
light and dark mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QTimer, Signal, Slot
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
    # Brand: oxblood. (Previous neutral blue: accent #2563eb, hover #1d4ed8, selection #2563eb, hover line #60a5fa.)
    accent="#7a1f2b",
    accent_hover="#641822",
    accent_text="#ffffff",
    accent_soft="rgba(122, 31, 43, 0.12)",
    canvas="#e7e3dc",
    selection="#7a1f2b",
    hover="#b8862b",
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
    # Brand: oxblood lifted for dark backgrounds. (Previous blue: accent #3b82f6, hover #60a5fa, selection #60a5fa, hover line #93c5fd.)
    accent="#c0404f",
    accent_hover="#d4525f",
    accent_text="#ffffff",
    accent_soft="rgba(192, 64, 79, 0.2)",
    canvas="#121417",
    selection="#d4525f",
    hover="#d4a94a",
    handle_fill="#1b1d21",
    danger="#f87171",
)

_current: Theme = LIGHT


def current() -> Theme:
    return _current


def _portal_color_scheme() -> int | None:
    """0 = no preference, 1 = prefer dark, 2 = prefer light (freedesktop settings portal)."""
    try:
        from PySide6 import QtDBus

        bus = QtDBus.QDBusConnection.sessionBus()
        if not bus.isConnected():
            return None
        iface = QtDBus.QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings", bus)
        reply = iface.call("ReadOne", "org.freedesktop.appearance", "color-scheme")
        args = reply.arguments()
        if not args:
            return None
        v = args[0]
        while hasattr(v, "variant"):
            v = v.variant()
        return int(v)
    except Exception:
        return None


def _gsettings_color_scheme() -> int | None:
    try:
        import subprocess

        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], capture_output=True, text=True, timeout=2).stdout
        if "prefer-dark" in out:
            return 1
        if "prefer-light" in out:
            return 2
        if "default" in out:
            return 0
    except Exception:
        pass
    return None


def system_prefers_dark() -> bool:
    """Best-effort detection of the desktop's colour scheme.

    Order: Qt's own hint (works with a platform theme), the freedesktop settings
    portal (GNOME, KDE, sway...), gsettings, and finally the palette lightness.
    """
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    for probe in (_portal_color_scheme, _gsettings_color_scheme):
        v = probe()
        if v is not None:
            return v == 1
    try:
        return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return False


class SystemThemeWatcher(QObject):
    """Emits ``changed(bool dark)`` when the desktop switches between light and dark."""

    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last = system_prefers_dark()
        self._dbus_ok = False
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._recheck)
        except Exception:
            pass
        try:
            from PySide6 import QtDBus

            bus = QtDBus.QDBusConnection.sessionBus()
            if bus.isConnected():
                self._dbus_ok = bus.connect("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                            "org.freedesktop.portal.Settings", "SettingChanged", self, "_on_setting_changed(QString,QString,QDBusVariant)")
        except Exception:
            self._dbus_ok = False
        # Fallback for desktops without a portal: poll occasionally.
        self._timer = QTimer(self)
        self._timer.setInterval(5000 if not self._dbus_ok else 60000)
        self._timer.timeout.connect(self._recheck)
        self._timer.start()

    @Slot(str, str, "QDBusVariant")
    def _on_setting_changed(self, namespace: str, key: str, value) -> None:
        if namespace == "org.freedesktop.appearance" and key == "color-scheme":
            self._recheck()

    @Slot()
    def _recheck(self) -> None:
        dark = system_prefers_dark()
        if dark != self._last:
            self._last = dark
            self.changed.emit(dark)


def theme_mode_to_dark(mode: str) -> bool:
    """Resolve a preference ("system" / "light" / "dark") to a concrete choice."""
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return system_prefers_dark()


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

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {{
        background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 5px 8px; min-height: 22px;
        selection-background-color: {t.accent}; selection-color: {t.accent_text};
    }}
    QPlainTextEdit, QTextEdit {{ background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {t.text_muted}; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {t.panel}; border: 1px solid {t.border}; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}

    QPushButton {{ background: {t.panel_alt}; border: 1px solid {t.border}; border-radius: 6px; padding: 6px 14px; min-height: 20px; }}
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
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1.5"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "line": '<path d="M5 19L19 5"/><circle cx="5" cy="19" r="1.5"/><circle cx="19" cy="5" r="1.5"/>',
    "pen": '<path d="M4 20l4-1L19 8a2 2 0 0 0-3-3L5 16z"/><path d="M14 7l3 3"/>',
    "text-add": '<path d="M4 6h10M9 6v12M7 18h4"/><path d="M18 10v6M15 13h6"/>',
    "field-text": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 11v2"/>',
    "field-check": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "field-radio": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
    "field-combo": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M14 11l2 2 2-2"/>',
    "field-list": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 12h10M7 15h6"/>',
    "field-button": '<rect x="3" y="8" width="18" height="9" rx="4"/><path d="M8 12.5h8"/>',
    "form": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h4"/>',
    "highlight": '<path d="M4 20h16"/><path d="M6 16l9-9 3 3-9 9H6z"/><path d="M13 9l3 3"/>',
    "underline": '<path d="M7 4v6a5 5 0 0 0 10 0V4M5 20h14"/>',
    "strikeout": '<path d="M5 12h14"/><path d="M16 7a4 3 0 0 0-4-3c-2.5 0-4 1.3-4 3s1.5 2.5 4 3"/><path d="M8 17a4 3 0 0 0 4 3c2.5 0 4-1.3 4-3"/>',
    "note": '<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
    "redact": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9l6 6M9 5l9 9M15 5l6 6M3 15l4 4"/>',
    "find": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    "print": '<path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "attach": '<path d="M21 11.5l-8.5 8.5a5.5 5.5 0 0 1-7.8-7.8l9-9a3.5 3.5 0 0 1 5 5l-9 9a1.5 1.5 0 0 1-2.1-2.1l8.3-8.3"/>',
    "resources": '<path d="M4 7l8-4 8 4-8 4z"/><path d="M4 12l8 4 8-4M4 17l8 4 8-4"/>',
    "align-left": '<path d="M4 3v18"/><rect x="7" y="6" width="12" height="4"/><rect x="7" y="14" width="8" height="4"/>',
    "align-center-h": '<path d="M12 3v18"/><rect x="5" y="6" width="14" height="4"/><rect x="8" y="14" width="8" height="4"/>',
    "align-right": '<path d="M20 3v18"/><rect x="5" y="6" width="12" height="4"/><rect x="9" y="14" width="8" height="4"/>',
    "align-top": '<path d="M3 4h18"/><rect x="6" y="7" width="4" height="12"/><rect x="14" y="7" width="4" height="8"/>',
    "align-center-v": '<path d="M3 12h18"/><rect x="6" y="5" width="4" height="14"/><rect x="14" y="8" width="4" height="8"/>',
    "align-bottom": '<path d="M3 20h18"/><rect x="6" y="5" width="4" height="12"/><rect x="14" y="9" width="4" height="8"/>',
    "flip-h": '<path d="M12 3v18"/><path d="M8 7L3 12l5 5V7z"/><path d="M16 7l5 5-5 5V7z"/>',
    "flip-v": '<path d="M3 12h18"/><path d="M7 8l5-5 5 5H7z"/><path d="M7 16l5 5 5-5H7z"/>',
    "front": '<rect x="8" y="8" width="12" height="12" rx="1" fill="currentColor" fill-opacity="0.25"/><rect x="4" y="4" width="12" height="12" rx="1"/>',
    "back": '<rect x="4" y="4" width="12" height="12" rx="1" fill="currentColor" fill-opacity="0.25"/><rect x="8" y="8" width="12" height="12" rx="1"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>',
    "export": '<path d="M12 3v12M7 8l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "shrink": '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
    "flatten": '<path d="M3 17l9 4 9-4M3 12l9 4 9-4"/><path d="M3 7l9 4 9-4-9-4z"/>',
    "page-number": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M10 16h4M12 13v4"/>',
    "watermark": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 14l8-6"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "signature": '<path d="M3 17c3-6 5-8 6-6s-1 6 1 6 3-5 5-5 1 4 3 4 2-2 3-2"/><path d="M3 21h18"/>',
    "logo": '<path d="M3 8l9 3 9-3v9l-9 3-9-3z"/><path d="M12 11v9"/><path d="M5 5l7 2.3L19 5"/>',
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


ASSETS_DIR = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), "assets")


def app_icon() -> QIcon:
    """The coloured application icon (full version for large sizes, folded stack for small ones)."""
    import os

    ic = QIcon()
    full = os.path.join(ASSETS_DIR, "quirewright.svg")
    small = os.path.join(ASSETS_DIR, "quirewright-symbolic.svg")
    for path, sizes in ((small, (16, 24, 32)), (full, (48, 64, 128, 256))):
        if not os.path.exists(path):
            continue
        renderer = QSvgRenderer(path)
        for px in sizes:
            img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(p)
            p.end()
            ic.addPixmap(QPixmap.fromImage(img))
    return ic


def icon_size() -> QSize:
    return QSize(20, 20)
