; Inno Setup script for wg-tray on Windows.
; Built in CI via: iscc installer.iss
; Expects the PyInstaller output at dist\wg-tray\ and an icon at dist\icon.ico.

#define MyAppName "wg-tray"
#define MyAppVersion GetEnv("WGTRAY_VERSION")
#define MyAppExeName "wg-tray.exe"

[Setup]
AppId={{6B6E9C2B-6E7C-4C6B-9D0C-1B7F5B9B7A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist-installer
OutputBaseFilename=wg-tray-windows-setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=dist\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\wg-tray\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
