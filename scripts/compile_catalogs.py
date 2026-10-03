#!/usr/bin/env python3
"""Compile every locale/<lang>/LC_MESSAGES/pdfeditor.po into a .mo file (pure Python, no msgfmt needed)."""

from __future__ import annotations

import array
import ast
import os
import struct
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "pdfeditor", "locale")


def parse_po(path: str) -> dict[str, str]:
    msgs: dict[str, str] = {}
    msgid = msgstr = None
    section = None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("#") or not line:
                if msgid is not None and section == "msgstr":
                    msgs[msgid] = msgstr or ""
                    msgid = msgstr = None
                    section = None
                continue
            if line.startswith("msgid "):
                if msgid is not None and section == "msgstr":
                    msgs[msgid] = msgstr or ""
                msgid, msgstr, section = ast.literal_eval(line[6:]), "", "msgid"
            elif line.startswith("msgstr "):
                msgstr, section = ast.literal_eval(line[7:]), "msgstr"
            elif line.startswith('"'):
                val = ast.literal_eval(line)
                if section == "msgid":
                    msgid = (msgid or "") + val
                else:
                    msgstr = (msgstr or "") + val
    if msgid is not None and section == "msgstr":
        msgs[msgid] = msgstr or ""
    return msgs


def write_mo(msgs: dict[str, str], path: str) -> None:
    keys = sorted(msgs)
    ids = b""
    strs = b""
    offsets = []
    for k in keys:
        kb, vb = k.encode("utf-8"), msgs[k].encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\0"
        strs += vb + b"\0"
    n = len(keys)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    output += array.array("i", koffsets).tobytes() + array.array("i", voffsets).tobytes() + ids + strs
    with open(path, "wb") as fh:
        fh.write(output)


def main() -> int:
    count = 0
    for lang in sorted(os.listdir(ROOT)) if os.path.isdir(ROOT) else []:
        po = os.path.join(ROOT, lang, "LC_MESSAGES", "pdfeditor.po")
        if os.path.exists(po):
            parsed = parse_po(po)
            msgs = {k: v for k, v in parsed.items() if k and v}
            # keep the header (empty msgid) so gettext knows the charset
            msgs[""] = parsed.get("", "") or "Content-Type: text/plain; charset=UTF-8\n"
            if "charset=" not in msgs[""]:
                msgs[""] += "Content-Type: text/plain; charset=UTF-8\n"
            write_mo(msgs, os.path.join(ROOT, lang, "LC_MESSAGES", "pdfeditor.mo"))
            print(f"{lang}: {len(msgs) - 1} translated strings")
            count += 1
    print(f"compiled {count} catalogue(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
