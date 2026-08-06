#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Останавливает и (опционально) полностью удаляет AutoSync.

.PARAMETER InstallDir
    Каталог установки. По умолчанию C:\AutoSync.

.PARAMETER Purge
    Дополнительно удалить Docker-volume'ы (база данных, загруженные
    документы, LLM-модель) и сам каталог установки. Без этого флага
    AutoSync просто останавливается — данные и файлы сохраняются, и
    его можно поднять заново командой `docker compose up -d` из
    каталога установки.

.EXAMPLE
    .\uninstall.ps1
    .\uninstall.ps1 -Purge
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\AutoSync",
    [switch]$Purge
)

$ErrorActionPreference = "Continue"

Write-Host "==> Останавливаю AutoSync" -ForegroundColor Cyan

if (Test-Path (Join-Path $InstallDir "docker-compose.yml")) {
    Push-Location $InstallDir
    if ($Purge) {
        docker compose down -v
    } else {
        docker compose down
    }
    Pop-Location
} else {
    Write-Host "docker-compose.yml не найден в $InstallDir — пропускаю остановку контейнеров."
}

Write-Host "==> Удаляю задачу автозапуска" -ForegroundColor Cyan
Unregister-ScheduledTask -TaskName "AutoSync" -Confirm:$false -ErrorAction SilentlyContinue

if ($Purge) {
    Write-Host "==> Удаляю каталог установки $InstallDir" -ForegroundColor Cyan
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    Write-Host "AutoSync полностью удалён, включая базу данных и загруженные файлы." -ForegroundColor Green
} else {
    Write-Host "AutoSync остановлен. Файлы и данные в $InstallDir сохранены." -ForegroundColor Green
    Write-Host "Запустить заново: cd `"$InstallDir`"; docker compose up -d"
    Write-Host "Удалить полностью: .\uninstall.ps1 -Purge"
}
