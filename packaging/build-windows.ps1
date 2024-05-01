# Build the Windows package of the Factory Data GUI: the PyInstaller one-folder
# build in dist\FactoryData, zipped as dist\FactoryData-<version>-windows-x64.zip.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# Prefer the project virtualenv when it exists; callers can override PYTHON.
$Python = $env:PYTHON
if (-not $Python) {
    if (Test-Path ".venv\Scripts\python.exe") {
        $Python = ".venv\Scripts\python.exe"
    } else {
        $Python = "python"
    }
}

& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing; install it with: $Python -m pip install pyinstaller"
}

$Version = (& $Python -c "from gui.window import VERSION; print(VERSION)").Trim()
& $Python -m PyInstaller packaging/factory-data.spec --noconfirm --clean

$Zip = "dist\FactoryData-$Version-windows-x64.zip"
Compress-Archive -Path "dist\FactoryData" -DestinationPath $Zip -Force
Write-Host "Windows package: $Zip"
