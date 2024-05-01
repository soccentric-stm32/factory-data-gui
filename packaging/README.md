# Packaging the Factory Data GUI

The application is built with PyInstaller in **one-folder** mode on each
operating system: `packaging/factory-data.spec` collects `factory_data_gui.py`,
`core/`, `gui/` and the PySide6 runtime into `dist/FactoryData/`. The GUI is
windowed (`console=False`), so a packaged run opens no terminal; the
command-line tool is not packaged and stays a plain `python factory_data_cli.py`.

PyInstaller is not a runtime dependency. Install it where you build:

```bash
python -m pip install pyinstaller
```

## Build

```bash
make dist                         # packaging script of the host OS
# or run the script directly:
packaging/build-linux.sh
packaging/build-macos.sh
packaging\build-windows.ps1
```

`make dist` byte-compiles the sources first and passes `PYTHON` through, so a
virtualenv built by `make deps` is used. The scripts prefer `.venv` themselves
and fall back to `python3` (POSIX) or `python` (Windows).

All three scripts start from the same PyInstaller spec, which reads the
version from `gui/window.py` (`VERSION`), so the bundle and the artifact names
always agree with the About box.

### Linux

```bash
packaging/build-linux.sh          # dist/FactoryData + .tar.gz
```

`dist/FactoryData-<version>-linux-<arch>.tar.gz` unpacks to a `FactoryData/`
folder that runs from anywhere; ship it as-is or wrap it in a `.deb`/AppImage
of your distribution. The one-folder build needs the X11/xcb libraries of the
target distribution, which PyInstaller bundles where it can.

### macOS

```bash
packaging/build-macos.sh          # dist/FactoryData.app + .dmg
```

The spec wraps the collected tree in `FactoryData.app` with the bundle
identifier `com.soccentric.factorydata` and the version in `Info.plist`. The
`.dmg` has the usual drag-to-Applications layout. Signing and notarisation are
left to the release owner.

### Windows

```powershell
packaging\build-windows.ps1       # dist\FactoryData + .zip
```

`dist\FactoryData-<version>-windows-x64.zip` contains the `FactoryData` folder
with `FactoryData.exe`. Signing and an MSI installer are left to the release
owner.

## Icons

No icon is committed yet. PyInstaller uses `packaging/FactoryData.ico` on
Windows and `packaging/FactoryData.icns` on macOS when either file exists, so
adding one needs no change to the spec or the scripts.

## Direct source run

```bash
make venv                         # .venv with the system PySide6 visible
make deps                         # pip install -r requirements.txt
make gui                          # or: .venv/bin/python factory_data_gui.py
```
