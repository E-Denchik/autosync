import threading
import time

import pytest
import requests

from app.services import llm_settings
from app.services import parallel
from app.services.llm_client import LLMClient, LLMClientError


@pytest.fixture(autouse=True)
def _selected_model(app):
    """_generate() требует явно выбранную модель (см. её собственный
    докстринг про запасной путь на жёстко прошитый "qwen2.5:14b") — тесты
    в этом файле проверяют промпты/ретраи, а не саму логику выбора модели
    (для неё см. test_llm_settings.py), поэтому просто заранее сажаем
    любую модель, как и сделал бы администратор через Настройки → LLM."""
    with app.app_context():
        llm_settings.set_selection("ollama", "qwen2.5:7b")


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def test_test_connection_succeeds_when_model_responds(app, monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(True, {"text": "OK"})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        message = client.test_connection()

    assert "отвечает" in message


def test_generate_concurrency_gate_caps_in_flight_requests_process_wide(app, monkeypatch):
    """_LlmConcurrencyGate — общий на процесс лимит (см. её докстринг в
    llm_client.py про переподписку: файлы каталога x куски текста x
    сопоставление x задания очереди, каждый со своим ThreadPoolExecutor).
    Здесь эмулируем именно это — БОЛЬШЕ потоков зовут _generate() сразу,
    чем разрешено llm_workers() — и проверяем, что реально одновременно
    исполняющихся requests.post никогда не больше лимита, хотя вызывающих
    потоков больше."""
    monkeypatch.setattr(parallel, "llm_workers", lambda: 2)

    lock = threading.Lock()
    state = {"current": 0, "max_seen": 0}

    def fake_post(url, json=None, timeout=None):
        with lock:
            state["current"] += 1
            state["max_seen"] = max(state["max_seen"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return _FakeResponse(True, {"text": "OK"})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient("http://llm-service:8000")

    def _call():
        with app.app_context():
            client.test_connection()

    threads = [threading.Thread(target=_call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["max_seen"] == 2


def test_test_connection_raises_with_real_error_on_failure(app, monkeypatch):
    """Реальный сценарий заказчика: модель выбрана и видна в списке
    скачанных, но раннер падает при попытке её реально загрузить
    (нехватка памяти) — test_connection должен пробросить настоящую
    причину, а не проглотить её."""

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(False, {}, status_code=502, text="out-of-memory during startup")

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.test_connection()
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "out-of-memory" in str(exc)


def test_generate_fails_clearly_without_silently_falling_back_when_no_model_selected(app, monkeypatch):
    """Регрессия: без выбора llm-service тихо подставляет свой запасной
    вариант (в реальном приложении — жёстко прошитый "qwen2.5:14b", ~9+ ГБ
    памяти, поскольку LLM_MODEL_NAME никогда не задаётся), задуманный только
    для ручного curl (см. llm-service/server.py). У заказчика это выглядело
    как случайный out-of-memory на слабой машине после смены модели в
    настройках — на самом деле выбор либо не сохранился, либо сбросился
    (app/api/llm.py: previous_selection), и КАЖДЫЙ запрос уходил на этот
    огромный запасной вариант в обход того, что реально выбрано."""
    with app.app_context():
        llm_settings.clear_selection()

    def must_not_be_called(url, json=None, timeout=None):
        raise AssertionError("не должно уходить в сеть без выбранной модели")

    monkeypatch.setattr("app.services.llm_client.requests.post", must_not_be_called)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "не выбрана" in str(exc)


def test_suggest_price_uses_dedicated_prompt_with_cost_price(app, monkeypatch):
    """Регрессия: suggest_price раньше рендерил card_generation.md (промпт
    для SEO-карточек) вместо своего — LLM не получала инструкцию учитывать
    себестоимость при рекомендации цены."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(True, {"text": '{"suggested_price": 1200, "reasoning": "с учётом себестоимости"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        result = client.suggest_price(
            {"name": "Тормозной диск", "sku": "SKU-1", "cost_price": 800.0},
            {"own_price": 1500, "competitor_min_price": 1400},
        )

    assert result == {"suggested_price": 1200, "reasoning": "с учётом себестоимости"}

    prompt = captured["payload"]["prompt"]
    assert "себестоимост" in prompt  # инструкция из price_suggestion.md
    assert "cost_price" in prompt
    assert "800.0" in prompt
    # card_generation.md ожидает title/bullets — suggest_price их не просит
    assert "bullets" not in prompt


def test_generate_card_content_still_uses_card_generation_prompt(app, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(
            True,
            {"text": '{"title": "т", "bullets": [], "description": "d", "suggested_price": null, "reasoning": "r"}'},
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.generate_card_content({"name": "Товар", "sku": "SKU-1"}, [])

    assert "bullets" in captured["payload"]["prompt"]


def test_generate_retries_do_not_actually_sleep_in_testing_mode(app, monkeypatch):
    """Регрессия: TESTING=True (см. tests/conftest.py: TestConfig) обычно
    означает, что llm-service вообще не запущен — это ожидаемый мгновенный
    ConnectionError, а не "сервис перегружен", для которого задержка между
    попытками имеет смысл. Без этой проверки полный прогон тестов (десятки
    мест с незамоканным LLMClient) вырос с ~1 минуты до ~6.5 — воспроизведено
    и исправлено в этой же сессии. НЕ мокаем time.sleep — тест должен сам
    провалиться по таймауту (через реальное время), если регрессия вернётся."""
    import time as real_time

    def always_fails(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_fails)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        started = real_time.monotonic()
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError:
            pass
        elapsed = real_time.monotonic() - started

    assert elapsed < 0.5  # с реальными паузами (2с x 2 повтора) заняло бы 4+ секунды


def test_generate_retries_transient_network_error_before_succeeding(app, monkeypatch):
    """Регрессия: одиночный сетевой сбой (llm-service ещё не забиндил порт,
    модель грузится в память и т.п.) раньше сразу и безвозвратно ронял
    конкретную позицию/работу в "не найдено" — со второй попытки тот же
    сбой обычно проходит сам."""
    calls = {"n": 0}

    def flaky_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("Connection refused")
        return _FakeResponse(True, {"text": '{"suggested_price": 100, "reasoning": "ок"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", flaky_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        result = client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert result == {"suggested_price": 100, "reasoning": "ок"}
    assert calls["n"] == 3


def test_generate_does_not_retry_local_runner_timeout(app, monkeypatch):
    calls = {"n": 0}

    def always_times_out(url, json=None, timeout=None):
        calls["n"] += 1
        assert timeout == 300
        raise requests.exceptions.Timeout("ollama stalled")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_times_out)
    # LLMClient.__init__ читает таймаут из runtime_settings() (адаптивный
    # режим, зависит от свободной RAM машины, где запущены тесты — см.
    # performance_settings.recommendation) — без фиксации значения здесь
    # тест был бы недетерминированным между машинами (300с при <5.5 ГБ
    # свободной памяти, иначе 180с), что и ловилось в CI, но не локально.
    monkeypatch.setattr(
        "app.services.performance_settings.runtime_settings",
        lambda: {"settings": {"mode": "auto", "workers": 4, "timeout_seconds": 300}},
    )

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        with pytest.raises(LLMClientError, match="ollama не ответил за 300 с"):
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert calls["n"] == 1


def test_generate_raises_after_exhausting_all_retries(app, monkeypatch):
    calls = {"n": 0}

    def always_fails(url, json=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_fails)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "недоступен" in str(exc)

    assert calls["n"] == 3  # не больше и не меньше настроенного числа попыток


def test_generate_retries_transient_5xx_from_llm_service_before_succeeding(app, monkeypatch):
    """Регрессия: llm-service мог вернуть 500/502 (Ollama/LM Studio не
    ответил вовремя, пока грузил модель в память — см. llm-service/server.py)
    — раньше это НЕ ретраилось (ретраился только обрыв соединения к самому
    llm-service), хотя со второй попытки раннер обычно уже прогрелся и
    отвечает нормально. Реальный симптом у заказчика: "llm-service -> 500:
    The server encountered an internal error..." при каждой обработке
    заказ-наряда, хотя ИИ в целом работает."""
    calls = {"n": 0}

    def flaky_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(False, {}, status_code=502, text="ollama не ответил вовремя")
        return _FakeResponse(True, {"text": '{"suggested_price": 100, "reasoning": "ок"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", flaky_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        result = client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert result == {"suggested_price": 100, "reasoning": "ок"}
    assert calls["n"] == 3


def test_generate_raises_after_exhausting_retries_on_persistent_5xx(app, monkeypatch):
    calls = {"n": 0}

    def always_fails(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(False, {}, status_code=500, text="internal error")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_fails)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "500" in str(exc)

    assert calls["n"] == 3  # не больше и не меньше настроенного числа попыток


def test_list_models_sends_vsegpt_key_as_header_not_query_param(app, monkeypatch):
    """Ключ не должен попадать в URL — иначе он echo'ится в текст сетевых
    ошибок/логах (тот же принцип, что и secret_redaction.py для других
    поставщиков)."""
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(True, {"providers": {}})

    monkeypatch.setattr("app.services.llm_client.requests.get", fake_get)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.list_models(vsegpt_api_key="sk-secret")

    assert "sk-secret" not in captured["url"]
    assert captured["headers"] == {"X-VseGPT-Api-Key": "sk-secret"}


def test_list_models_without_vsegpt_key_sends_no_header(app, monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse(True, {"providers": {}})

    monkeypatch.setattr("app.services.llm_client.requests.get", fake_get)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.list_models()

    assert captured["headers"] is None


def test_generate_includes_vsegpt_api_key_when_provider_selected(app, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(True, {"text": '{"suggested_price": 100, "reasoning": "ок"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        llm_settings.set_selection("vsegpt", "openai/gpt-4o-mini")
        app.config["VSEGPT_API_KEY"] = "sk-secret"
        client = LLMClient("http://llm-service:8000")
        client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert captured["payload"]["provider"] == "vsegpt"
    assert captured["payload"]["api_key"] == "sk-secret"


def test_generate_omits_api_key_for_local_providers(app, monkeypatch):
    """Ollama/LM Studio не должны получать поле api_key вовсе — оно нужно
    только облачному vsegpt.ru (см. _generate в llm_client.py)."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(True, {"text": '{"suggested_price": 100, "reasoning": "ок"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert "api_key" not in captured["payload"]


def test_extract_table_from_text_parses_well_formed_json(app, monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(
            True,
            {"text": '{"rows": [{"article": "A1", "name": "Болт", "qty": 2, "price": 10.5}]}'},
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows = client.extract_table_from_text("сырой текст", ["article", "name", "qty", "price"])

    assert rows == [{"article": "A1", "name": "Болт", "qty": 2, "price": 10.5}]


def test_extract_table_from_text_caches_clean_result_across_calls(app, monkeypatch):
    """Регрессия/фича: повторная обработка того же куска текста (например,
    файл загрузили заново, тестируя одно и то же) не должна оплачиваться
    заново — см. services/llm_extraction_cache.py."""
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(True, {"text": '{"rows": [{"article": "A1", "name": "Болт"}]}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows1 = client.extract_table_from_text("один и тот же текст", ["article", "name"])
        rows2 = client.extract_table_from_text("один и тот же текст", ["article", "name"])

    assert rows1 == rows2 == [{"article": "A1", "name": "Болт"}]
    assert calls["n"] == 1  # второй вызов обслужен из кеша, LLM не дёргали


def test_extract_table_from_text_cache_key_ignores_chunking_when_text_differs(app, monkeypatch):
    """Другой текст — другой ключ кеша, промаха быть не должно (LLM
    вызывается заново для реально нового содержимого)."""
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(True, {"text": '{"rows": [{"article": "A1", "name": "Болт"}]}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.extract_table_from_text("текст один", ["article", "name"])
        client.extract_table_from_text("текст два, совсем другой", ["article", "name"])

    assert calls["n"] == 2


def test_extract_table_from_text_does_not_cache_truncated_recovery(app, monkeypatch):
    """Обрезанный/восстановленный ответ НЕ должен попадать в кеш — иначе
    неполный результат застрял бы там навсегда вместо того, чтобы быть
    переспрошенным при следующей обработке того же текста."""
    calls = {"n": 0}

    truncated = '{"rows": [{"article": "A1", "name": "Болт"}, {"article": "A2", "name": "Гай'  # обрыв в конце

    def fake_post(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(True, {"text": truncated})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows1 = client.extract_table_from_text("текст с обрывом", ["article", "name"])
        rows2 = client.extract_table_from_text("текст с обрывом", ["article", "name"])

    # Убеждаемся, что это действительно путь восстановления (не полный
    # отказ) — иначе тест не проверял бы то, что заявлено в его названии.
    assert rows1 == rows2 == [{"article": "A1", "name": "Болт"}]
    assert calls["n"] == 2  # оба раза реально ходили в LLM, кеш не сработал


def test_extract_table_from_text_recovers_rows_from_truncated_json(app, monkeypatch):
    """Регрессия у заказчика: на большой таблице (сотни позиций) раннер
    обрезает ответ по лимиту токенов посреди JSON — весь разбор файла
    падал с "llm-service вернул невалидный JSON", хотя почти все строки
    в ответе распознались нормально. Полные строки до обрыва должны
    восстановиться, а не пропадать вместе с одной обломанной хвостовой."""
    truncated = (
        '{\n  "rows": [\n'
        '    {"article": "0083032200", "name": "ШТИФТ БЕЗ РЕЗЬБЫ", "qty": null, "price": 42.75},\n'
        '    {"article": "008408182A", "name": "ШТИФТ БЕЗ РЕЗЬБЫ", "qty": null, "price": 32.345},\n'
        '    {"article": "0112104221", "name": "БОЛТ'  # обрыв ответа посреди строки
    )

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(True, {"text": truncated})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows = client.extract_table_from_text("сырой текст", ["article", "name", "qty", "price"])

    assert rows == [
        {"article": "0083032200", "name": "ШТИФТ БЕЗ РЕЗЬБЫ", "qty": None, "price": 42.75},
        {"article": "008408182A", "name": "ШТИФТ БЕЗ РЕЗЬБЫ", "qty": None, "price": 32.345},
    ]


def test_extract_table_from_text_raises_when_nothing_recoverable(app, monkeypatch):
    """Полностью нечитаемый ответ (0 восстановленных строк) — по-прежнему
    настоящая ошибка, а не тихо пустой результат."""

    def fake_post(url, json=None, timeout=None):
        return _FakeResponse(True, {"text": "не JSON вообще, а голый текст ошибки раннера"})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.extract_table_from_text("сырой текст", ["article", "name"])
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "невалидный JSON" in str(exc)


def test_extract_table_from_text_splits_long_input_into_multiple_requests(app, monkeypatch):
    """Регрессия: раньше текст жёстко обрезался до 12000 символов ПЕРЕД
    отправкой — все строки за этой границей никогда не попадали в запрос
    вообще, независимо от того, обрывался ли ответ модели. Длинный текст
    (много строк) должен уйти несколькими запросами, а не потерять хвост."""
    calls = []
    # 50 строк по ~90 символов = далеко за старым обрезанием в 12000,
    # и заведомо больше одного куска по 4000 символов (fields <= 5).
    raw_text = "\n".join(f"АРТИКУЛ-{i:04d} НАЗВАНИЕ ПОЗИЦИИ НОМЕР {i} ЦЕНА 100.50" for i in range(200))

    def fake_post(url, json=None, timeout=None):
        calls.append(json["prompt"])
        # Каждый запрос "распознаёт" одну строку-заглушку — важно само
        # число запросов и то, что результаты всех кусков попадают в ответ.
        idx = len(calls)
        return _FakeResponse(True, {"text": f'{{"rows": [{{"article": "A{idx}", "name": "n", "qty": 1, "price": 1}}]}}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows = client.extract_table_from_text(raw_text, ["article", "name", "qty", "price"])

    assert len(calls) > 1  # текст реально ушёл несколькими запросами, не одним обрезанным
    assert len(rows) == len(calls)  # результаты со всех кусков собраны вместе, ничего не потеряно


def test_extract_table_from_text_uses_smaller_chunks_for_wide_field_lists(app, monkeypatch):
    """Чем больше полей на строку (шире таблица), тем компактнее должен
    быть кусок текста на один запрос — иначе на той же таблице ответ
    (JSON с большим числом полей на строку) с большей вероятностью
    обрежется по лимиту токенов раннера."""
    # 300 строк по ~40 символов = ~12000 символов — заведомо больше обоих
    # порогов кусков (4000 и 2200), чтобы оба случая реально разбились
    # на несколько кусков и было что сравнивать.
    raw_text = "\n".join(f"строка номер {i:04d} какой-то текст" for i in range(300))
    narrow_fields = ["a", "b", "c"]
    wide_fields = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"]  # как у номенклатуры (11 полей)

    def make_fake_post(calls):
        def fake_post(url, json=None, timeout=None):
            calls.append(1)
            return _FakeResponse(True, {"text": '{"rows": []}'})

        return fake_post

    narrow_calls, wide_calls = [], []
    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        monkeypatch.setattr("app.services.llm_client.requests.post", make_fake_post(narrow_calls))
        client.extract_table_from_text(raw_text, narrow_fields)
        monkeypatch.setattr("app.services.llm_client.requests.post", make_fake_post(wide_calls))
        client.extract_table_from_text(raw_text, wide_fields)

    assert len(wide_calls) > len(narrow_calls)


def test_extract_table_from_text_skips_one_unrecoverable_chunk_and_keeps_the_rest(app, monkeypatch):
    """Один совсем не разобравшийся кусок текста не должен ронять разбор
    остальных — частичный результат лучше отказа прочитать файл целиком.

    Куски теперь разбираются параллельно (см. extract_table_from_text:
    map_with_app_context), поэтому какой физический вызов requests.post
    случится первым — не определено. Помечаем "ломающийся" кусок по
    содержимому (первая строка исходного текста), а не по порядковому
    номеру вызова, иначе тест был бы гонкой потоков."""
    raw_text = "\n".join(f"строка номер {i:04d} какой-то текст" for i in range(300))
    lock = threading.Lock()
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        with lock:
            calls["n"] += 1
        if "строка номер 0000" in json["prompt"]:  # маркер именно первого куска
            return _FakeResponse(True, {"text": "совсем не JSON, раннер сломался на этом куске"})
        return _FakeResponse(True, {"text": '{"rows": [{"a": "ok"}]}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        rows = client.extract_table_from_text(raw_text, ["a"])

    assert calls["n"] > 1  # действительно было несколько кусков
    assert all(r == {"a": "ok"} for r in rows)
    assert len(rows) == calls["n"] - 1  # ровно один (первый) кусок пропущен, остальные учтены


def test_generate_does_not_retry_on_clean_http_error_response(app, monkeypatch):
    """Ошибка вида "модель не найдена"/400 — не сетевой сбой, повтор её не
    исправит, только зря тратит время (до 3 x таймаут)."""
    calls = {"n": 0}

    def bad_response(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(False, {}, status_code=400, text="model not found")

    monkeypatch.setattr("app.services.llm_client.requests.post", bad_response)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: (_ for _ in ()).throw(AssertionError("не должно вызываться")))

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError:
            pass

    assert calls["n"] == 1


def test_generate_error_unwraps_llm_service_json_instead_of_dumping_it_raw(app, monkeypatch):
    """Регрессия: llm-service отдаёт ошибки как {"error": "текст"} (см.
    llm-service/server.py: jsonify(error=...)) — раньше LLMClientError
    просто дублировал resp.text целиком, и пользователь в итоге видел
    двойную JSON-обёртку с экранированными кавычками (именно так выглядела
    ошибка нехватки баланса vsegpt.ru). Сообщение должно быть чистым
    текстом, без фигурных скобок и \" вокруг него."""
    human_message = (
        "Закончился баланс на аккаунте vsegpt.ru — пополните на https://vsegpt.ru/User/Money "
        "(vsegpt -> 400: You have only -2.66 on account...)"
    )

    def bad_response(url, json=None, timeout=None):
        return _FakeResponse(False, {"error": human_message}, status_code=400, text=f'{{"error": "{human_message}"}}')

    monkeypatch.setattr("app.services.llm_client.requests.post", bad_response)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: (_ for _ in ()).throw(AssertionError("не должно вызываться")))

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            message = str(exc)
            assert human_message in message
            assert '{"error"' not in message  # не осталось сырой JSON-обёртки
