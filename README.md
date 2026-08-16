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
sudo apt install ./autosync-desktop_<версия>_amd64.deb
```
Именно `apt install`, а не `dpkg -i` — так системные зависимости (окно,
Tesseract OCR) подтянутся сами. Дальше — запуск из меню приложений
(«AutoSync») либо `/opt/autosync/autosync`.

**Windows**

Скачать `autosync-setup-<версия>.exe`, запустить, пройти обычный мастер
установки (права администратора не нужны — ставится в профиль пользователя).
Ничего доустанавливать не нужно.

**Требования:** локально установленный [Ollama](https://ollama.com) (или
LM Studio) — нужен только для LLM-функций (предложения по цене, LLM-fallback
сопоставления, генерация карточек, распознавание сканов); всё остальное
работает и без него.

Всё остальное клиент не ставит отдельно — оба пакета самодостаточны:
- Окно приложения: на Linux `.deb` сам подтянет системные пакеты
  (`python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`/`-4.0`) через
  `apt install`; на Windows рантайм WebView2 идёт в составе Windows 10
  (21H2+)/11.
- Tesseract OCR (загрузка сканов/фото документов вместо файла таблицы,
  с русским языковым пакетом): на Linux — тоже зависимость `.deb`,
  `apt install` поставит сам; на Windows бинарник и языковые данные
  запакованы прямо внутри `autosync-setup-<версия>.exe` (см.
  `scripts/build-native-windows.ps1`) — устанавливать Tesseract отдельно
  не нужно.

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

Все API-эндпоинты, кроме `/api/health`, `/api/auth/login`, `/api/auth/login-options`,
`/api/auth/setup*`, требуют заголовок `Authorization: Bearer <token>`. Входа по
паролю нет — вход происходит выбором своей учётной записи из списка
(`/api/auth/login-options`). Публичной регистрации нет —
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
flask users create-admin --email you@company.ru

python native_app.py   # откроет своё окно само; БД и загрузки — в data/ (в корне проекта)
```

Тесты: `pytest tests/` (используют sqlite in-memory).

Запуск из исходников (`python native_app.py`) — это НЕ упакованная сборка,
поэтому Tesseract туда не встроен (см. `native_app.py: configure_tesseract()`
— встраивание срабатывает только для frozen-бинарника). Для разработки OCR
локально доставьте системный `tesseract-ocr`/`tesseract-ocr-rus` сами.

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

**Тестирование синхронизации с Ozon без реального кабинета продавца**

У Ozon нет публичной песочницы, поэтому для проверки каталога/категорий/поиска
без реальных ключей есть локальный мок Seller API (`scripts/mock_ozon_api.py`,
8 тестовых товаров в 3 категориях):

```bash
python scripts/mock_ozon_api.py   # слушает 127.0.0.1:5900

# в другом терминале — направляем AutoSync на мок вместо реального Ozon:
export OZON_SELLER_API_BASE=http://127.0.0.1:5900
export OZON_CLIENT_ID=test
export OZON_API_KEY=test
python backend/native_app.py
```

Дальше в UI: Карточки → «Синхронизировать с Ozon» — товары, категории и поиск
заработают на тестовых данных. С реальными ключами `OZON_SELLER_API_BASE` не
задавайте — тогда клиент по умолчанию идёт на настоящий `api-seller.ozon.ru`.

## Состояние на старте

Оба модуля работают целиком, не только каркас:

**Модуль 1 (Ozon)** — каталог подтягивается только синхронизацией с Ozon Seller
API (`services/catalog_sync.py`, вручную кнопкой «Синхронизировать с Ozon» или
по расписанию раз в 6 часов), с категориями и поиском по каталогу. Закупочная
цена (единственное, что Ozon в принципе не может отдать — это внутренняя
себестоимость продавца) редактируется отдельно, инлайн, на странице Карточки.
LLM предлагает цену с учётом маржи; после одобрения в PricingDashboard цена
реально уходит в Ozon (`ozon_client.update_prices`), а не только меняется
локально. Ключи Ozon Seller/Performance API и стороннего аналитического
сервиса вводятся в UI (Администрирование → Интеграции) и хранятся в базе —
без переменных окружения. Для проверки без реального кабинета продавца есть
локальный мок Ozon Seller API (`scripts/mock_ozon_api.py`, см. раздел выше).

**Модуль 2 (заказ-наряды)** — загрузка, парсинг, сопоставление (точное/кросс-номера/
LLM-fallback), ручная пересвязка, массовые approve-reject, CSV-экспорт,
генерация итогового документа.

Единственный способ развёртывания — обычное desktop-приложение без Docker
(SQLite, ThreadPoolExecutor + APScheduler вместо внешней очереди задач — см.
`app/config.py`, `app/services/job_queue.py`), с готовыми `.deb`/Windows-
инсталляторами.

Что осознанно оставлено как заглушка/TODO до уточнения с заказчиком (см.
"Открытые вопросы" в ARCHITECTURE.md — конфигурация и проверка подключения для
обоих ниже уже готовы, не хватает только реального провайдера/документации):

- **`analytics_provider.py`** — конкретный сторонний сервис (MPSTATS/Moneyplace/аналог)
  не выбран; путь `/v1/competitors` в клиенте — плейсхолдер под нормализованный контракт.
- **`parts_supplier_client.py`** — точная схема ответа API поставщика (какие поля
  доступны для кросс-номеров) не подтверждена; пути `/v1/parts*` — плейсхолдер.
- **`MATCH_CONFIDENCE_THRESHOLD`** (0.75 по умолчанию) — порог, ниже которого
  LLM-сопоставление уходит на обязательную ручную проверку; нужно подтвердить с заказчиком.
- **Ozon Seller/Performance API** (`ozon_client.py`) — эндпоинты реализованы по
  официальной документации и проверены через локальный мок, но не вживую с
  реальными ключами: некоторые поля (особенно у `/v1/product/import/prices` и
  разбор category у `/v3/product/info/list`) может понадобиться скорректировать.

Ozon-скрейпинг исключён архитектурно — не добавляйте его в `ozon_client.py` (см.
PROJECT.md, «Для новых разработчиков»).
