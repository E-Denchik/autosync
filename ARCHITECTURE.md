# AutoSync — Architecture

## Стек

| Слой | Технология | Почему |
|---|---|---|
| Backend API | Python + Flask | основной стек разработчика, быстрый старт REST API |
| LLM | Qwen2.5-14B (локально, Ollama/LM Studio) | не зависит от внешних API-ключей, приемлем по цене/скорости для генерации текста и сопоставления |
| БД | SQLite | файл в каталоге данных пользователя, без отдельного сервера БД — приложение ставится на одну машину как обычная программа |
| Асинхронные задачи | `ThreadPoolExecutor` (загрузки) + `APScheduler` (плановый синк цен) | всё выполняется в одном процессе, без брокера очереди |
| Frontend | React | дашборд для approve/reject предложений по цене и карточкам, загрузка документов |
| Парсинг документов | pandas / openpyxl (Excel), pdfplumber (PDF) | стандартный набор для табличных/PDF данных |
| Деплой | PyInstaller-бинарник, собственное окно (pywebview) | один exe/ELF, без Docker и без браузерного доступа — см. «Развёртывание» ниже |

## Внешние интеграции

- **Ozon Seller API / Performance API** — свои товары, продажи, позиции.
- **Сторонний аналитический сервис по Ozon** (MPSTATS / Moneyplace / аналог — уточнить с заказчиком) — данные по конкурентам легально, без прямого скрейпинга.
- **API поставщика запчастей** — цены, наличие, кросс-номера аналогов.

## Структура папок

```
autosync/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── models/                     # SQLAlchemy: Product, PriceSnapshot,
│   │   │                                #   RepairOrder, PartMatch, Contract
│   │   ├── api/
│   │   │   ├── ozon/                   # роуты модуля 1
│   │   │   │   ├── pricing.py
│   │   │   │   └── cards.py
│   │   │   └── repair_orders/          # роуты модуля 2
│   │   │       ├── upload.py
│   │   │       └── matching.py
│   │   ├── services/
│   │   │   ├── ozon_client.py          # обёртка Ozon Seller/Performance API
│   │   │   ├── analytics_provider.py   # обёртка стороннего аналитического сервиса
│   │   │   ├── parts_supplier_client.py# обёртка API поставщика запчастей
│   │   │   ├── document_parser.py      # парсинг xlsx/pdf договоров и нарядов
│   │   │   ├── llm_client.py           # единая точка вызова LLM-сервиса
│   │   │   ├── matcher.py              # логика сопоставления запчастей
│   │   │   ├── price_sync.py           # плановая подтяжка цен/продаж (вызывается APScheduler)
│   │   │   ├── repair_order_processor.py # парсинг+сопоставление (вызывается job_queue)
│   │   │   └── job_queue.py            # постановка задач в ThreadPoolExecutor
│   │   └── utils/
│   ├── migrations/                     # Alembic
│   ├── tests/
│   ├── native_app.py                   # точка входа: окно pywebview + backend + llm-service
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ozon/
│   │   │   │   ├── PricingDashboard.jsx
│   │   │   │   └── CardGenerator.jsx
│   │   │   └── repair-orders/
│   │   │       ├── UploadPage.jsx
│   │   │       └── ReviewMatches.jsx   # approve/reject сопоставлений
│   │   ├── components/
│   │   ├── api/                        # клиенты к backend
│   │   └── App.jsx
│   └── package.json
│
├── llm-service/
│   ├── server.py                       # обёртка над Ollama/LM Studio, отдаёт /generate
│   └── prompts/
│       ├── card_generation.md
│       └── parts_matching.md
│
├── scripts/                            # build-native-*.sh/ps1, run-native.sh
├── packaging/native-deb/, native-windows/
├── PROJECT.md
└── ARCHITECTURE.md
```

## Потоки данных

**Модуль 1 (Ozon), плановый цикл:**
```
APScheduler (по расписанию, раз в 6 часов)
  → price_sync.py: sync_ozon_prices_job()
    → ozon_client.py (свои данные)
    → analytics_provider.py (данные по рынку)
  → сохранение в PriceSnapshot
  → llm_client.py анализирует снимок → предложение по цене/карточке
  → фронт: PricingDashboard показывает предложение → человек approve/reject
```

**Модуль 2 (заказ-наряды), по загрузке файлов:**
```
Пользователь загружает договор + заказ-наряд (frontend)
  → API принимает файлы → ставит задачу в ThreadPoolExecutor (job_queue.py)
  → repair_order_processor.py:
      document_parser.py парсит оба файла в таблицы
      matcher.py сопоставляет позиции:
        1. точное совпадение артикула
        2. если нет — запрос в parts_supplier_client.py (кросс-номера)
        3. если и там нет — llm_client.py сопоставляет по названию (fallback)
  → результат: PartMatch записи со статусом confidence (exact / cross-ref / llm-guess)
  → фронт: ReviewMatches — человек проверяет позиции с низким confidence
  → генерация итогового документа
```

## Ключевые решения и почему

- **LLM как отдельный сервис (`llm-service/`), а не встроен в backend** — оба модуля обращаются к нему через HTTP, легко заменить модель или вынести на отдельную машину с GPU, не трогая backend.
- **Confidence-статусы в сопоставлении запчастей** — LLM-догадка никогда не должна выглядеть так же надёжно, как точное совпадение по API поставщика. Фронт обязан визуально различать эти статусы.
- **Человек в контуре на изменении цен и на low-confidence сопоставлениях** — до накопления статистики точности автоприменение отключено намеренно.
- **Ozon-скрейпинг исключён архитектурно** — данные по конкурентам идут только через легальный сторонний сервис, чтобы не рисковать баном аккаунта клиента.

## Развёртывание: обычное приложение, без Docker и без браузера

AutoSync ставится на одну машину как обычная desktop-программа (заказчик
прямо просил без Docker и без «танцев с бубном») и работает **только**
через собственное окно — никакого браузерного доступа нет ни с этой
машины, ни тем более с других устройств в сети:

- **SQLite** (файл в `~/.autosync/autosync.db`) вместо отдельного сервера БД.
- **`ThreadPoolExecutor`** (обработка загрузок) + **`APScheduler`** (плановый
  синк цен по Ozon) вместо внешнего брокера очереди — см.
  `app/services/job_queue.py`, `app/services/price_sync.py`.
- **`llm-service/server.py`** (обёртка над Ollama/LM Studio) поднят в
  отдельном потоке того же процесса.
- Этот же Flask отдаёт собранный `frontend/dist` как статику — нет
  отдельного nginx/дев-сервера, нет кросс-origin запросов, поэтому CORS не
  используется вовсе.
- **Backend слушает только `127.0.0.1`** (`native_app.py: run_backend`) —
  недоступен ни из браузера на этой машине, ни с других устройств в сети.
  Единственная точка входа — окно pywebview (`native_app.py: run_window`,
  WebView2 на Windows, WebKitGTK на Linux): закрытие окна полностью
  завершает процесс, включая плановый синк цен, без фонового режима/иконки
  в трее.
- Первый администратор создаётся мастером `/setup` в окне приложения при
  первом запуске (либо CLI-командой `flask users create-admin`).
- Упаковка — PyInstaller-бинарник: один exe/ELF, всё вшито
  (`scripts/build-native-*`, `packaging/native-deb/`, `packaging/native-windows/`).

**Почему не Postgres/Docker:** нужно, чтобы один установочный файл ставился
на машину без предварительной установки СУБД/брокера очереди — SQLite и
встроенный планировщик убирают эти внешние зависимости целиком, ценой
худшей горизонтальной масштабируемости (некритично для одного автосервиса
на одной машине).

## Открытые вопросы (не архитектурные решения, а то, что нужно уточнить у заказчика)

- Какой именно сторонний аналитический сервис по Ozon подключаем. Конфигурация и проверка
  подключения (Администрирование → Интеграции, `app/api/integrations.py`) уже готовы — не хватает
  только реальных ключей и точной схемы ответа выбранного провайдера в `analytics_provider.py`.
- Точная схема ответа API поставщика запчастей (какие поля доступны для кросс-референсов).
- Порог confidence, ниже которого сопоставление обязательно уходит на ручную проверку.
