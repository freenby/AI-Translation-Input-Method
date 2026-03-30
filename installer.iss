; Inno Setup Script for AI翻译输入法
; 需要安装 Inno Setup: https://jrsoftware.org/isinfo.php

#define MyAppName "AI翻译输入法"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AI Translator"
#define MyAppExeName "AI翻译输入法.exe"

[Setup]
; 应用程序信息
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=AI翻译输入法_安装程序_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

; 安装界面语言（使用默认英文，避免语言包缺失问题）
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: checkedonce
Name: "startupicon"; Description: "开机自动启动"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
; 复制打包后的所有文件
Source: "dist\AI翻译输入法\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 开机自启动（如果用户选择）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupicon

[Run]
; 安装完成后运行程序
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前关闭程序
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""{#MyAppExeName}"""; Flags: runhidden

[Code]
// 检查是否需要安装 VC++ 运行库
function NeedsVCRedist: Boolean;
var
  Version: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
  begin
    Result := False;
  end;
end;

// 初始化安装向导
function InitializeSetup(): Boolean;
begin
  Result := True;
  
  // 检查是否已经在运行
  if CheckForMutexes('{#MyAppName}_Mutex') then
  begin
    MsgBox('程序正在运行中，请先关闭后再安装。', mbError, MB_OK);
    Result := False;
  end;
end;
