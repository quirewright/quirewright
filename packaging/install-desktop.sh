#!/usr/bin/env bash
# Install the launcher and icons for the current user (Linux, freedesktop.org / GNOME / KDE).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$data/applications"
hicolor="$data/icons/hicolor"
assets="$here/../src/quirewright/assets"
mkdir -p "$apps" "$hicolor/scalable/apps"
cp "$assets/quirewright.svg" "$hicolor/scalable/apps/quirewright.svg"

# Fixed-size PNGs for shells that do not rasterise SVG icons themselves.
py="$here/../.venv/bin/python"
[ -x "$py" ] || py="$(command -v python3 || true)"
if [ -n "$py" ]; then
  QT_QPA_PLATFORM=offscreen "$py" - "$assets" "$hicolor" <<'PYICON' || true
import os, sys
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
except ImportError:
    sys.exit(0)
assets, root = sys.argv[1], sys.argv[2]
app = QGuiApplication([])
for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
    src = os.path.join(assets, "quirewright-symbolic.svg" if size <= 32 else "quirewright.svg")
    r = QSvgRenderer(src)
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    d = os.path.join(root, f"{size}x{size}", "apps")
    os.makedirs(d, exist_ok=True)
    img.save(os.path.join(d, "quirewright.png"))
PYICON
fi

# Point Exec at the installed console script (or this checkout's venv)
exec_path="$(command -v quirewright || true)"
if [ -z "$exec_path" ] && [ -x "$here/../.venv/bin/quirewright" ]; then
  exec_path="$(cd "$here/.." && pwd)/.venv/bin/quirewright"
fi
sed "s|^Exec=quirewright %f|Exec=${exec_path:-quirewright} %f|" "$here/quirewright.desktop" > "$apps/quirewright.desktop"
update-desktop-database "$apps" 2>/dev/null || true
touch "$hicolor"
gtk-update-icon-cache -f -t "$hicolor" 2>/dev/null || true
echo "Installed launcher to $apps/quirewright.desktop (Exec=${exec_path:-quirewright})"
echo "Icons in $hicolor (scalable + $(ls "$hicolor" | grep -c x) PNG sizes)"
