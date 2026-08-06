; Inno Setup script for Cadre.
; Build with: ISCC.exe windows\installer.iss
; (requires windows\build.ps1 to have already run PyInstaller and produced
; dist\CadreApp.exe and dist\CadreDaemon.exe)
;
; Get Inno Setup (free) from https://jrsoftware.org/isinfo.php

#define MyAppName "Cadre"
#define MyAppVersion "0.1.0-alpha"
#define MyAppPublisher "Bradey Burge"
#define MyAppURL "http://127.0.0.1:7420"

[Setup]
AppId={{127B4A60-2B0E-4D48-874C-D3B3EBAEEF4A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Cadre
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
SetupIconFile=cadre-logo.ico
; Per-user install, no admin elevation prompt -- matches the systemd
; --user (not system-wide) model used on Linux/macOS.
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=Cadre-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\CadreApp.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\CadreDaemon.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\VERSION"; DestDir: "{app}"; Flags: ignoreversion
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
