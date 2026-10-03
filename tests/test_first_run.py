"""The first-run notice is shown once and remembered in the settings."""

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from quirewright.ui.dialogs import NOTICE_SETTING, FirstRunDialog, show_first_run_notice


def test_notice_shown_once(tmp_path):
    QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)

    def accept_open_dialog():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, FirstRunDialog):
                w.accept()

    QTimer.singleShot(0, accept_open_dialog)
    assert show_first_run_notice(None, settings) is True
    assert settings.value(NOTICE_SETTING, "", type=str) == "1"
    assert show_first_run_notice(None, settings) is False
