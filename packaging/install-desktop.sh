#!/usr/bin/env bash
# Install the launcher and icon for the current user (Linux, freedesktop.org).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$apps" "$icons"
cp "$here/../src/quirewright/assets/quirewright.svg" "$icons/quirewright.svg"
# Point Exec at the installed console script (or this checkout's venv)
exec_path="$(command -v quirewright || true)"
if [ -z "$exec_path" ] && [ -x "$here/../.venv/bin/quirewright" ]; then
  exec_path="$(cd "$here/.." && pwd)/.venv/bin/quirewright"
fi
sed "s|^Exec=quirewright %f|Exec=${exec_path:-quirewright} %f|" "$here/quirewright.desktop" > "$apps/quirewright.desktop"
update-desktop-database "$apps" 2>/dev/null || true
gtk-update-icon-cache "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
echo "Installed launcher to $apps/quirewright.desktop (Exec=${exec_path:-quirewright})"
