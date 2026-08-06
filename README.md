# AutoSync

Внутренняя платформа для автосервиса, торгующего на Ozon. См. [PROJECT.md](PROJECT.md)
(что и зачем) и [ARCHITECTURE.md](ARCHITECTURE.md) (стек, структура, потоки данных).

Есть два независимых способа развернуть AutoSync:

1. **Обычное приложение** (рекомендуется для одного автосервиса/одной машины) —
   один исполняемый файл, без Docker, без сервера БД. Ставится как любая
   desktop-программа, открывается в собственном окне — не в браузере.
2. **Docker Compose** (для серверного/масштабируемого развёртывания) —
   PostgreSQL + Redis + Celery, несколько контейнеров, ближе к продакшен-стеку
   из ARCHITECTURE.md.

## Вариант 1 — обычное приложение (без Docker)

Работает и на Linux, и на Windows. SQLite вместо Postgres, встроенный
планировщик задач вместо Celery/Redis — всё приложение (backend + LLM-обёртка
+ фронт) это один процесс. Открывается в своём окне (pywebview — системный
webview: WebView2 на Windows, WebKitGTK на Linux, никакого Chromium внутри) —
единая точка входа, закрытие окна полностью завершает приложение. Первый
запуск сам предложит создать администратора прямо в этом окне — командной
строки не требуется. Backend слушает все интерфейсы, поэтому пока окно
открыто, AutoSync доступен и из браузера с телефона/другого ПК в той же
сети — по адресу этой машины.

**Linux**

```bash
sudo dpkg -i autosync-desktop_<версия>_amd64.deb
```
Дальше — запуск из меню приложений («AutoSync») либо `/opt/autosync/autosync`.

**Windows**

Скачать `autosync-setup-<версия>.exe`, запустить, пройти обычный мастер
установки (права администратора не нужны — ставится в профиль пользователя).

**Требования:** локально установленный [Ollama](https://ollama.com) — нужен
только для LLM-функций (предложения по цене, LLM-fallback сопоставления,
генерация карточек); всё остальное работает и без него. На Linux `.deb`
сам подтянет системные пакеты для окна (`python3-gi`, `gir1.2-gtk-3.0`,
`gir1.2-webkit2-4.1`/`-4.0`) — обычно они уже стоят на любом десктопе с
GNOME/XFCE/подобным окружением. На Windows ничего доставлять не нужно —
рантайм WebView2 идёт в составе Windows 10 (21H2+)/11.

### Быстрый запуск на Linux из исходников (без установки .deb)

```bash
./scripts/run-native.sh   # соберёт бинарник при первом запуске, дальше просто откроет окно
```

### Сборка этих пакетов из исходников

```bash
./scripts/build-native-linux.sh   # -> dist/native-linux/autosync (сам бинарник)
./scripts/build-native-deb.sh     # -> dist/autosync-desktop_<версия>_amd64.deb

# Windows — обязательно запускать НА Windows, PyInstaller не кросс-компилирует:
.\scripts\build-native-windows.ps1        # -> dist\native-windows\autosync.exe
# затем Inno Setup по packaging\native-windows\autosync.iss -> установщик .exe
```

Оба .exe/.deb автоматически собираются в CI на реальных Linux- и
Windows-раннерах: `.github/workflows/build-native.yml`, публикует готовые
файлы в GitHub Release по тегу `vX.Y.Z`.

## Вариант 2 — Docker Compose (сервер)

```bash
cp .env.example .env
# заполнить OZON_*, ANALYTICS_PROVIDER_*, PARTS_SUPPLIER_* по мере получения доступов
# ОБЯЗАТЕЛЬНО заменить SECRET_KEY на случайную строку (openssl rand -hex 32) вне локальной разработки

docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:14b   # один раз, модель немаленькая

docker compose exec backend flask users create-admin --email you@company.ru --password ...
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:5000/api
- LLM-сервис: http://localhost:8000

Работает и на Windows через Docker Desktop (WSL2-бэкенд) — контейнеры всегда
Linux, стек не требует изменений под хост.

### Сборка `.deb`/Windows-пакета для Docker-варианта

```bash
./scripts/build-deb.sh               # -> dist/autosync_<версия>_all.deb (Linux)
./scripts/build-windows-package.sh   # -> dist/autosync-windows_<версия>.zip (Windows)
```

`dpkg -i` / `install.ps1` интерактивно спрашивают каталог установки, публичный
хост/IP, порт, LLM-модель и данные администратора, сами поднимают
`docker compose up -d --build` и регистрируют автозапуск (systemd-юнит на
Linux, Планировщик заданий на Windows). Подробности — в
[packaging/windows/README-WINDOWS.md](packaging/windows/README-WINDOWS.md) и
файлах `packaging/deb/`.

## Авторизация (общее для обоих вариантов)

Все API-эндпоинты, кроме `/api/health`, `/api/auth/login`, `/api/auth/setup*`,
требуют заголовок `Authorization: Bearer <token>`. Публичной регистрации нет —
первого администратора создаёт либо мастер `/setup` в окне приложения (native-режим),
либо CLI-команда `flask users create-admin` (Docker-режим); новых пользователей
дальше заводит уже сам администратор через страницу «Пользователи» в UI.

## Локальная разработка

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt      # Docker/Postgres-режим разработки
# pip install -r requirements-native.txt # либо native-режим (SQLite, без Celery/Redis)

export DATABASE_URL=postgresql://autosync:autosync@localhost:5432/autosync
export FLASK_APP=wsgi.py

flask db upgrade
flask users create-admin --email you@company.ru --password ...
flask run --port 5000
```

Тесты: `pytest tests/` (используют sqlite in-memory, Postgres не нужен).

Native-режим без сборки в exe — просто `python backend/native_app.py`
(нужен `requirements-native.txt`, см. выше; на Linux — venv с
`--system-site-packages`, окну нужен системный `gi`/webkit2gtk, см. Вариант 1
выше); откроет своё окно само, БД и загрузки — в `~/.autosync/`.

**Celery** (только для Docker-режима — в native-режиме не нужен вовсе)

```bash
celery -A celery_worker.celery worker --loglevel=info
celery -A celery_worker.celery beat --loglevel=info   # плановая подтяжка цен по Ozon
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

**LLM-сервис** (в native-режиме поднимается автоматически внутри native_app.py)

```bash
cd llm-service
pip install -r requirements.txt
export OLLAMA_BASE_URL=http://localhost:11434
python server.py
```

Требует локально запущенный Ollama с моделью `qwen2.5:14b` (см. `LLM_MODEL_NAME`).

## Состояние на старте

Реализован полный вертикальный скелет обоих модулей — модели, API, JWT-авторизация
(роли admin/operator, доступ выдаётся вручную), ручная пересвязка/массовые
approve-reject/CSV-экспорт сопоставлений в модуле заказ-нарядов. Два независимых
пути развёртывания: Docker Compose (Celery/Redis/Postgres, ближе к
ARCHITECTURE.md) и native-приложение без Docker (SQLite, ThreadPoolExecutor +
APScheduler вместо Celery — см. `app/config.py: NativeConfig`,
`app/services/job_queue.py`) с готовыми `.deb`/Windows-инсталляторами под оба
варианта. Что осознанно оставлено как заглушка/TODO до уточнения с заказчиком
(см. "Открытые вопросы" в ARCHITECTURE.md):

- **`analytics_provider.py`** — конкретный сторонний сервис (MPSTATS/Moneyplace/аналог)
  не выбран; путь `/v1/competitors` в клиенте — плейсхолдер под нормализованный контракт.
- **`parts_supplier_client.py`** — точная схема ответа API поставщика (какие поля
  доступны для кросс-номеров) не подтверждена; пути `/v1/parts*` — плейсхолдер.
- **`MATCH_CONFIDENCE_THRESHOLD`** (0.75 по умолчанию, `.env`) — порог, ниже которого
  LLM-сопоставление уходит на обязательную ручную проверку; нужно подтвердить с заказчиком.
- **Ozon Seller/Performance API** (`ozon_client.py`) — эндпоинты реализованы по
  официальной документации, но не протестированы вживую без реальных ключей.

Ozon-скрейпинг исключён архитектурно — не добавляйте его в `ozon_client.py` (см.
PROJECT.md, «Для новых разработчиков»).
