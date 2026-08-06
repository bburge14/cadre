# Called from setup.bat before anything else. If this looks like a
# ZIP-extracted copy (no .git\ -- a real git clone is left wherever you put
# it, since moving it would break git pull/update.bat) running from
# somewhere like Downloads\, moves the whole thing to a stable home and
# re-launches setup from there. Exit code 2 = relocated, caller should stop
# (the new copy is running its own setup now); 0 = already fine, continue.
$ErrorActionPreference = "Stop"
$sourceDir = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $env:LOCALAPPDATA "Programs\Cadre"

if ($sourceDir -eq $targetDir) {
    exit 0
}
if (Test-Path (Join-Path $sourceDir ".git")) {
    exit 0
}

Write-Host "This looks like a ZIP-extracted copy running from a download/temp"
Write-Host "location ($sourceDir)."
Write-Host "Moving it to $targetDir so it has a stable home instead of"
Write-Host "depending on that folder still existing later..."
Write-Host ""

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
robocopy $sourceDir $targetDir /E /XD venv instance /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error "Copy to $targetDir failed (robocopy exit code $LASTEXITCODE). Setup stopped -- nothing was changed at the new location."
    exit 1
}

Write-Host "Done. Continuing setup from $targetDir ..."
Write-Host ""
Start-Process -FilePath (Join-Path $targetDir "windows\setup.bat") -WorkingDirectory $targetDir -Wait -NoNewWindow
Write-Host ""
Write-Host "You can delete the original download/extracted folder now"
Write-Host "($sourceDir) -- Cadre runs from $targetDir going forward."
exit 2
