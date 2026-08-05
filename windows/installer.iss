; Inno Setup script for Brad's Agent Stack Creator.
; Build with: ISCC.exe windows\installer.iss
; (requires windows\build.ps1 to have already run PyInstaller and produced
; dist\AgentStackCreatorApp.exe and dist\AgentStackCreatorDaemon.exe)
;
; Get Inno Setup (free) from https://jrsoftware.org/isinfo.php

#define MyAppName "Brad's Agent Stack Creator"
#define MyAppVersion "0.1.0-alpha"
#define MyAppPublisher "Bradey Burge"
#define MyAppURL "http://127.0.0.1:7420"

[Setup]
AppId={{127B4A60-2B0E-4D48-874C-D3B3EBAEEF4A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\BradsAgentStackCreator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install, no admin elevation prompt -- matches the systemd
; --user (not system-wide) model used on Linux/macOS.
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=BradsAgentStackCreator-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\AgentStackCreatorApp.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\AgentStackCreatorDaemon.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SETUP.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "install-services.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall-services.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{#MyAppURL}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-services.ps1"""; \
    WorkingDir: "{app}"; StatusMsg: "Setting up background services..."; Flags: runhidden waituntilterminated
Filename: "{#MyAppURL}"; Description: "Open the dashboard now"; Flags: postinstall shellexec skipifsilent

[UninstallRun]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall-services.ps1"""; \
    Flags: runhidden waituntilterminated
