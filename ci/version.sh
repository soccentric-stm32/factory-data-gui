#!/usr/bin/env bash
#
# version.sh - print the version this build reports, without a leading v
#
# Used by the Jenkins Package and Release stages.  The source of truth is
# gui/window.py (VERSION), which the About box and the packaging scripts also
# read, so a release can never carry a GUI that reports another version.
#

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
sed -n 's/^VERSION *= *"\([^"]*\)".*/\1/p' gui/window.py | head -n 1
