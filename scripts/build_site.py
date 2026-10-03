#!/usr/bin/env python3
"""Build the static project site (GitHub Pages) from site/ and the bundled docs.

    python scripts/build_site.py [-o OUTPUT_DIR]

Pages: index.html and download.html from site/templates/, guide.html from the in-app user
guide, features.html from docs/FEATURES.md. Output is self-contained; the gh-pages
branch holds exactly this directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import shutil
import subprocess
import sys

try:
    import markdown
except ImportError:  # pragma: no cover
    sys.exit("The 'markdown' package is required: pip install markdown")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
REPO_URL = "https://github.com/quirewright/quirewright"
SITE_URL = "https://quirewright.github.io/quirewright/"
WARNING = (
    "This software was fully developed by AI. Its human testing and human code review has been extremely limited. "
    "This software comes with no guarantees and no warranties and should not be relied upon for any critical "
    "applications. It is released to the public in hopes that it can be useful for others. Download and use is "
    "covered under the terms of the GNU AGPL License (see <a href=\"{repo}/blob/main/LICENSE\">LICENSE</a> for more "
    "info). We welcome bug reports and contributions. See <a href=\"{repo}/blob/main/CONTRIBUTING.md\">CONTRIBUTING</a> "
    "for more information."
)
DESCRIPTION = (
    "Quirewright is a free and open-source PDF editor for Linux that edits page content as vector "
    "objects and manages pages, forms and comments."
)


def version() -> str:
    with open(os.path.join(ROOT, "src", "quirewright", "__init__.py"), encoding="utf-8") as fh:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    return m.group(1) if m else "0"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def render(template: str, **vars: str) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: vars.get(m.group(1), m.group(0)), template)


def md_to_html(text: str) -> tuple[str, str]:
    """Return (body, toc) for a Markdown document."""
    text = re.sub(r"^(\s*[-*] )\[x\] ", r'\1<span class="check" aria-label="done">✓</span> ', text, flags=re.M)
    text = re.sub(r"^(\s*[-*] )\[ \] ", r'\1<span class="todo" aria-label="planned">○</span> ', text, flags=re.M)
    md = markdown.Markdown(extensions=["toc", "tables", "fenced_code", "sane_lists", "attr_list"],
                           extension_configs={"toc": {"toc_depth": "2-3", "anchorlink": False}})
    body = md.convert(text)
    return body, md.toc


def git_date() -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip() or dt.date.today().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def build(out: str) -> None:
    ver = version()
    base = read(os.path.join(SITE, "templates", "base.html"))
    common = dict(version=ver, repo_url=REPO_URL, site_url=SITE_URL, description=DESCRIPTION)

    def page(name: str, title: str, content: str) -> None:
        html_text = render(base, title=title, content=content, **common)
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            fh.write(html_text)

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    shutil.copytree(os.path.join(SITE, "static"), os.path.join(out, "static"))
    shutil.copy(os.path.join(SITE, "style.css"), os.path.join(out, "style.css"))
    open(os.path.join(out, ".nojekyll"), "w").close()

    index = render(read(os.path.join(SITE, "templates", "index.html")), **common)
    page("index.html", "Quirewright · a free and open-source PDF editor", index)

    download = render(read(os.path.join(SITE, "templates", "download.html")),
                      warning=WARNING.format(repo=REPO_URL), **common)
    page("download.html", "Download · Quirewright", download)

    doc_tpl = read(os.path.join(SITE, "templates", "doc.html"))
    stamp = f'<p class="doc-meta">Quirewright {html.escape(ver)} · updated {git_date()}</p>'

    body, toc = md_to_html(read(os.path.join(ROOT, "src", "quirewright", "help", "USER_GUIDE.md")))
    body = body.replace("</h1>", "</h1>" + stamp, 1)
    page("guide.html", "User guide · Quirewright", render(doc_tpl, body=body, toc=toc))

    body, toc = md_to_html(read(os.path.join(ROOT, "docs", "FEATURES.md")))
    body = body.replace("</h1>", "</h1>" + stamp, 1)
    page("features.html", "Feature checklist · Quirewright", render(doc_tpl, body=body, toc=toc))

    page("404.html", "Not found · Quirewright",
         '<div class="wrap" style="padding:96px 0"><h1>Page not found</h1><p class="lede">'
         'Try the <a href="./">home page</a> or the <a href="guide.html">user guide</a>.</p></div>')
    print(f"site written to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--output", default=os.path.join(ROOT, "build", "site"))
    args = ap.parse_args()
    build(os.path.abspath(args.output))


if __name__ == "__main__":
    main()
