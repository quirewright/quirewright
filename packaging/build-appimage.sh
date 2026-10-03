#!/usr/bin/env bash
# Build a self-contained Linux AppImage with PyInstaller + appimagetool.
# Usage: packaging/build-appimage.sh            (from the repository root)
# Requires: python with the project and pyinstaller installed, curl, FUSE2 (or
# APPIMAGE_EXTRACT_AND_RUN=1 to run appimagetool without FUSE).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
py="${PYTHON:-python}"
if [ -x "$root/.venv/bin/python" ] && [ -z "${PYTHON:-}" ]; then py="$root/.venv/bin/python"; fi
version="$($py -c 'import pdfeditor; print(pdfeditor.__version__)')"
arch="$(uname -m)"
build="$root/build/appimage"
rm -rf "$build" "$root/dist/PDFEditor-$version-$arch.AppImage"
mkdir -p "$build" "$root/dist"

echo "==> PyInstaller bundle"
"$py" -m PyInstaller --noconfirm --clean --log-level WARN \
  --name pdfeditor --windowed --onedir \
  --distpath "$build/dist" --workpath "$build/work" --specpath "$build" \
  --collect-data pdfeditor \
  --hidden-import pdfeditor.ui.main_window \
  --exclude-module tkinter --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts --exclude-module PySide6.QtDataVisualization \
  "$root/packaging/entry.py"

echo "==> AppDir"
appdir="$build/AppDir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor/scalable/apps" "$appdir/usr/share/metainfo"
cp -r "$build/dist/pdfeditor/." "$appdir/usr/bin/"
cp "$root/packaging/pdfeditor.desktop" "$appdir/pdfeditor.desktop"
cp "$root/packaging/pdfeditor.desktop" "$appdir/usr/share/applications/"
cp "$root/packaging/pdfeditor.svg" "$appdir/pdfeditor.svg"
cp "$root/packaging/pdfeditor.svg" "$appdir/usr/share/icons/hicolor/scalable/apps/pdfeditor.svg"
cp "$root/packaging/io.github.pdfeditor.PDFEditor.metainfo.xml" "$appdir/usr/share/metainfo/" 2>/dev/null || true
cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-xdgdesktopportal}"
exec "$here/usr/bin/pdfeditor" "$@"
EOF
chmod +x "$appdir/AppRun"

echo "==> appimagetool"
tool="${APPIMAGETOOL:-$build/appimagetool}"
if [ ! -x "$tool" ]; then
  curl -sL -o "$tool" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$arch.AppImage"
  chmod +x "$tool"
fi
export ARCH="$arch"
out="$root/dist/PDFEditor-$version-$arch.AppImage"
if [ -n "${APPIMAGE_EXTRACT_AND_RUN:-}" ] || ! [ -e /dev/fuse ]; then
  "$tool" --appimage-extract-and-run "$appdir" "$out"
else
  "$tool" "$appdir" "$out" || "$tool" --appimage-extract-and-run "$appdir" "$out"
fi
ls -la "$out"
echo "==> done: $out"
