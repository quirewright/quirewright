"""Translation support (gettext). ``tr("text")`` returns the translated string.

Catalogues live in ``pdfeditor/locale/<lang>/LC_MESSAGES/pdfeditor.mo``.
Use ``scripts/extract_strings.py`` to refresh ``pdfeditor.pot`` and
``msgfmt`` (or ``scripts/compile_catalogs.py``) to build ``.mo`` files.
"""

from __future__ import annotations

import gettext
import locale
import os

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")
_translation: gettext.NullTranslations = gettext.NullTranslations()
_language = "en"


def available_languages() -> list[str]:
    langs = ["en"]
    if os.path.isdir(LOCALE_DIR):
        for name in sorted(os.listdir(LOCALE_DIR)):
            if os.path.exists(os.path.join(LOCALE_DIR, name, "LC_MESSAGES", "pdfeditor.mo")) and name not in langs:
                langs.append(name)
    return langs


def system_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            return v.split(".")[0].split("_")[0] or "en"
    try:
        loc = locale.getlocale()[0] or ""
        return loc.split("_")[0] or "en"
    except Exception:
        return "en"


def set_language(lang: str | None) -> str:
    """Activate a language ("system", "en", "de", ...); returns the language actually used."""
    global _translation, _language
    want = system_language() if not lang or lang == "system" else lang
    if want == "en" or want not in available_languages():
        _translation = gettext.NullTranslations()
        _language = "en" if want not in available_languages() else want
        return _language
    _translation = gettext.translation("pdfeditor", LOCALE_DIR, languages=[want], fallback=True)
    _language = want
    return _language


def current_language() -> str:
    return _language


def tr(text: str) -> str:
    if not text:
        return text  # gettext would return the catalogue header for ""
    return _translation.gettext(text)


def ntr(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def N_(text: str) -> str:
    """Mark a string for extraction without translating it yet (translate with tr() at use)."""
    return text
