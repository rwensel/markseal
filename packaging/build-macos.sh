#!/usr/bin/env sh
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [ "${SKIP_TESTS:-0}" != "1" ]; then
    ./.venv/bin/python -m unittest
fi
./.venv/bin/python packaging/fetch_ner_model.py
./.venv/bin/python -m PyInstaller --noconfirm --clean packaging/markseal.spec
mkdir -p dist/Markseal.app/Contents/Resources
cp LICENSE dist/Markseal.app/Contents/Resources/LICENSE
printf 'Built dist/Markseal.app\n'
