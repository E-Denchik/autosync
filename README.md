# AutoSync

Внутренняя платформа для автосервиса, торгующего на Ozon. См. [PROJECT.md](PROJECT.md)
(что и зачем) и [ARCHITECTURE.md](ARCHITECTURE.md) (стек, структура, потоки данных).

AutoSync — обычное desktop-приложение, без Docker и без браузерного доступа:
один исполняемый файл, без сервера БД, работает **только** через собственное
окно (pywebview — системный webview: WebView2 на Windows, WebKitGTK на
Linux, никакого Chromium внутри). Backend слушает исключительно
`127.0.0.1` — AutoSync недоступен ни из браузера на этой машине, ни тем
более с других устройств в сети. Закрытие окна полностью завершает
приложение. Первый запуск сам предложит создать администратора прямо в
этом окне — командной строки не требуется.

## Установка

**Linux**

```bash
sudo dpkg -i autosync-desktop_<версия>_amd64.deb
```
Дальше — запуск из меню приложений («AutoSync») либо `/opt/autosync/autosync`.

**Windows**

Скачать `autosync-setup-<версия>.exe`, запустить, пройти обычный мастер
установки (права администратора не нужны — ставится в профиль пользователя).

**Требования:** локально установленный [Ollama](https://ollama.com) (или
LM Studio) — нужен только для LLM-функций (предложения по цене, LLM-fallback
сопоставления, генерация карточек); всё остальное работает и без него. На
Linux `.deb` сам подтянет системные пакеты для окна (`python3-gi`,
`gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`/`-4.0`) — обычно они уже стоят на
любом десктопе с GNOME/XFCE/подобным окружением. На Windows ничего
доставлять не нужно — рантайм WebView2 идёт в составе Windows 10
(21H2+)/11.

## Быстрый запуск на Linux из исходников (без установки .deb)

```bash
./scripts/run-native.sh   # соберёт бинарник при первом запуске, дальше просто откроет окно
```

## Сборка пакетов из исходников

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

## Авторизация

Все API-эндпоинты, кроме `/api/health`, `/api/auth/login`, `/api/auth/setup*`,
требуют заголовок `Authorization: Bearer <token>`. Публичной регистрации нет —
первого администратора создаёт мастер `/setup` в окне приложения при первом
запуске (либо CLI-команда `flask users create-admin`); новых пользователей
дальше заводит уже сам администратор через страницу «Пользователи» в UI.

## Локальная разработка

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export FLASK_APP=wsgi.py
flask db upgrade
flask users create-admin --email you@company.ru --password ...

python native_app.py   # откроет своё окно само; БД и загрузки — в ~/.autosync/
```

Тесты: `pytest tests/` (используют sqlite in-memory).

**Frontend**

```bash
cd frontend
npm install
VITE_API_BASE_URL=/api npm run build   # относительный путь — тот же процесс отдаёт и API, и статику
```

Frontend не запускается отдельным dev-сервером (`npm run dev`) в обычном
режиме работы — `native_app.py` отдаёт уже собранный `frontend/dist`
напрямую, тем же процессом, что и API, без браузерного доступа. Для
итеративной разработки UI собирайте `npm run build` после каждого
изменения и перезапускайте `python native_app.py`.

**LLM-сервис** (в обычном режиме поднимается автоматически внутри `native_app.py`)

```bash
cd llm-service
pip install -r requirements.txt
export OLLAMA_BASE_URL=http://localhost:11434
python server.py
```

Требует локально запущенный Ollama (или LM Studio) — конкретную модель
выбирает администратор в UI (Администрирование → LLM-модель).

## Состояние на старте

Реализован полный вертикальный скелет обоих модулей — модели, API, JWT-авторизация
(роли admin/operator, доступ выдаётся вручную), ручная пересвязка/массовые
approve-reject/CSV-экспорт сопоставлений в модуле заказ-нарядов. Единственный
способ развёртывания — обычное desktop-приложение без Docker (SQLite,
ThreadPoolExecutor + APScheduler вместо внешней очереди задач — см.
`app/config.py`, `app/services/job_queue.py`), с готовыми `.deb`/Windows-
инсталляторами. Что осознанно оставлено как заглушка/TODO до уточнения с
заказчиком (см. "Открытые вопросы" в ARCHITECTURE.md):

- **`analytics_provider.py`** — конкретный сторонний сервис (MPSTATS/Moneyplace/аналог)
  не выбран; путь `/v1/competitors` в клиенте — плейсхолдер под нормализованный контракт.
- **`parts_supplier_client.py`** — точная схема ответа API поставщика (какие поля
  доступны для кросс-номеров) не подтверждена; пути `/v1/parts*` — плейсхолдер.
- **`MATCH_CONFIDENCE_THRESHOLD`** (0.75 по умолчанию) — порог, ниже которого
  LLM-сопоставление уходит на обязательную ручную проверку; нужно подтвердить с заказчиком.
- **Ozon Seller/Performance API** (`ozon_client.py`) — эндпоинты реализованы по
  официальной документации, но не протестированы вживую без реальных ключей.

Ozon-скрейпинг исключён архитектурно — не добавляйте его в `ozon_client.py` (см.
PROJECT.md, «Для новых разработчиков»).
