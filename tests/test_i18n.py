import os
import subprocess
import sys

from quirewright import i18n


def test_language_switching():
    assert "de" in i18n.available_languages()
    assert i18n.set_language("de") == "de"
    try:
        assert i18n.tr("&File") == "&Datei"
        assert i18n.tr("Open PDF…") == "PDF öffnen…"
        assert i18n.tr("some untranslated text") == "some untranslated text"
        assert i18n.N_("&File") == "&File"
    finally:
        i18n.set_language("en")
    assert i18n.tr("&File") == "&File"
    assert i18n.set_language("xx") == "en"


def test_extractor_and_compiler_run(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, os.path.join(root, "scripts", "extract_strings.py")], capture_output=True, text=True, check=True)
    assert "strings" in out.stdout
    pot = open(os.path.join(root, "src", "quirewright", "locale", "quirewright.pot"), encoding="utf-8").read()
    assert 'msgid "&File"' in pot and 'msgid "Rectangle"' in pot
    out = subprocess.run([sys.executable, os.path.join(root, "scripts", "compile_catalogs.py")], capture_output=True, text=True, check=True)
    assert "de:" in out.stdout


def test_ui_in_german(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    i18n.set_language("de")
    try:
        from quirewright.ui.main_window import MainWindow

        win = MainWindow()
        titles = [a.text() for a in win.menuBar().actions()]
        assert "&Datei" in titles and "&Hilfe" in titles
        assert win.act_open.text() == "&Öffnen…"
        win.close()
    finally:
        i18n.set_language("en")
