; Inno Setup script — собирает автономный установщик AutoSync.exe вокруг
; уже готового dist\native-windows\autosync.exe (см.
; scripts\build-native-windows.ps1 — нужно запустить ДО этого скрипта).
;
; Компилируется через Inno Setup Compiler (ISCC.exe), см.
; .github\workflows\build-native.yml для автоматической сборки в CI, либо
; вручную: iscc packaging\native-windows\autosync.iss
;
; Никаких зависимостей от Docker — устанавливает один exe + ярлыки.
; Открывается в собственном окне (WebView2, без Chromium внутри), первый
; запуск настраивается прямо там (мастер /setup).

#define MyAppName "AutoSync"
#define MyAppVersion GetEnv("AUTOSYNC_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "AutoSync Internal"
#define MyAppExeName "autosync.exe"
#define RepoRoot GetEnv("AUTOSYNC_REPO_ROOT")
#if RepoRoot == ""
  #define RepoRoot "..\.."
#endif

[Setup]
AppId={{B6F1B6C0-6C7A-4E9C-9E37-AUTOSYNCAPP1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AutoSync
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#RepoRoot}\dist\native-windows-installer
OutputBaseFilename=autosync-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
; lowest — ставим в профиль пользователя, без прав администратора: ближе
; к "обычному приложению", плюс данные (%LOCALAPPDATA%\AutoSync) и так
; per-user, поэтому системные права для установки не нужны.

[Files]
Source: "{#RepoRoot}\dist\native-windows\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"
Name: "startupicon"; Description: "Запускать AutoSync при входе в Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить AutoSync"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Бинарник и ярлыки убираем, данные пользователя (SQLite, загрузки в
; %LOCALAPPDATA%\AutoSync) — нет, чтобы не потерять базу при переустановке.
Type: files; Name: "{app}\{#MyAppExeName}"
