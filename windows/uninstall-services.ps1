# Removes the scheduled tasks created by install-services.ps1. Does not
# touch instance/ or .env -- your account, sessions, and settings survive.

Unregister-ScheduledTask -TaskName "BradsAgentStackCreator-Daemon" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "BradsAgentStackCreator-App" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed BradsAgentStackCreator scheduled tasks (if they existed)."
