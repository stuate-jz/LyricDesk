; 桌面歌词 · Inno Setup 打包脚本
;
; 编译：  ISCC.exe installer.iss
; 注意：  本文件必须保存为「UTF-8 带 BOM」，否则中文会乱码。
;
; 输出：  dist\LyricDesk-Setup-v1.0.exe（纯 ASCII 名，Gitee / GitHub 通用）

#define AppName "桌面歌词"
#define AppDirName "LyricDesk"
#define AppVersion "1.6.6"
#define AppPublisher "LyricDesk"
#define AppExeName "LyricDesk.exe"

[Setup]
AppId={{8F3A2C7E-5B41-4D9A-9E27-1C6D4B0A7F33}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}

DefaultDirName={autopf}\{#AppDirName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

LicenseFile=packaging\许可协议.txt
InfoBeforeFile=packaging\更新说明.txt

OutputDir=dist
OutputBaseFilename=LyricDesk-Setup-v1.6.6
SetupIconFile=desktop-lyric.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
; 检测到程序在运行时直接自动关闭，不弹「请关闭应用程序」的提示
; （桌面歌词平时缩在托盘里，用户很容易以为已经退出了）
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "开机自动运行 {#AppName}"

[Files]
Source: "dist\{#AppExeName}";      DestDir: "{app}"; Flags: ignoreversion
Source: "packaging\使用说明.txt";  DestDir: "{app}"; Flags: ignoreversion
Source: "packaging\更新说明.txt";  DestDir: "{app}"; Flags: ignoreversion
Source: "packaging\许可协议.txt";  DestDir: "{app}"; Flags: ignoreversion
Source: "packaging\update.json";  DestDir: "{app}"; DestName: "更新源模板.json"; Flags: ignoreversion
Source: "assets\fonts\SmileySans-LICENSE.txt"; DestDir: "{app}"; DestName: "字体授权-得意黑.txt"; Flags: ignoreversion
Source: "assets\fonts\LXGWMarkerGothic-LICENSE.txt"; DestDir: "{app}"; DestName: "字体授权-霞鹜漫黑.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                  Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}";             Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";            Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "LyricDesk"; ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
{ 卸载时询问是否一并删除设置与缓存。
  注意：Inno 的卸载分两个进程阶段，全局变量跨阶段会丢，
  所以必须在真正执行卸载的这一步 usUninstall 里询问并删除。 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  { 静默卸载不弹窗，保留用户数据（更安全） }
  if UninstallSilent() then
    Exit;

  UserDataDir := ExpandConstant('{userappdata}\LyricDesk');
  if not DirExists(UserDataDir) then
    Exit;

  if MsgBox('是否同时删除设置和歌词缓存？' + #13#10 + #13#10 +
            '位置：' + UserDataDir + #13#10 +
            '内容：设置、歌词缓存、专辑封面缓存。' + #13#10 + #13#10 +
            '选择「否」会保留这些数据，方便以后重新安装时设置还在。',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(UserDataDir, True, True, True);
end;
