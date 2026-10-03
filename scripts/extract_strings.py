#!/usr/bin/env python3
"""Extract tr("...") strings from the UI sources into a gettext template (quirewright.pot)."""

from __future__ import annotations

import ast
import os
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "quirewright")
OUT = os.path.join(ROOT, "locale", "quirewright.pot")


def extract(path: str) -> list[tuple[str, int]]:
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name in ("tr", "_") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.append((node.args[0].value, node.lineno))
    return found


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def main() -> int:
    entries: dict[str, list[str]] = {}
    for dirpath, _dirs, files in os.walk(ROOT):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(dirpath, f)
                for text, line in extract(p):
                    entries.setdefault(text, []).append(f"{os.path.relpath(p, ROOT)}:{line}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        stamp = time.strftime("%Y-%m-%d %H:%M%z")
        fh.write(f'msgid ""\nmsgstr ""\n"Project-Id-Version: quirewright\\n"\n"POT-Creation-Date: {stamp}\\n"\n"MIME-Version: 1.0\\n"\n"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n\n')
        for text in sorted(entries):
            fh.write("#: " + " ".join(entries[text][:4]) + "\n")
            fh.write(f'msgid "{escape(text)}"\nmsgstr ""\n\n')
    print(f"wrote {len(entries)} strings to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
