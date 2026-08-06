# Resets the admin account so you can pick a new username/password --
# for when you're locked out and the password itself is genuinely
# unrecoverable (hashed one-way, never stored in plaintext anywhere).
# Only removes instance\admin.json -- your sessions list, agent stacks,
# skills, and settings (everything else in instance\) are untouched, and
# no restart is needed: admin_exists() is a live file check, so the very
# next page load redirects straight to /setup. Pass -y/--yes to skip the
# confirmation prompt.
$repoRoot = Split-Path -Parent $PSScriptRoot
$adminFile = Join-Path $repoRoot 'instance\admin.json'

if (-not (Test-Path $adminFile)) {
    Write-Host "No admin account is set up yet -- nothing to reset."
    Write-Host "Just load the dashboard; it'll take you to /setup directly."
    exit 0
}

if ($args -notcontains '-y' -and $args -notcontains '--yes') {
    Write-Host "This deletes instance\admin.json only -- your sessions, agent"
    Write-Host "stacks, skills, and settings are untouched. The next time anyone"
    Write-Host "loads the dashboard, they land on /setup to create a new account."
    Write-Host ""
    $confirm = Read-Host "Continue? [y/N]"
    if ($confirm -notmatch '^(?i:y|yes)$') {
        Write-Host "Aborted."
        exit 1
    }
}

Remove-Item -Force $adminFile

Write-Host ""
Write-Host "Done. Load the dashboard now -- it'll take you straight to /setup."
