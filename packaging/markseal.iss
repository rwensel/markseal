#define MyAppName "Markseal"
#define MyAppDisplayName "MarkSeal"
#define MyAppVersion "2.0.5"
#define MyAppExeName "Markseal.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=Markseal-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=icons\markseal.ico
WizardImageFile=icons\wizard-large.bmp
WizardSmallImageFile=icons\wizard-small.bmp

[Files]
Source: "..\dist\Markseal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppDisplayName}"; Flags: nowait postinstall skipifsilent
