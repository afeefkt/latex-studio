; ── LaTeX Studio Windows installer — Inno Setup script ──
; Build: iscc /DMyAppVersion="v0.1.0" installer/windows.iss

#define MyAppName "LaTeX Studio"
#define MyAppPublisher "LatexStudio"
#define MyAppExeName "LaTeXStudio.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={userappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist\installer
OutputBaseFilename=LaTeXStudio-{#MyAppVersion}-windows-x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\LaTeXStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsLualatexInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd', '/c where lualatex >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function IsGitInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd', '/c where git >nul 2>&1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Msg: string;
begin
  if CurStep = ssPostInstall then
  begin
    Msg := '';
    if not IsLualatexInstalled then
      Msg := Msg + 'LaTeX (lualatex) was not found on your system.' + #13#10 +
             'Install it: winget install MiKTeX.MiKTeX' + #13#10#13#10;
    if not IsGitInstalled then
      Msg := Msg + 'Git was not found on your system.' + #13#10 +
             'Install it: winget install Git.Git' + #13#10#13#10;
    if Msg <> '' then
      MsgBox(Msg + 'LaTeX Studio will start, but PDF compilation requires these tools.', mbInformation, MB_OK);
  end;
end;
