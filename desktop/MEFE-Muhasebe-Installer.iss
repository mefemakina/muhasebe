#define MyAppName "MEFE Muhasebe"
; MyAppVersion uyumsoft_cari/__init__.py içindeki __version__ ile manuel senkronize edilir.
; CI/Build pipeline'da `tools/sync_installer_version.py` çalıştırılarak otomatik güncellenir.
#define MyAppVersion "1.1.0"
#define MyAppPublisher "MEFE Makina"
#define MyAppExeName "MEFE-Muhasebe.exe"

[Setup]
AppId={{8B1595D0-2C8D-4F7C-9430-3C3B85F7F4E2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MEFE Muhasebe
DefaultGroupName=MEFE Muhasebe
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=MEFE-Muhasebe-Setup-{#MyAppVersion}
SetupIconFile=assets\mefe_muhasebe_logo.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
