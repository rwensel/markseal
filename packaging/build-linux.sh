#!/usr/bin/env sh
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
./.venv/bin/python -m unittest
./.venv/bin/python -m PyInstaller --noconfirm --clean packaging/markseal.spec
printf 'Built dist/Markseal/ - wrap it as an AppImage with appimagetool if you want a single file\n'
