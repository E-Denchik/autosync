<#
.SYNOPSIS
    Собирает AutoSync в один .exe для Windows (PyInstaller) — аналог
    scripts/build-native-linux.sh, только PyInstaller не кросс-компилирует,
    поэтому этот скрипт обязательно запускать НА Windows.

.DESCRIPTION
    Требует Python 3.11+ и Node.js в PATH. Собирает frontend (npm run build),
    ставит зависимости в backend/.venv-native и запускает PyInstaller с теми
    же флагами, что и Linux-сборка (--collect-all numpy/pandas,
    --hidden-import=logging.config — без них PyInstaller тихо ломает
    динамическую загрузку Alembic-миграций и numpy C-расширений, см.
    комментарии в build-native-linux.sh).

    Результат: dist/native-windows/autosync.exe — используется дальше
    packaging/native-windows/autosync.iss (Inno Setup) для сборки
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

Write-Host "==> Запускаю PyInstaller" -ForegroundColor Cyan
$BuildWork = "$RepoRoot\build\native-windows"
$OutDir = "$RepoRoot\dist\native-windows"
Remove-Item -Recurse -Force $BuildWork, $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BuildWork, $OutDir | Out-Null

Set-Location "$RepoRoot\backend"

pyinstaller `
  --name autosync `
  --onefile `
  --windowed `
  --noconfirm `
  --distpath $OutDir `
  --workpath "$BuildWork\work" `
  --specpath $BuildWork `
  --add-data "$RepoRoot\frontend\dist;frontend_dist" `
  --add-data "$RepoRoot\llm-service;llm_service_src" `
  --add-data "$RepoRoot\backend\migrations;migrations" `
  --add-data "$RepoRoot\packaging\icon;icon" `
  --icon "$RepoRoot\packaging\icon\icon.ico" `
  --hidden-import=waitress `
  --hidden-import=apscheduler.schedulers.background `
  --collect-submodules apscheduler `
  --hidden-import=logging.config `
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
Write-Host "==> Готово: $OutDir\autosync.exe" -ForegroundColor Green
Write-Host "    Дальше: Inno Setup по packaging\native-windows\autosync.iss соберёт установщик."
