#!/usr/bin/env bash
# Build a wg-tray binary/bundle for the current OS.
#   macOS  -> dist/wg-tray.app
#   Linux  -> dist/wg-tray/ (run dist/wg-tray/wg-tray)
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv .build-venv
source .build-venv/bin/activate
pip install -q -r requirements.txt

pyinstaller --noconfirm wg_tray.spec

deactivate

echo
echo "Build complete. See ./dist/"
