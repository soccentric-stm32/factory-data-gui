# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller one-folder build of the Factory Data GUI.
#
# Build it through `make dist` or the packaging script of the host OS:
#   packaging/build-linux.sh    dist/FactoryData + .tar.gz
#   packaging/build-macos.sh    dist/FactoryData + FactoryData.app + .dmg
#   packaging\build-windows.ps1 dist/FactoryData + .zip
#
# The GUI is windowed (console=False), so a run has no terminal; the CLI stays
# a plain `python factory_data_cli.py`.
import ast
import os
import sys

# Relative paths in a PyInstaller spec are resolved against the spec file, not
# the directory the build is started from.  Derive the repository root from
# SPECPATH so the build works from any working directory.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))


def _version() -> str:
    """The app version, read from gui/window.py (the one place it is set)."""
    with open(os.path.join(ROOT, "gui", "window.py"), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VERSION":
            return node.value.value
    raise RuntimeError("gui/window.py does not define VERSION")


def _icon(suffix: str) -> str | None:
    """packaging/FactoryData.ico or .icns, when the release owner ships one."""
    path = os.path.join(ROOT, "packaging", "FactoryData" + suffix)
    return path if os.path.exists(path) else None


VERSION = _version()

a = Analysis(
    [os.path.join(ROOT, "factory_data_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FactoryData",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon(".ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FactoryData",
)

# macOS only: wrap the one-folder tree in a .app so the bundle identifier and
# the version reach the Finder and Gatekeeper.  build-macos.sh turns it into
# the .dmg; the other platforms stop at the folder above.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FactoryData.app",
        icon=_icon(".icns"),
        bundle_identifier="com.soccentric.factorydata",
        info_plist={
            "CFBundleName": "Factory Data",
            "CFBundleDisplayName": "Factory Data",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
