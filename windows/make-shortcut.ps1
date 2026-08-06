# Creates a Desktop shortcut pointing at start.bat. Called from setup.bat --
# not meant to be run standalone, but harmless if it is.
$repoRoot = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Start Cadre.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $repoRoot 'windows\start.bat'
$shortcut.WorkingDirectory = $repoRoot
$iconPath = Join-Path $repoRoot 'windows\cadre-logo.ico'
$shortcut.IconLocation = if (Test-Path $iconPath) { $iconPath } else { "$env:SystemRoot\System32\shell32.dll,220" }
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
