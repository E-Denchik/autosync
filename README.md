# AutoSync

Внутренняя платформа для автосервиса, торгующего на Ozon. См. [PROJECT.md](PROJECT.md)
(что и зачем) и [ARCHITECTURE.md](ARCHITECTURE.md) (стек, структура, потоки данных).

## Быстрый старт (Docker Compose)

```bash
cp .env.example .env
# заполнить OZON_*, ANALYTICS_PROVIDER_*, PARTS_SUPPLIER_* по мере получения доступов

docker compose up -d --build
docker compose exec ollama ollama pull qwen2.5:14b   # один раз, модель немаленькая

docker compose exec backend flask db upgrade          # применяется автоматически при старте backend,
                                                        # но можно и вручную
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:5000/api
- LLM-сервис: http://localhost:8000

## Локальная разработка без Docker

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export DATABASE_URL=postgresql://autosync:autosync@localhost:5432/autosync
export FLASK_APP=wsgi.py

flask db upgrade
flask run --port 5000
```

Тесты: `pytest tests/` (используют sqlite in-memory, Postgres не нужен).

**Celery**

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

**LLM-сервис**

```bash
cd llm-service
pip install -r requirements.txt
export OLLAMA_BASE_URL=http://localhost:11434
python server.py
```

Требует локально запущенный Ollama с моделью `qwen2.5:14b` (см. `LLM_MODEL_NAME` в `.env`).

## Состояние на старте

Реализован полный вертикальный скелет обоих модулей — модели, API, Celery-задачи,
matcher, парсер документов, React-фронт, docker-compose. Что осознанно оставлено
как заглушка/TODO до уточнения с заказчиком (см. "Открытые вопросы" в ARCHITECTURE.md):

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
