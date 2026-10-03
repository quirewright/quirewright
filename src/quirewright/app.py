"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from quirewright import APP_ID, APP_NAME, __version__


def _migrate_settings() -> None:
    """Carry preferences over from the pre-release name ("pdfeditor") on first start."""
    try:
        from PySide6.QtCore import QSettings

        new = QSettings(APP_ID, APP_ID)
        if new.allKeys():
            return
        old = QSettings("pdfeditor", "pdfeditor")
        for key in old.allKeys():
            new.setValue(key, old.value(key))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME} {__version__}")
    parser.add_argument("file", nargs="?", help="PDF file to open")
    parser.add_argument("--dark", action="store_true", help="force dark mode")
    parser.add_argument("--light", action="store_true", help="force light mode")
    parser.add_argument("--lang", help="interface language code (e.g. en, de); overrides the preference")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from quirewright import i18n

    _migrate_settings()
    settings_pre = QSettings(APP_ID, APP_ID)
    i18n.set_language(args.lang or settings_pre.value("ui/language", "system", type=str))

    from quirewright.ui import theme
    from quirewright.ui.main_window import MainWindow

    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_ID)
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication(sys.argv[:1])
    _migrate_settings()
    settings = QSettings(APP_ID, APP_ID)
    app.setWindowIcon(theme.app_icon())
    # Qt's own strings (file dialogs, message box buttons) in the chosen language
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    lang = i18n.current_language()
    if lang != "en":
        qt_tr = QTranslator(app)
        if qt_tr.load(QLocale(lang), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(qt_tr)
    # Theme preference: "system" (default, follows the desktop live), "light" or "dark".
    mode = settings.value("ui/theme", "", type=str)
    if mode not in ("system", "light", "dark"):
        # First start with the three-way preference: follow the desktop. The old
        # boolean toggle is dropped rather than migrated (it was easy to leave stale).
        mode = "system"
        settings.setValue("ui/theme", mode)
        settings.remove("ui/dark")
        settings.sync()
    if args.dark:
        mode = "dark"
    elif args.light:
        mode = "light"
    theme.apply_theme(app, theme.theme_mode_to_dark(mode))

    win = MainWindow()
    win.show()
    if args.file:
        win.open_file(os.path.abspath(args.file))
    from PySide6.QtCore import QTimer

    from quirewright.ui.dialogs import show_first_run_notice

    QTimer.singleShot(0, lambda: show_first_run_notice(win, settings))
    return app.exec()
