#!/usr/bin/env bash
#
# Build the macOS package of the Factory Data GUI: the PyInstaller .app bundle
# (com.soccentric.factorydata) and a .dmg with a drag-to-Applications layout.
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

# Prefer the project virtualenv when it exists; callers can override PYTHON.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python3
  fi
fi

if ! "$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "PyInstaller is missing; install it with: $PYTHON -m pip install pyinstaller" >&2
  exit 1
fi

VERSION="$("$PYTHON" -c 'from gui.window import VERSION; print(VERSION)')"
"$PYTHON" -m PyInstaller packaging/factory-data.spec --noconfirm --clean

APP="$ROOT/dist/FactoryData.app"
if [ ! -d "$APP" ]; then
  echo "expected the .app bundle at $APP; the spec builds it with BUNDLE on macOS" >&2
  exit 1
fi

DMG="$ROOT/dist/FactoryData-${VERSION}.dmg"
STAGE="$ROOT/build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Factory Data" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "macOS package: $DMG"
