# Full teardown of this app's install footprint, so you can re-run
# windows\setup.bat and get a genuinely clean first-run experience. Removes
# only what setup.bat creates -- the source code, %USERPROFILE%\.claude\agents\
# (the global agent team), and every stack's own project directory are never
# touched. Pass -y/--yes to skip the confirmation prompt.
$repoRoot = Split-Path -Parent $PSScriptRoot

if ($args -notcontains '-y' -and $args -notcontains '--yes') {
    Write-Host "This will:"
    Write-Host "  - stop the dashboard and session daemon if running (ends any"
    Write-Host "    Claude Code sessions the daemon is currently holding open)"
    Write-Host "  - remove the BradsAgentStackCreator scheduled tasks, if installed"
    Write-Host "  - delete venv\, instance\ (your admin account, sessions list,"
    Write-Host "    agent stacks, settings), .env, and the Desktop shortcut"
    Write-Host ""
    Write-Host "NOT touched: the source code itself, ~\.claude\agents\ (your"
    Write-Host "global agent team), and every stack's own project directory."
    Write-Host ""
    $confirm = Read-Host "Continue? [y/N]"
    if ($confirm -notmatch '^(?i:y|yes)$') {
        Write-Host "Aborted."
        exit 1
    }
}

# Scheduled task names are global, not scoped to whichever checkout is
# running this script -- only remove a task if its own WorkingDirectory
# actually matches this repo, so a second checkout elsewhere can never
# reach across and kill a different install's services.
foreach ($taskName in @("BradsAgentStackCreator-Daemon", "BradsAgentStackCreator-App")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { continue }
    $taskWorkDir = $task.Actions[0].WorkingDirectory
    if ($taskWorkDir -eq $repoRoot) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } else {
        Write-Host "Scheduled task $taskName points at a different checkout ($taskWorkDir) -- leaving it alone."
    }
}

Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like "*$repoRoot*app.py*" -or $_.CommandLine -like "*$repoRoot*session_daemon.py*")
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item -Recurse -Force (Join-Path $repoRoot 'venv') -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $repoRoot 'instance') -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $repoRoot '.env') -ErrorAction SilentlyContinue

$desktop = [Environment]::GetFolderPath('Desktop')
Remove-Item -Force (Join-Path $desktop 'Start Agent Stack Creator.lnk') -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done. Run windows\setup.bat to reinstall from scratch."
