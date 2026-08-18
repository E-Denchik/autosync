<#
.SYNOPSIS
    Собирает AutoSync для Windows (PyInstaller) — аналог
    scripts/build-native-linux.sh, только PyInstaller не кросс-компилирует,
    поэтому этот скрипт обязательно запускать НА Windows.

.DESCRIPTION
    Требует Python 3.11+ и Node.js в PATH. Собирает frontend (npm run build),
    ставит зависимости в backend/.venv-native и запускает PyInstaller с теми
    же флагами, что и Linux-сборка (--collect-all numpy/pandas,
    --hidden-import=logging.config — без них PyInstaller тихо ломает
    динамическую загрузку Alembic-миграций и numpy C-расширений, см.
    комментарии в build-native-linux.sh).

    --onedir (папка), не --onefile: self-extracting однофайловые сборки
    PyInstaller Windows Defender/антивирусы чаще ошибочно помечают как
    троян (паттерн поведения похож на дроппер) — папку с exe и рядом
    лежащими файлами так не флагает. Пользователю разницы не видно: Inno
    Setup (autosync.iss) всё равно упаковывает всё в один установщик.
    Плюс --version-file — метаданные (издатель/описание/версия) в
    свойствах .exe, тоже снижает подозрительность у SmartScreen.

    Результат: dist/native-windows/autosync/autosync.exe — используется
    дальше packaging/native-windows/autosync.iss (Inno Setup) для сборки
    полноценного установщика.

.EXAMPLE
    .\scripts\build-native-windows.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path "$RepoRoot\backend")) {
    Write-Error "Запускать из корня проекта autosync (не найден backend\)."
    exit 1
}

Write-Host "==> Собираю frontend" -ForegroundColor Cyan
Push-Location "$RepoRoot\frontend"
npm install --silent
# VITE_API_BASE_URL=/api (относительный) — фронт и backend это один и тот
# же процесс/origin (окно pywebview на 127.0.0.1), относительный путь
# резолвится webview против текущего origin сам.
$env:VITE_API_BASE_URL = "/api"
npm run build --silent
Remove-Item Env:\VITE_API_BASE_URL
Pop-Location

Write-Host "==> Готовлю Python-окружение для сборки (backend\.venv-native)" -ForegroundColor Cyan
$VenvDir = "$RepoRoot\backend\.venv-native"
if (-not (Test-Path $VenvDir)) {
    python -m venv $VenvDir
}
& "$VenvDir\Scripts\Activate.ps1"
pip install -q --upgrade pip
pip install -q -r "$RepoRoot\backend\requirements.txt"

Write-Host "==> Ищу Tesseract OCR для встраивания в сборку" -ForegroundColor Cyan
$TesseractDir = $env:TESSERACT_DIR
if (-not $TesseractDir) {
    $candidates = @(
        "$env:ProgramFiles\Tesseract-OCR",
        "${env:ProgramFiles(x86)}\Tesseract-OCR"
    )
    $TesseractDir = $candidates | Where-Object { Test-Path "$_\tesseract.exe" } | Select-Object -First 1
}

$TesseractDataArg = @()
if ($TesseractDir -and (Test-Path "$TesseractDir\tesseract.exe")) {
    if (-not (Test-Path "$TesseractDir\tessdata\rus.traineddata")) {
        Write-Warning "Найден Tesseract в $TesseractDir, но нет tessdata\rus.traineddata — распознавание русского текста в сборке работать не будет."
    }
    Write-Host "    Использую Tesseract из $TesseractDir"
    $TesseractDataArg = @("--add-data", "$TesseractDir;tesseract")
} else {
    Write-Warning "Tesseract OCR не найден (проверьте TESSERACT_DIR) — сборка соберётся, но загрузка сканов/фото работать не будет."
}

Write-Host "==> Готовлю метаданные версии для .exe" -ForegroundColor Cyan
$BuildWork = "$RepoRoot\build\native-windows"
$OutDir = "$RepoRoot\dist\native-windows"
Remove-Item -Recurse -Force $BuildWork, $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BuildWork, $OutDir | Out-Null

$VersionParts = @((Get-Content "$RepoRoot\VERSION" -Raw).Trim() -split '\.')
while ($VersionParts.Count -lt 4) { $VersionParts += '0' }
$VersionTuple = ($VersionParts[0..3] -join ', ')
$VersionDotted = ($VersionParts[0..3] -join '.')
$VersionInfoPath = "$BuildWork\version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($VersionTuple),
    prodvers=($VersionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'AutoSync Internal'),
        StringStruct(u'FileDescription', u'AutoSync - internal auto-service platform'),
        StringStruct(u'FileVersion', u'$VersionDotted'),
        StringStruct(u'InternalName', u'autosync'),
        StringStruct(u'OriginalFilename', u'autosync.exe'),
        StringStruct(u'ProductName', u'AutoSync'),
        StringStruct(u'ProductVersion', u'$VersionDotted')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Path $VersionInfoPath -Encoding UTF8

Write-Host "==> Запускаю PyInstaller" -ForegroundColor Cyan
Set-Location "$RepoRoot\backend"

pyinstaller `
  --name autosync `
  --windowed `
  --noconfirm `
  --distpath $OutDir `
  --workpath "$BuildWork\work" `
  --specpath $BuildWork `
  --version-file $VersionInfoPath `
  --add-data "$RepoRoot\frontend\dist;frontend_dist" `
  --add-data "$RepoRoot\llm-service;llm_service_src" `
  --add-data "$RepoRoot\backend\migrations;migrations" `
  --add-data "$RepoRoot\packaging\icon;icon" `
  @TesseractDataArg `
  --icon "$RepoRoot\packaging\icon\icon.ico" `
  --hidden-import=waitress `
  --hidden-import=apscheduler.schedulers.background `
  --collect-submodules apscheduler `
  --hidden-import=logging.config `
  --hidden-import=pytesseract `
  --collect-all numpy `
  --collect-all pandas `
  --exclude-module PyQt5 `
  --exclude-module PySide2 `
  --exclude-module PySide6 `
  --exclude-module django `
  --exclude-module scipy `
  --exclude-module matplotlib `
  native_app.py
# ^ exclude-module — на некоторых машинах сборки в системном/user Python
# случайно оказываются Django/PyQt5/scipy/matplotlib от других проектов;
# PyInstaller подхватывает их по графу импортов (необязательные хуки
# pandas/SQLAlchemy) и раздувает .exe на сотни лишних мегабайт, хотя
# AutoSync их не использует (см. build-native-linux.sh, где это реально
# наблюдалось).

deactivate

Write-Host ""
Write-Host "==> Готово: $OutDir\autosync\autosync.exe" -ForegroundColor Green
Write-Host "    Дальше: Inno Setup по packaging\native-windows\autosync.iss соберёт установщик."
