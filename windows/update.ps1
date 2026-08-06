# Pulls the latest code, reinstalls dependencies (in case requirements.txt
# changed), and restarts the dashboard if this checkout owns a registered
# scheduled task -- the session daemon is deliberately left alone, since
# restarting it ends any live Claude Code sessions it's holding open; if an
# update specifically touches session_daemon.py, restart that yourself.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
    Write-Host "This isn't a git checkout (no .git\ found) -- can't pull an"
    Write-Host "update this way. Download the latest release from GitHub instead:"
    Write-Host "https://github.com/bburge14/cadre/releases"
    exit 1
}

Write-Host "Pulling latest changes..."
git pull

Write-Host "Reinstalling dependencies..."
& "venv\Scripts\pip.exe" install -r requirements.txt

# Same WorkingDirectory-match safety check as uninstall.ps1 -- a scheduled
# task name is global, not scoped to whichever checkout runs this script.
$task = Get-ScheduledTask -TaskName "Cadre-App" -ErrorAction SilentlyContinue
if ($null -ne $task -and $task.Actions[0].WorkingDirectory -eq $repoRoot) {
    Write-Host "Restarting the Cadre-App task (the dashboard only)..."
    Stop-ScheduledTask -TaskName "Cadre-App" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName "Cadre-App"
} else {
    Write-Host ""
    Write-Host "No matching scheduled task for this checkout -- restart the"
    Write-Host "dashboard yourself (re-run windows\start.bat, or close and"
    Write-Host "reopen it) to pick up the new code."
}

$version = (Get-Content (Join-Path $repoRoot "VERSION") -ErrorAction SilentlyContinue)
Write-Host ""
Write-Host "Done. Now on: v$version"
