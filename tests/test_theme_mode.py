"""Theme preference: system / light / dark, detection fallbacks, live following."""

import os

from PySide6.QtWidgets import QApplication

from quirewright.ui import theme


def test_detection_fallbacks(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: 1)
    monkeypatch.setattr(theme, "_gsettings_color_scheme", lambda: None)
    # Qt reports Unknown offscreen, so the portal answer decides
    assert theme.system_prefers_dark() is True
    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: None)
    monkeypatch.setattr(theme, "_gsettings_color_scheme", lambda: 2)
    assert theme.system_prefers_dark() is False
    assert theme.theme_mode_to_dark("dark") is True and theme.theme_mode_to_dark("light") is False
    monkeypatch.setattr(theme, "_gsettings_color_scheme", lambda: 1)
    assert theme.theme_mode_to_dark("system") is True


def test_window_modes_and_live_follow(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app, False)
    from quirewright.ui.main_window import MainWindow

    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: 2)
    monkeypatch.setattr(theme, "_gsettings_color_scheme", lambda: None)
    win = MainWindow()
    win.apply_theme_mode("system")
    assert win.settings.value("ui/theme") == "system" and not theme.current().dark and win.act_follow_system.isChecked()
    # the desktop switches to dark: the watcher notices and the app follows
    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: 1)
    win._theme_watcher._recheck()
    assert theme.current().dark and win.act_dark.isChecked()
    # an explicit toolbar choice stops following
    win.act_dark.setChecked(False)
    win.toggle_dark(False)
    assert win.settings.value("ui/theme") == "light" and not win.act_follow_system.isChecked()
    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: 2)
    monkeypatch.setattr(theme, "_portal_color_scheme", lambda: 1)
    win._theme_watcher._last = False
    win._theme_watcher._recheck()
    assert not theme.current().dark  # still light: not following
    win.apply_theme_mode("dark")
    assert theme.current().dark and win.settings.value("ui/theme") == "dark"
    win.apply_theme_mode("light")
    theme.apply_theme(app, False)
    win.close()
