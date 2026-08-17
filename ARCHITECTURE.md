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
│   │   │   │   ├── cards.py
│   │   │   │   └── stats.py
│   │   │   ├── repair_orders/          # роуты модуля 2
│   │   │   │   ├── upload.py
│   │   │   │   ├── matching.py
│   │   │   │   └── labor.py            # работы/нормо-часы (approve/reject, правка часов)
│   │   │   ├── nomenclature.py         # номенклатура/остатки: CRUD + загрузка файлом
│   │   │   ├── contracts.py            # каталоги контрактов: CRUD, догрузка файлов, парчасти/нормо-часы
│   │   │   ├── contragents.py
│   │   │   ├── labor_catalog.py        # справочник нормо-часов (ручное ведение)
│   │   │   ├── integrations.py         # статус/проверка/ключи внешних API
│   │   │   └── history.py              # аудит-лог (SCD2), параметризованный поиск
│   │   ├── services/
│   │   │   ├── ozon_client.py          # обёртка Ozon Seller/Performance API
│   │   │   ├── analytics_provider.py   # обёртка стороннего аналитического сервиса
│   │   │   ├── parts_supplier_client.py# обёртка API поставщика запчастей
│   │   │   ├── autodata_client.py      # нормо-часы: локальный справочник + 1С:Альфа-Авто (OData)
│   │   │   ├── labor_matcher.py        # сопоставление строк работ с операциями/нормо-часами
│   │   │   ├── nomenclature_client.py  # номенклатура/остатки: локальный поиск + 1С:Альфа-Авто (OData)
│   │   │   ├── nomenclature_import.py  # парсинг выгрузки номенклатуры (xlsx/ods/csv) в NomenclatureEntry
│   │   │   ├── nomenclature_matcher.py # обогащение PartMatch данными номенклатуры
│   │   │   ├── catalog_sync.py         # синхронизация каталога товаров из Ozon
│   │   │   ├── settings_store.py       # ключи внешних API — в БД (IntegrationSetting)
│   │   │   ├── document_parser.py      # парсинг xlsx/pdf договоров и нарядов
│   │   │   ├── document_generator.py   # генерация итогового заказ-наряда (xlsx)
│   │   │   ├── contract_catalog_import.py # bulk-импорт каталога контракта (парчасти+нормо-часы) в БД
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
│   │   │   │   └── CardGenerator.jsx   # категории, поиск, синк с Ozon, закупочная цена
│   │   │   ├── repair-orders/
│   │   │   │   ├── UploadPage.jsx
│   │   │   │   └── ReviewMatches.jsx   # approve/reject сопоставлений запчастей и работ
│   │   │   └── admin/
│   │   │       ├── Integrations.jsx    # статус/ключи/проверка внешних API
│   │   │       ├── Contragents.jsx
│   │   │       ├── LaborCatalog.jsx    # справочник нормо-часов
│   │   │       ├── NomenclatureCatalog.jsx # номенклатура/остатки: загрузка файлом, поиск, CRUD
│   │   │       └── History.jsx         # аудит-лог, параметризованный поиск
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
├── scripts/                            # build-native-*.sh/ps1, run-native.sh,
│   │                                    #   mock_ozon_api.py (тестовый Seller API)
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

**Модуль 2 (заказ-наряды):**

Договор (Contract) — переиспользуемый каталог контракта/тендера с фиксированным
списком запчастей (`ContractPart`) и нормо-часов (`ContractLaborNorm`), а не
файл, который грузится заново на каждый заказ-наряд. Загружается один раз
(`app/api/contracts.py`, `contract_catalog_import.py` — парсит через
`document_parser.py`: `parse_repair_order_export` для файлов-экспортов
заказ-наряда с разделами работ/материалов, `parse_price_catalog_by_brand` для
каталогов по маркам, иначе плоский прайс-лист) и bulk-insert'ится в БД —
реальные тендерные каталоги легко превышают 10–50 тыс. позиций (см.
`testdata/`), поэтому вставка батчами (`bulk_insert_mappings`) и индексы по
`article`/`operation_name`, а не Python-список в JSON-поле.

```
Пользователь загружает заказ-наряд + либо новый договор, либо ссылку на уже
загруженный каталог контракта (frontend: UploadPage)
  → API принимает → ставит задачу в ThreadPoolExecutor (job_queue.py)
  → repair_order_processor.py (process_upload_job):
      document_parser.py парсит заказ-наряд в таблицу
      если у Contract ещё нет ContractPart/ContractLaborNorm — парсит и
      импортирует его файлы (только один раз на весь контракт)
      matcher.py (match_all_against_contract) сопоставляет каждую строку
      заказ-наряда с каталогом КОНКРЕТНОГО контракта через индексированный
      SQL-запрос по артикулу (не Python-скан):
        1. точное совпадение артикула в ContractPart
        2. если нет — запрос в parts_supplier_client.py (кросс-номера)
        3. если и там нет — llm_client.py сопоставляет по названию (fallback,
           кандидаты — ограниченная SQL-выборка по контракту, не весь каталог)
      nomenclature_matcher.py обогащает каждое совпадение данными склада
      (код/№ кат./производитель/остаток/резерв) через nomenclature_client.py —
      не влияет на confidence, только подтягивает метаданные
      labor_matcher.py сопоставляет строки работ: если у Contract есть
      ContractLaborNorm — СТРОГО только из его списка (match_all_labor_against_contract,
      без подмешивания общего справочника LaborCatalogEntry), иначе — старый
      путь через autodata_client.py/LaborCatalogEntry
  → результат: PartMatch (+ nomenclature_*) и LaborLine записи со статусом confidence
    (exact / cross-ref / llm-guess) и review_status (pending/approved/rejected)
  → фронт: ReviewMatches — человек проверяет позиции и работы с низким confidence
  → генерация итогового документа (document_generator.py, либо загруженный
    Excel-шаблон с плейсхолдерами — document_template_engine.py) — только
    approved-позиции, артикул/название/цена берутся из авторитетного
    каталога контракта (matched_*), не из черновика заказ-наряда
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

- **SQLite** (файл в `data/autosync.db` в корне проекта при запуске из
  исходников; для установленного frozen-бинарника — каталог данных ОС,
  см. `backend/native_app.py:get_data_dir()`) вместо отдельного сервера БД.
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
- **Источник номенклатуры/остатков и нормо-часов заказчика подтверждён** — 1С:Альфа-Авто ПРОФ 5.1,
  один сервер на оба (`ALFAAUTO_BASE_URL`/`ALFAAUTO_LOGIN`/`ALFAAUTO_PASSWORD`, HTTP Basic Auth —
  стандартный протокол 1С OData). Не хватает реального доступа к серверу, чтобы `discover_entities()`
  показал настоящие имена объектов и можно было донастроить `_find_remote()`/`find_norm_hours()`
  (сейчас там имена по стандартному соглашению 1С — предположение, не проверено вживую). Подробности
  и конкретные открытые вопросы — в PROJECT.md, «Ограничения и допущения».
