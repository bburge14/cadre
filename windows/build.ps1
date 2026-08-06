# Builds the actual Windows installer (Setup.exe) for Cadre. Must run ON
# Windows -- PyInstaller does not cross-compile from Linux/macOS. Run from
# a normal PowerShell prompt in the repo root or from windows\.
#
# Prerequisites (one-time):
#   venv already set up (SETUP.md steps 1-2)
#   venv\Scripts\pip install pyinstaller
#   Inno Setup installed (https://jrsoftware.org/isinfo.php), ISCC.exe on
#     your PATH (its default install location is usually already added)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $repoRoot "app.py"))) { $repoRoot = Get-Location }
Set-Location $repoRoot

$pyinstaller = Join-Path $repoRoot "venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    Write-Error "PyInstaller not found at $pyinstaller -- run: venv\Scripts\pip install pyinstaller"
    exit 1
}

Write-Host "Building CadreApp.exe..."
& $pyinstaller --noconfirm windows\app.spec

Write-Host "Building CadreDaemon.exe..."
& $pyinstaller --noconfirm windows\daemon.spec

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    Write-Warning "ISCC.exe (Inno Setup compiler) not found on PATH -- the two .exe files are built in dist\, but I couldn't produce the final Setup.exe installer. Install Inno Setup from https://jrsoftware.org/isinfo.php and re-run this script, or run 'ISCC.exe windows\installer.iss' yourself once it's installed."
    exit 0
}

Write-Host "Building the installer..."
& ISCC.exe windows\installer.iss

Write-Host ""
Write-Host "Done. Installer is in windows\installer-output\"
