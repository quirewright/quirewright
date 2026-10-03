"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from pdfeditor import APP_ID, APP_NAME, __version__


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
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication

    from pdfeditor import i18n

    settings_pre = QSettings(APP_ID, APP_ID)
    i18n.set_language(args.lang or settings_pre.value("ui/language", "system", type=str))

    from pdfeditor.ui import theme
    from pdfeditor.ui.main_window import MainWindow

    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_ID)
    QApplication.setDesktopFileName(APP_ID)
    app = QApplication(sys.argv[:1])
    settings = QSettings(APP_ID, APP_ID)
    # Qt's own strings (file dialogs, message box buttons) in the chosen language
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    lang = i18n.current_language()
    if lang != "en":
        qt_tr = QTranslator(app)
        if qt_tr.load(QLocale(lang), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(qt_tr)
    dark: bool | None = None
    if args.dark:
        dark = True
    elif args.light:
        dark = False
    elif settings.contains("ui/dark"):
        dark = settings.value("ui/dark", False, type=bool)
    theme.apply_theme(app, dark)

    win = MainWindow()
    win.show()
    if args.file:
        win.open_file(os.path.abspath(args.file))
    return app.exec()
