#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Устанавливает и запускает AutoSync на Windows поверх Docker Desktop.

.DESCRIPTION
    Аналог packaging/deb/postinst для Linux: копирует файлы приложения в
    выбранный каталог, генерирует .env, поднимает docker compose,
    заводит первого администратора и регистрирует автозапуск при входе
    в систему через Планировщик заданий (аналог systemd-юнита на Linux).

    Требует установленный и запущенный Docker Desktop с включённым
    Docker Compose (идёт в комплекте с современными версиями).

.PARAMETER InstallDir
    Каталог установки. По умолчанию C:\AutoSync.

.PARAMETER PublicHost
    Хост/IP, по которому AutoSync будет доступен из браузера. Если не
    указан — определяется автоматически или запрашивается интерактивно.

.PARAMETER FrontendPort
    Порт веб-интерфейса. По умолчанию 5173.

.PARAMETER PullModel
    Скачать LLM-модель qwen2.5:14b (~9 ГБ) сразу при установке.

.PARAMETER AdminEmail
    Email первого администратора.

.PARAMETER AdminPassword
    Пароль первого администратора. Если не задан — генерируется случайный
    и сохраняется в INITIAL_ADMIN_CREDENTIALS.txt в каталоге установки.

.PARAMETER Silent
    Не задавать интерактивные вопросы — использовать параметры/значения
    по умолчанию. Удобно для автоматизации.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Silent -PublicHost 192.168.1.50 -AdminEmail admin@company.ru -PullModel
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\AutoSync",
    [string]$PublicHost,
    [int]$FrontendPort = 5173,
    [switch]$PullModel,
    [string]$AdminEmail,
    [string]$AdminPassword,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

function Write-Section([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host $Message -ForegroundColor Green
}

function Write-Err([string]$Message) {
    Write-Host $Message -ForegroundColor Red
}

# --- 1. Проверка Docker Desktop -------------------------------------------
Write-Section "Проверяю Docker Desktop"

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Err "Docker не найден в PATH."
    Write-Host "Установите Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker Desktop установлен, но не запущен (или ещё не поднялся)."
    Write-Host "Запустите Docker Desktop и повторите установку."
    exit 1
}

docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Err "Docker Compose plugin не найден — обновите Docker Desktop до актуальной версии."
    exit 1
}

Write-Ok "Docker Desktop найден и запущен."

# --- 2. Параметры установки -------------------------------------------------
if (-not $Silent) {
    $inp = Read-Host "Каталог установки [$InstallDir]"
    if ($inp) { $InstallDir = $inp }
}

if (-not $PublicHost) {
    $detected = $null
    try {
        $detected = (Get-NetIPConfiguration -ErrorAction Stop |
            Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
            Select-Object -First 1).IPv4Address.IPAddress
    } catch { $detected = $null }
    if (-not $detected) { $detected = "localhost" }

    if ($Silent) {
        $PublicHost = $detected
    } else {
        $inp = Read-Host "Публичный хост/IP для доступа из браузера [$detected]"
        $PublicHost = if ($inp) { $inp } else { $detected }
    }
}

if (-not $Silent) {
    $inp = Read-Host "Порт веб-интерфейса [$FrontendPort]"
    if ($inp) { $FrontendPort = [int]$inp }

    if (-not $PSBoundParameters.ContainsKey('PullModel')) {
        $inp = Read-Host "Скачать LLM-модель qwen2.5:14b сейчас (~9 ГБ)? [y/N]"
        if ($inp -match '^(y|yes|д|да)$') { $PullModel = $true }
    }
}

if (-not $AdminEmail) {
    if ($Silent) {
        $AdminEmail = "admin@autosync.local"
    } else {
        $inp = Read-Host "Email администратора [admin@autosync.local]"
        $AdminEmail = if ($inp) { $inp } else { "admin@autosync.local" }
    }
}

if (-not $AdminPassword -and -not $Silent) {
    $secure = Read-Host "Пароль администратора (Enter — сгенерировать случайный)" -AsSecureString
    if ($secure.Length -gt 0) {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $AdminPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

# --- 3. Копирование файлов ---------------------------------------------------
Write-Section "Копирую файлы приложения в $InstallDir"

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# robocopy возвращает коды 0-7 как успех (не только 0) — не проверяем $LASTEXITCODE.
robocopy $SourceDir $InstallDir /E /XD ".git" "node_modules" ".venv" "__pycache__" "dist" /XF ".env" *> $null

Write-Ok "Файлы скопированы."

# --- 4. Конфигурация (.env) --------------------------------------------------
$EnvPath = Join-Path $InstallDir ".env"
if (-not (Test-Path $EnvPath)) {
    Copy-Item (Join-Path $InstallDir ".env.example") $EnvPath

    $secretBytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($secretBytes)
    $secretKey = -join ($secretBytes | ForEach-Object { $_.ToString("x2") })

    (Get-Content $EnvPath) |
        ForEach-Object {
            $_ -replace '^SECRET_KEY=.*', "SECRET_KEY=$secretKey" `
               -replace '^FRONTEND_PORT=.*', "FRONTEND_PORT=$FrontendPort" `
               -replace '^VITE_API_BASE_URL=.*', "VITE_API_BASE_URL=http://${PublicHost}:5000/api"
        } | Set-Content $EnvPath

    Write-Ok "Создан $EnvPath"
} else {
    Write-Host "Найден существующий .env — оставляю как есть."
}

New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "uploads") | Out-Null

# --- 5. Запуск docker compose -------------------------------------------------
Write-Section "Собираю и запускаю контейнеры — это может занять несколько минут"

Push-Location $InstallDir
try {
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        Write-Err "docker compose up завершился с ошибкой — см. вывод выше."
        Write-Host "Повторить: docker compose up -d --build (из $InstallDir)"
        exit 1
    }

    # --- 6. Ждём готовности backend ---
    Write-Section "Жду готовности backend"
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        docker compose exec -T backend true *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        Write-Err "backend не поднялся за отведённое время — проверьте: docker compose logs backend"
    }

    # --- 7. Администратор ---
    Write-Section "Создаю администратора"
    $generatedPassword = $false
    if (-not $AdminPassword) {
        $AdminPassword = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
        $generatedPassword = $true
    }

    docker compose exec -T backend flask users create-admin --email $AdminEmail --password $AdminPassword
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Не удалось создать администратора автоматически. Выполните вручную:"
        Write-Host "  docker compose exec backend flask users create-admin --email $AdminEmail --password ..."
    } elseif ($generatedPassword) {
        $credFile = Join-Path $InstallDir "INITIAL_ADMIN_CREDENTIALS.txt"
        "email=$AdminEmail`npassword=$AdminPassword" | Set-Content $credFile
        Write-Ok "Пароль администратора сгенерирован и сохранён в $credFile"
    }

    # --- 8. LLM-модель ---
    if ($PullModel) {
        Write-Section "Загружаю LLM-модель qwen2.5:14b (может занять долгое время)"
        docker compose exec -T ollama ollama pull qwen2.5:14b
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Не удалось скачать модель автоматически. Выполните позже:"
            Write-Host "  docker compose exec ollama ollama pull qwen2.5:14b"
        }
    }

    # --- 9. Автозапуск при входе в систему ---
    Write-Section "Регистрирую автозапуск (Планировщик заданий)"
    try {
        $action = New-ScheduledTaskAction -Execute "docker" -Argument "compose up -d" -WorkingDirectory $InstallDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
        Register-ScheduledTask -TaskName "AutoSync" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        Write-Ok "Задача автозапуска 'AutoSync' зарегистрирована."
    } catch {
        Write-Err "Не удалось зарегистрировать автозапуск: $($_.Exception.Message)"
        Write-Host "AutoSync всё равно работает, просто не поднимется автоматически после перезагрузки."
    }
} finally {
    Pop-Location
}

# --- Итог ---------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " AutoSync установлен и запущен." -ForegroundColor Green
Write-Host " Открыть в браузере: http://${PublicHost}:${FrontendPort}/"
Write-Host " Логин администратора: $AdminEmail"
$credFile = Join-Path $InstallDir "INITIAL_ADMIN_CREDENTIALS.txt"
if (Test-Path $credFile) {
    Write-Host " Пароль сохранён в: $credFile"
}
Write-Host " Каталог установки: $InstallDir"
Write-Host "============================================================" -ForegroundColor Green
