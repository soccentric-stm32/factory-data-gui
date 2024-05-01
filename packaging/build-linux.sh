#!/usr/bin/env bash
#
# Build the Linux package of the Factory Data GUI: a PyInstaller one-folder
# tree in dist/FactoryData, archived so it can be unpacked anywhere.
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

ARCHIVE="$ROOT/dist/FactoryData-${VERSION}-linux-$(uname -m).tar.gz"
tar -C "$ROOT/dist" -czf "$ARCHIVE" FactoryData
echo "Linux package: $ARCHIVE"
