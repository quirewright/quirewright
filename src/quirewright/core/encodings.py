"""Simple-font encodings and glyph-name to Unicode mapping.

WinAnsiEncoding and MacRomanEncoding are nearly identical to Python's
``cp1252`` and ``mac_roman`` codecs; StandardEncoding is tabulated here.
Glyph names are mapped via a subset of the Adobe Glyph List covering Latin
scripts and common punctuation, plus the ``uniXXXX`` / ``uXXXX`` conventions.
"""

from __future__ import annotations

import re

# --- Base encodings (code -> unicode string) -------------------------------

_STANDARD_HIGH = {
    0o241: "¡", 0o242: "¢", 0o243: "£", 0o244: "⁄", 0o245: "¥", 0o246: "ƒ", 0o247: "§",
    0o250: "¤", 0o251: "'", 0o252: "“", 0o253: "«", 0o254: "‹", 0o255: "›", 0o256: "ﬁ",
    0o257: "ﬂ", 0o261: "–", 0o262: "†", 0o263: "‡", 0o264: "·", 0o266: "¶", 0o267: "•",
    0o270: "‚", 0o271: "„", 0o272: "”", 0o273: "»", 0o274: "…", 0o275: "‰", 0o277: "¿",
    0o301: "`", 0o302: "´", 0o303: "ˆ", 0o304: "˜", 0o305: "¯", 0o306: "˘", 0o307: "˙",
    0o310: "¨", 0o312: "˚", 0o313: "¸", 0o315: "˝", 0o316: "˛", 0o317: "ˇ", 0o320: "—",
    0o341: "Æ", 0o343: "ª", 0o350: "Ł", 0o351: "Ø", 0o352: "Œ", 0o353: "º", 0o361: "æ",
    0o365: "ı", 0o370: "ł", 0o371: "ø", 0o372: "œ", 0o373: "ß",
}


def _build_standard() -> dict[int, str]:
    table = {c: chr(c) for c in range(32, 127)}
    table[0o47] = "’"  # quoteright
    table[0o140] = "‘"  # quoteleft
    table.update(_STANDARD_HIGH)
    return table


def _build_codec(codec: str) -> dict[int, str]:
    table: dict[int, str] = {}
    for c in range(32, 256):
        try:
            ch = bytes([c]).decode(codec)
        except UnicodeDecodeError:
            continue
        if ch and ch != "�":
            table[c] = ch
    return table


STANDARD_ENCODING = _build_standard()
WINANSI_ENCODING = _build_codec("cp1252")
WINANSI_ENCODING[160] = " "  # PDF maps nbsp slot to 'space'
WINANSI_ENCODING[173] = "-"  # hyphen
MACROMAN_ENCODING = _build_codec("mac_roman")
# PDF's MacRomanEncoding differs from Apple's in a couple of slots
MACROMAN_ENCODING[0o312] = " "

BASE_ENCODINGS = {
    "StandardEncoding": STANDARD_ENCODING,
    "WinAnsiEncoding": WINANSI_ENCODING,
    "MacRomanEncoding": MACROMAN_ENCODING,
    "MacExpertEncoding": STANDARD_ENCODING,  # approximation
}

# --- Glyph names -> unicode ---------------------------------------------------

_GLYPH_NAMES: dict[str, str] = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "quotesingle": "'", "quoteright": "’",
    "quoteleft": "‘", "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+",
    "comma": ",", "hyphen": "-", "minus": "−", "period": ".", "slash": "/", "zero": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "colon": ":", "semicolon": ";", "less": "<",
    "equal": "=", "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_",
    "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    "exclamdown": "¡", "cent": "¢", "sterling": "£", "currency": "¤", "yen": "¥",
    "brokenbar": "¦", "section": "§", "dieresis": "¨", "copyright": "©", "ordfeminine": "ª",
    "guillemotleft": "«", "logicalnot": "¬", "registered": "®", "macron": "¯",
    "degree": "°", "plusminus": "±", "twosuperior": "²", "threesuperior": "³",
    "acute": "´", "mu": "µ", "paragraph": "¶", "periodcentered": "·", "cedilla": "¸",
    "onesuperior": "¹", "ordmasculine": "º", "guillemotright": "»", "onequarter": "¼",
    "onehalf": "½", "threequarters": "¾", "questiondown": "¿", "Agrave": "À", "Aacute": "Á",
    "Acircumflex": "Â", "Atilde": "Ã", "Adieresis": "Ä", "Aring": "Å", "AE": "Æ",
    "Ccedilla": "Ç", "Egrave": "È", "Eacute": "É", "Ecircumflex": "Ê", "Edieresis": "Ë",
    "Igrave": "Ì", "Iacute": "Í", "Icircumflex": "Î", "Idieresis": "Ï", "Eth": "Ð",
    "Ntilde": "Ñ", "Ograve": "Ò", "Oacute": "Ó", "Ocircumflex": "Ô", "Otilde": "Õ",
    "Odieresis": "Ö", "multiply": "×", "Oslash": "Ø", "Ugrave": "Ù", "Uacute": "Ú",
    "Ucircumflex": "Û", "Udieresis": "Ü", "Yacute": "Ý", "Thorn": "Þ", "germandbls": "ß",
    "agrave": "à", "aacute": "á", "acircumflex": "â", "atilde": "ã", "adieresis": "ä",
    "aring": "å", "ae": "æ", "ccedilla": "ç", "egrave": "è", "eacute": "é",
    "ecircumflex": "ê", "edieresis": "ë", "igrave": "ì", "iacute": "í", "icircumflex": "î",
    "idieresis": "ï", "eth": "ð", "ntilde": "ñ", "ograve": "ò", "oacute": "ó",
    "ocircumflex": "ô", "otilde": "õ", "odieresis": "ö", "divide": "÷", "oslash": "ø",
    "ugrave": "ù", "uacute": "ú", "ucircumflex": "û", "udieresis": "ü", "yacute": "ý",
    "thorn": "þ", "ydieresis": "ÿ", "Amacron": "Ā", "amacron": "ā", "Abreve": "Ă",
    "abreve": "ă", "Aogonek": "Ą", "aogonek": "ą", "Cacute": "Ć", "cacute": "ć",
    "Ccaron": "Č", "ccaron": "č", "Dcaron": "Ď", "dcaron": "ď", "Dcroat": "Đ", "dcroat": "đ",
    "Emacron": "Ē", "emacron": "ē", "Edotaccent": "Ė", "edotaccent": "ė", "Eogonek": "Ę",
    "eogonek": "ę", "Ecaron": "Ě", "ecaron": "ě", "Gbreve": "Ğ", "gbreve": "ğ",
    "Imacron": "Ī", "imacron": "ī", "Iogonek": "Į", "iogonek": "į", "Idotaccent": "İ",
    "dotlessi": "ı", "Lacute": "Ĺ", "lacute": "ĺ", "Lcaron": "Ľ", "lcaron": "ľ",
    "Lslash": "Ł", "lslash": "ł", "Nacute": "Ń", "nacute": "ń", "Ncaron": "Ň", "ncaron": "ň",
    "Omacron": "Ō", "omacron": "ō", "Ohungarumlaut": "Ő", "ohungarumlaut": "ő", "OE": "Œ",
    "oe": "œ", "Racute": "Ŕ", "racute": "ŕ", "Rcaron": "Ř", "rcaron": "ř", "Sacute": "Ś",
    "sacute": "ś", "Scedilla": "Ş", "scedilla": "ş", "Scaron": "Š", "scaron": "š",
    "Tcaron": "Ť", "tcaron": "ť", "Umacron": "Ū", "umacron": "ū", "Uring": "Ů", "uring": "ů",
    "Uhungarumlaut": "Ű", "uhungarumlaut": "ű", "Uogonek": "Ų", "uogonek": "ų",
    "Ydieresis": "Ÿ", "Zacute": "Ź", "zacute": "ź", "Zdotaccent": "Ż", "zdotaccent": "ż",
    "Zcaron": "Ž", "zcaron": "ž", "florin": "ƒ", "circumflex": "ˆ", "caron": "ˇ",
    "breve": "˘", "dotaccent": "˙", "ring": "˚", "ogonek": "˛", "tilde": "˜",
    "hungarumlaut": "˝", "endash": "–", "emdash": "—", "quotedblleft": "“",
    "quotedblright": "”", "quotesinglbase": "‚", "quotedblbase": "„", "dagger": "†",
    "daggerdbl": "‡", "bullet": "•", "ellipsis": "…", "perthousand": "‰",
    "guilsinglleft": "‹", "guilsinglright": "›", "fraction": "⁄", "Euro": "€",
    "trademark": "™", "partialdiff": "∂", "Delta": "∆", "product": "∏", "summation": "∑",
    "radical": "√", "infinity": "∞", "integral": "∫", "approxequal": "≈", "notequal": "≠",
    "lessequal": "≤", "greaterequal": "≥", "lozenge": "◊", "fi": "ﬁ", "fl": "ﬂ",
    "ff": "ﬀ", "ffi": "ﬃ", "ffl": "ﬄ", "nbspace": " ", "sfthyphen": "­",
    "Omega": "Ω", "pi": "π", "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "theta": "θ", "lambda": "λ", "sigma": "σ", "tau": "τ", "phi": "φ",
    "omega": "ω", "arrowleft": "←", "arrowup": "↑", "arrowright": "→", "arrowdown": "↓",
    "checkmark": "✓", "apple": "", ".notdef": "",
}
for _c in range(ord("A"), ord("Z") + 1):
    _GLYPH_NAMES[chr(_c)] = chr(_c)
    _GLYPH_NAMES[chr(_c + 32)] = chr(_c + 32)

_UNI_RE = re.compile(r"^uni([0-9A-Fa-f]{4})")
_U_RE = re.compile(r"^u([0-9A-Fa-f]{4,6})$")
_GID_RE = re.compile(r"^(?:g|glyph|cid|c|G)(\d+)$")


def glyph_name_to_unicode(name: str) -> str | None:
    """Map a glyph name to a Unicode string, or ``None`` if unknown."""
    if name in _GLYPH_NAMES:
        return _GLYPH_NAMES[name]
    base = name.split(".")[0]  # e.g. "a.sc" -> "a"
    if base != name and base in _GLYPH_NAMES:
        return _GLYPH_NAMES[base]
    m = _UNI_RE.match(name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return None
    m = _U_RE.match(name)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except ValueError:
            return None
    if _GID_RE.match(name):
        return None
    if len(name) == 1:
        return name
    return None
