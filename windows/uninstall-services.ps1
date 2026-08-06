# Removes the scheduled tasks created by install-services.ps1. Does not
# touch instance/ or .env -- your account, sessions, and settings survive.

# Scheduled task names are global, not scoped to whichever checkout is
# running this script -- only remove a task if its own WorkingDirectory
# actually matches this repo, so a second checkout elsewhere can never
# reach across and kill a different install's services.
$repoRoot = Split-Path -Parent $PSScriptRoot
foreach ($taskName in @("Cadre-Daemon", "Cadre-App")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { continue }
    $taskWorkDir = $task.Actions[0].WorkingDirectory
    if ($taskWorkDir -eq $repoRoot) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed $taskName."
    } else {
        Write-Host "Scheduled task $taskName points at a different checkout ($taskWorkDir) -- leaving it alone."
    }
}
