#!/usr/bin/env python3
#
# factory_data_gui.py - Factory Data: PySide6 GUI that generates the .sys,
#                       .cal and .diag factory data files from CSV files
#
# Author:  Sandesh Ghimire <sandesh@soccentric.com>
# Date:    2026-11-09
# Target:  factory station / factory firmware (FACTORY_SPEC.md section 3)
#
# Pages:
#   System info   .sys   one CSV row per unit: serial, product, versions,
#                        batch, date, MAC, notes
#   Calibration   .cal   one CSV row per channel: gain, offset, plus the
#                        temperature reference, date and operator
#   Diagnostics   .diag  fault, counter and log rows; an id of * applies to
#                        every unit
#   Inspect              open a generated file and check both CRCs
#
# Each generator page loads a CSV, previews its records, and writes the file
# of the selected record, or of every record, to an output folder.
#
# Usage:
#   make gui                (installs dependencies first: make deps)
#   ./factory_data_gui.py
#
# Code lives in core/ (file format, CSV loaders, no Qt) and gui/ (window.py,
# pages.py, widgets.py, icons.py; soc_theme.py, soc_native.py and soc_brand.py
# are the shared SoCcentric look).
#

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication

from gui import soc_brand, soc_native
from gui import soc_theme as theme
from gui.window import APP_NAME, MainWindow


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("soccentric")
    soc_native.install()   # Windows 11 look; no-op elsewhere
    soc_brand.install()    # one colour + the icon set
    app.setFont(theme.ui_font())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
