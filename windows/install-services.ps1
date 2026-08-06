# Sets up Cadre to run automatically at login, using
# Windows Task Scheduler -- the closest equivalent to the systemd --user
# services used on Linux/macOS (see SETUP.md). Run this once, from a normal
# PowerShell prompt (no admin rights needed for a per-user scheduled task).
#
# Works two ways, auto-detected:
#   - Source/dev install (cloned the repo, `venv\Scripts\pip install -r
#     requirements.txt` already run): runs venv\Scripts\pythonw.exe against
#     app.py / session_daemon.py.
#   - Installed via the .exe installer: runs the standalone
#     CadreApp.exe / CadreDaemon.exe directly, no
#     Python installation involved at all.
#
# Two separate tasks are created, mirroring the two-process design: the
# session daemon (owns each Claude Code session's pseudo-console, should
# rarely need restarting) and the web dashboard (restarts often as you
# make changes, but a restart of *this* one can never kill a live session
# -- that's the whole point of the split).

$ErrorActionPreference = "Stop"
$repoDir = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoDir "venv\Scripts\pythonw.exe"
$appExe = Join-Path $repoDir "CadreApp.exe"
$daemonExe = Join-Path $repoDir "CadreDaemon.exe"

if (Test-Path $pythonw) {
    $daemonAction = @{ Execute = $pythonw; Argument = "session_daemon.py" }
    $appAction = @{ Execute = $pythonw; Argument = "app.py" }
} elseif ((Test-Path $appExe) -and (Test-Path $daemonExe)) {
    $daemonAction = @{ Execute = $daemonExe; Argument = "" }
    $appAction = @{ Execute = $appExe; Argument = "" }
} else {
    Write-Error "Couldn't find either a venv (venv\Scripts\pythonw.exe) or the installed executables (CadreApp.exe / CadreDaemon.exe) in $repoDir"
    exit 1
}

function Install-Task {
    param([string]$Name, [hashtable]$ActionSpec)
    $action = New-ScheduledTaskAction -Execute $ActionSpec.Execute -Argument $ActionSpec.Argument -WorkingDirectory $repoDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Installed scheduled task: $Name"
}

Install-Task -Name "Cadre-Daemon" -ActionSpec $daemonAction
Install-Task -Name "Cadre-App" -ActionSpec $appAction

Write-Host ""
Write-Host "Starting both now (they'll also auto-start at your next login)..."
Start-ScheduledTask -TaskName "Cadre-Daemon"
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "Cadre-App"

Write-Host ""
Write-Host "Done. Check status with:"
Write-Host "  Get-ScheduledTask -TaskName 'Cadre-*'"
Write-Host "Dashboard should be reachable shortly at the host/port from your .env (default http://127.0.0.1:7420)."
