# Build a wg-tray.exe for Windows.
# Run from PowerShell: .\build.ps1
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m venv .build-venv
. .\.build-venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

pyinstaller --noconfirm wg_tray.spec

deactivate

Write-Host ""
Write-Host "Build complete. See .\dist\wg-tray\wg-tray.exe"
