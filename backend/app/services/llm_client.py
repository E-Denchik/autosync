"""Единая точка вызова LLM-сервиса (llm-service/server.py, Qwen2.5).

Backend никогда не обращается к Ollama/vLLM напрямую — только через этот
HTTP-клиент, чтобы модель/хост можно было заменить, не трогая backend
(см. ARCHITECTURE.md: «Ключевые решения»).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager

import requests

logger = logging.getLogger(__name__)


def _llm_service_error_detail(resp: requests.Response) -> str:
    """Достаёт читаемое сообщение из тела ответа llm-service вместо сырого
    JSON целиком — llm-service сам уже выбрал понятную формулировку (см.
    llm-service/server.py: _error_detail/_vsegpt_error_message) и завернул
    её в {"error": "..."}; без этой распаковки пользователь видел бы
    двойную обёртку JSON (экранированные кавычки и т.п. — именно так
    выглядела ошибка нехватки баланса vsegpt.ru до этого исправления)."""
    try:
        data = resp.json()
    except ValueError:
        return resp.text
    error = data.get("error")
    return error if isinstance(error, str) and error else resp.text


def _recover_truncated_rows(text: str) -> list[dict]:
    """Лучшее из возможного восстановление построчных объектов из
    оборванного JSON-ответа ocr_table_extraction.md — раннер иногда режет
    ответ по лимиту токенов на очень длинных таблицах (сотни позиций),
    получается невалидный JSON вместо смыслового результата.

    Строчные объекты в этом формате плоские (только строки/числа/null, без
    вложенных {}/[] — см. сам промпт), поэтому каждая пара фигурных скобок
    без фигурных скобок внутри — это ровно одна строка целиком. Последняя
    строка, обрубленная посередине обрывом ответа, не находит закрывающую
    скобку и естественно выпадает — что и нужно, включать её обломок было
    бы хуже, чем просто её не найти."""
    recovered = []
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            recovered.append(obj)
    return recovered


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Режет текст на куски по границам строк, каждый не длиннее max_chars
    — используется в extract_table_from_text вместо одного жёсткого
    обрезания всего текста по фиксированной длине, чтобы обработать файл
    целиком, а не только его начало.

    Не пытается угадать, где именно проходит граница строки исходной
    таблицы в OCR/PDF-тексте — это тот же компромисс, что уже был в этом
    коде и без разбиения на куски (см. document_parser.py: OCR/PDF-текст
    изначально нечёткий, для его интерпретации и нужна LLM, а не жёсткий
    построчный парсер). Одна строка исходного текста длиннее max_chars
    (например, один OCR-блок без переносов) попадает в свой кусок как
    есть, не разрывается посередине."""
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1  # +1 за перевод строки
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


# Локальный llm-service (Ollama и т.п.) нередко на первом запросе после
# простоя грузит модель в память по несколько секунд, плюс сеть между
# процессами на одной машине изредка отдаёт мгновенный ConnectionRefused,
# если процесс ещё не успел забиндить порт (гонка при старте приложения) —
# оба случая проходят сами со второй попытки. Раньше ЛЮБОЙ сбой сети
# (даже такой сиюминутный) сразу и безвозвратно ронял конкретную
# позицию/работу в "не найдено" на весь заказ-наряд.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0
_LOCAL_LLM_TIMEOUT_SECONDS = int(os.environ.get("AUTOSYNC_LLM_TIMEOUT_SECONDS", "300"))
_REMOTE_LLM_TIMEOUT_SECONDS = 200
_VSEGPT_STATUS_TIMEOUT_SECONDS = 15


class _LlmConcurrencyGate:
    """Общий на ВЕСЬ процесс лимит одновременных запросов к раннеру —
    сколько бы независимых пулов потоков ни вызвало _generate() одновременно
    (файлы каталога договора, куски текста внутри одного из этих файлов,
    сопоставление запчастей, сопоставление работ, до 2 таких деревьев сразу
    из job_queue.py) — см. docstring parallel.py про то, почему каждый
    уровень сам по себе созданный ThreadPoolExecutor(max_workers=llm_workers())
    не спасает: адаптивный лимит рассчитан как бюджет НА ВЕСЬ процесс, а не
    на каждый уровень вложенности отдельно, и без общей точки схождения
    4 уровня по 4 потока дают до 16-32 одновременных запросов к одной и той
    же модели вместо задуманных 1-4.

    Это счётчик с condition variable, а НЕ общий ThreadPoolExecutor — если
    бы несколько уровней сами по себе сабмитили задачи в один и тот же
    пул, поток, уже занявший воркер и ждущий результата ВЛОЖЕННОГО submit
    в тот же пул, мог бы дедлокнуться (пула не хватит выполнить вложенную
    задачу, потому что все воркеры заняты ожиданием). Здесь же поток просто
    блокируется на acquire() — не в каком-то пуле, а сам по себе, — и это
    безопасно на любую глубину вложенности.

    Лимит читается ЖИВЫМ на каждой попытке взять слот (не сохраняется на
    момент создания): performance_settings.py может поменять его по ходу
    дела (adaptive-режим реагирует на свободную память), а parallel.py
    может понизить его до 1 сразу после обнаружения CPU-only раннера
    (см. _slow_runner_active) — оба изменения должны сработать немедленно
    для уже стоящих в очереди запросов, а не только для новых."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._in_flight = 0

    @contextmanager
    def slot(self):
        from app.services.parallel import llm_workers

        with self._condition:
            # wait(timeout=...) вместо голого wait() — лимит мог вырасти,
            # пока мы ждали (память освободилась, TTL медленного раннера
            # истёк), а notify() уходит только при release(), которого
            # может долго не быть, если другие слоты заняты надолго.
            while self._in_flight >= llm_workers():
                self._condition.wait(timeout=1.0)
            self._in_flight += 1
        try:
            yield
        finally:
            with self._condition:
                self._in_flight -= 1
                self._condition.notify()


_concurrency_gate = _LlmConcurrencyGate()


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    # Локальный раннер получает ограниченное время: после таймаута повторять
    # такой же тяжёлый запрос бессмысленно. Для vsegpt ниже сохраняется
    # отдельный, более длинный timeout.
    def __init__(self, base_url: str, timeout: int = _LOCAL_LLM_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        try:
            from app.services.performance_settings import runtime_settings

            self.timeout = runtime_settings()["settings"]["timeout_seconds"]
        except RuntimeError:
            self.timeout = timeout

    def list_models(self, vsegpt_api_key: str | None = None) -> dict:
        """Discovery всех LLM-провайдеров, которые видит llm-service: что
        реально скачано на этой машине (Ollama, LM Studio) плюс облачные
        модели vsegpt.ru, если передан ключ (заголовком, не query-параметром
        — тот же принцип, что и secret_redaction.py: секрет не должен
        попадать в URL, который echo'ится в текст сетевых ошибок/логов)."""
        headers = {"X-VseGPT-Api-Key": vsegpt_api_key} if vsegpt_api_key else None
        try:
            # /models для vsegpt внутри llm-service получает сначала баланс,
            # затем список моделей; один общий timeout backend должен покрывать
            # оба внешних запроса, иначе discovery ложно выглядит недоступным.
            resp = requests.get(f"{self.base_url}/models", headers=headers, timeout=_VSEGPT_STATUS_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as exc:
            raise LLMClientError(f"llm-service недоступен: {exc}") from exc
        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {_llm_service_error_detail(resp)}")
        return resp.json()

    def vsegpt_status(self, api_key: str | None = None) -> dict:
        headers = {"X-VseGPT-Api-Key": api_key} if api_key else None
        try:
            # llm-service сначала обращается к vsegpt.ru и только затем
            # возвращает JSON. Не обрываем этот административный запрос раньше
            # внутреннего timeout шлюза.
            resp = requests.get(
                f"{self.base_url}/vsegpt/status", headers=headers, timeout=_VSEGPT_STATUS_TIMEOUT_SECONDS
            )
        except requests.exceptions.RequestException as exc:
            raise LLMClientError(f"llm-service недоступен: {exc}") from exc
        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {_llm_service_error_detail(resp)}")
        return resp.json()

    def test_connection(self) -> str:
        """Настоящий пробный запрос к уже выбранной модели — дожидается
        реального ответа раннера (Ollama/LM Studio), а не просто проверяет,
        что модель есть в списке скачанных (list_models). Модель может
        числиться на диске и при этом не влезать в доступную память —
        list_models этого не поймает, а именно на этом заказчик спотыкался
        (см. UploadPage.jsx: предварительная проверка перед загрузкой
        файлов, чтобы узнать об этом ДО, а не посреди обработки)."""
        self._generate("Ответь одним словом: OK", json_response=False)
        return "Модель отвечает, можно продолжать."

    def _generate(self, prompt: str, *, json_response: bool = False) -> str:
        from flask import current_app

        from app.services.llm_settings import get_selection

        selection = get_selection()
        if selection is None:
            # Без выбора llm-service тихо подставляет свой запасной вариант
            # (переменные окружения LLM_PROVIDER/LLM_MODEL_NAME, а без них —
            # жёстко прошитый "qwen2.5:14b", ~9+ ГБ памяти) — этот запасной
            # путь задуман только для ручного curl/обратной совместимости
            # (см. докстринг llm-service/server.py), а не для реальной
            # работы приложения. Раньше это выглядело как случайный
            # out-of-memory на слабой машине, хотя причина была в том, что
            # администратор просто не выбрал модель (или выбор сбросился,
            # см. app/api/llm.py: previous_selection) — теперь ошибка сразу
            # называет настоящую причину.
            raise LLMClientError(
                "Модель ИИ не выбрана — откройте Администрирование → LLM-модель и выберите модель."
            )
        payload = {
            "prompt": prompt,
            "json_response": json_response,
            "provider": selection.provider,
            "model": selection.model_name,
        }
        request_timeout = (
            _REMOTE_LLM_TIMEOUT_SECONDS if selection.provider == "vsegpt" else self.timeout
        )
        if selection.provider == "vsegpt":
            # Ключ хранится только в backend (БД, см. settings_store.py) —
            # llm-service его нигде не держит, поэтому передаём с каждым
            # запросом (см. докстринг llm-service/server.py).
            payload["api_key"] = current_app.config.get("VSEGPT_API_KEY", "")

        # В тестах (TESTING=True) llm-service обычно не запущен вовсе —
        # это ОЖИДАЕМЫЙ, мгновенный ConnectionError, а не тот случай
        # "сервис перегружен/грузит модель", для которого задержка между
        # попытками вообще имеет смысл. Без этой оговорки ретраи с реальным
        # sleep(2с) на каждый непойманный вызов LLMClient в десятках тестов
        # раздули бы весь прогон с ~1 минуты до нескольких (что и
        # обнаружилось на практике).
        retry_delay = 0.0 if current_app.config.get("TESTING") else _RETRY_DELAY_SECONDS

        last_exc: requests.exceptions.RequestException | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                # Только сам сетевой запрос — НЕ retry_delay ниже: пока этот
                # поток спит перед повтором, слот должен освободиться для
                # чужого запроса, а не простаивать занятым впустую (см.
                # docstring _LlmConcurrencyGate).
                with _concurrency_gate.slot():
                    resp = requests.post(
                        f"{self.base_url}/generate",
                        json=payload,
                        timeout=request_timeout,
                    )
            except requests.exceptions.Timeout as exc:
                # Повтор таймаута Ollama обычно только ставит ещё один такой же
                # тяжёлый запрос в очередь и превращает минуты в часы.
                raise LLMClientError(
                    f"{selection.provider} не ответил за {request_timeout} с — "
                    "проверьте, что модель помещается в память и раннер не занят"
                ) from exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "llm-service недоступен (попытка %s/%s): %s — повтор через %sс",
                        attempt,
                        _MAX_ATTEMPTS,
                        exc,
                        retry_delay,
                    )
                    if retry_delay:
                        time.sleep(retry_delay)
                    continue
                raise LLMClientError(f"llm-service недоступен: {exc}") from last_exc

            # 5xx от самого llm-service (не разрыв соединения, а ответ с
            # ошибкой) — обычно значит, что раннер (Ollama/LM Studio) не
            # успел ответить вовремя, пока грузил модель в память, или был
            # занят другим запросом. Это ровно тот же временный сбой, что и
            # ConnectionError выше — раньше не ретраился и сразу ронял
            # позицию в "не найдено", хотя со второй попытки чаще всего
            # проходит нормально.
            if resp.status_code >= 500:
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "llm-service вернул %s (попытка %s/%s): %s — повтор через %sс",
                        resp.status_code,
                        attempt,
                        _MAX_ATTEMPTS,
                        _llm_service_error_detail(resp),
                        retry_delay,
                    )
                    if retry_delay:
                        time.sleep(retry_delay)
                    continue
                raise LLMClientError(f"llm-service -> {resp.status_code}: {_llm_service_error_detail(resp)}")
            break

        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {_llm_service_error_detail(resp)}")
        return resp.json()["text"]

    def generate_card_content(self, product: dict, market: dict | list) -> dict:
        """SEO-текст, буллеты и характеристики карточки на основе конкурентов."""
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt(
            "card_generation.md",
            product=product,
            market=market,
        )
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def suggest_price(self, product: dict, snapshot: dict) -> dict:
        """Предложение по цене с обоснованием. Не применяется автоматически.

        product должен содержать 'cost_price' — промпт явно требует не
        предлагать цену ниже себестоимости (см. prompts/price_suggestion.md).
        """
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt("price_suggestion.md", product=product, market=snapshot)
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def summarize_review(self, stats: dict) -> dict:
        """Короткая сводка "на что смотреть в первую очередь" для человека,
        проверяющего результаты автосопоставления заказ-наряда (см.
        repair_order_processor.py: _generate_review_summary). Возвращает
        {"summary": str}."""
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt("review_summary.md", **stats)
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def match_labor_by_name(
        self,
        description: str,
        candidates: list[dict],
        vehicle_make: str | None = None,
        vehicle_model: str | None = None,
    ) -> dict:
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt(
            "labor_matching.md",
            description=description,
            candidates=candidates,
            vehicle_make=vehicle_make,
            vehicle_model=vehicle_model,
        )
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def suggest_additional_labor_operations(
        self, existing_operations: list[str], vehicle_make: str | None, vehicle_model: str | None, candidates: list[dict]
    ) -> dict:
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt(
            "labor_suggestions.md",
            existing_operations=existing_operations,
            vehicle_make=vehicle_make,
            vehicle_model=vehicle_model,
            candidates=candidates,
        )
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def extract_table_from_text(self, raw_text: str, fields: list[str]) -> list[dict]:
        """Извлекает табличные строки из текста произвольной длины и
        "ширины" (числа запрошенных полей на строку — от 3 у ставок
        нормо-часов до 11 у номенклатуры, см. вызывающий код). Раньше
        текст жёстко обрезался до 12000 символов ПЕРЕД отправкой — все
        строки за этой границей просто никогда не попадали в запрос,
        независимо от того, обрывался ли реально ответ модели. Теперь текст
        режется на куски (см. _split_into_chunks) и разбирается несколькими
        запросами — короткий файл, как и раньше, укладывается в один кусок
        и в один запрос, поведение для типичного случая не меняется.

        Чем шире таблица (больше fields), тем компактнее кусок — на то же
        число строк уходит больше символов JSON в ответе, значит риск
        упереться в лимит токенов раннера выше. Если ответ на конкретный
        кусок всё равно обрезался — восстанавливаем из него целые строки
        (см. _recover_truncated_rows) вместо одной ошибки на весь файл.
        Если какой-то ОДИН кусок совсем не разобрался — пропускаем именно
        его и продолжаем с остальными: частичный результат лучше отказа
        прочитать файл целиком.

        Куски не зависят друг от друга, поэтому разбираются ПАРАЛЛЕЛЬНО
        через map_with_app_context (см. services/parallel.py) — тот же
        приём, что уже используется для сопоставления запчастей/работ.
        Раньше это был обычный последовательный цикл: каждый кусок ждал
        до 3 попыток по 200с таймаута ДРУГ ЗА ДРУГОМ (см. _generate), и на
        файле с полутора-двумя десятками кусков (широкая таблица, живой
        скан) весь разбор мог растянуться на часы, хотя реальное время
        ответа раннера на один кусок — секунды. Параллельно эти же куски
        укладываются в разы быстрее — до 4 сразу (MAX_WORKERS в parallel.py).

        Перед реальным запросом каждый кусок сверяется с кешем по хешу
        своего содержимого + полей + провайдера/модели (см.
        services/llm_extraction_cache.py) — повторная загрузка того же
        файла (или того же куска текста в другом файле) не оплачивается
        и не пересчитывается заново. Кешируется только ЧИСТО распарсенный
        результат — обрезанный/восстановленный ответ намеренно НЕ
        попадает в кеш, иначе неполный результат застрял бы там навсегда."""
        from app.services import llm_extraction_cache, llm_settings
        from app.services.parallel import llm_workers, map_with_app_context
        from app.services.prompt_loader import render_prompt

        # Дробим только для ограничения размера ответа, а не на маленькие
        # фиксированные блоки.  llm-service задаёт max_tokens=8000 для vsegpt,
        # поэтому более крупные входные куски заметно уменьшают число
        # сетевых запросов и оплату за повторные prompt-токены.  Для широких
        # таблиц оставляем запас, чтобы JSON-ответ не упирался в лимит.
        chunk_chars = 7000 if len(fields) <= 5 else 3200
        chunks = _split_into_chunks(raw_text, chunk_chars)
        total = len(chunks)
        # Без выбранной модели закешировать нечего осмысленно (ключ должен
        # зависеть от того, ЧЕМ был получен результат) — _generate() внутри
        # цикла всё равно поднимет свою обычную понятную ошибку "модель не
        # выбрана" на первом же кэш-промахе, отдельно проверять не нужно.
        selection = llm_settings.get_selection()

        def _process_chunk(item: tuple[int, str]) -> tuple[list[dict], str | None, tuple[str, list[dict]] | None]:
            idx, chunk = item

            cache_key = None
            if selection is not None:
                cache_key = llm_extraction_cache.build_key(
                    selection.provider, selection.model_name, fields, chunk
                )
                cached_rows = llm_extraction_cache.get(cache_key)
                if cached_rows is not None:
                    logger.info(
                        "Кусок %s/%s взят из кеша LLM-извлечения — модель не вызывалась повторно",
                        idx,
                        total,
                    )
                    return cached_rows, None, None

            prompt = render_prompt("ocr_table_extraction.md", raw_text=chunk, fields=fields)
            text = self._generate(prompt, json_response=True)
            try:
                parsed = json.loads(text)
                rows = parsed.get("rows") or []
                cache_entry = (cache_key, rows) if cache_key is not None else None
                return rows, None, cache_entry
            except json.JSONDecodeError:
                pass

            # Раннер оборвал ответ по лимиту токенов посреди JSON (обычно —
            # длинный/широкий кусок) — восстанавливаем всё, что успело
            # попасть в ответ до обрыва, вместо того чтобы терять его целиком.
            recovered = _recover_truncated_rows(text)
            if recovered:
                logger.warning(
                    "Ответ llm-service на ocr_table_extraction обрезан (кусок %s/%s) — восстановлено %s строк(и) из повреждённого JSON",
                    idx,
                    total,
                    len(recovered),
                )
                return recovered, None, None

            logger.warning(
                "Не удалось разобрать кусок текста %s/%s при извлечении таблицы — пропускаем, продолжаем с остальными",
                idx,
                total,
            )
            return [], text, None

        results = map_with_app_context(
            _process_chunk,
            list(enumerate(chunks, start=1)),
            max_workers=llm_workers(),
        )

        all_rows: list[dict] = []
        failed_chunks = 0
        last_failed_text = ""
        cache_entries: list[tuple[str, list[dict]]] = []
        for rows, failed_text, cache_entry in results:
            all_rows.extend(rows)
            if cache_entry is not None:
                cache_entries.append(cache_entry)
            if failed_text is not None:
                failed_chunks += 1
                last_failed_text = failed_text

        if not all_rows and failed_chunks:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {last_failed_text!r}")
        llm_extraction_cache.set_many(cache_entries)
        return [{field: row.get(field) for field in fields} for row in all_rows]

    def match_part_by_name(self, contract_line: dict, candidates: list[dict]) -> dict:
        """Fallback-сопоставление позиции по названию, когда нет совпадения
        по артикулу ни напрямую, ни через кросс-номера поставщика.

        Возвращает {"matched_index": int | None, "confidence": float, "reasoning": str}.
        matched_index — индекс в списке candidates, либо None, если модель
        не уверена ни в одном варианте.
        """
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt(
            "parts_matching.md",
            contract_line=contract_line,
            candidates=candidates,
        )
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def normalize_brand_labels(self, labels: list[str]) -> dict[str, str | None]:
        """Марки из каталога заказчика, которых нет в справочнике BrandAlias
        (см. app/models/brand_alias.py) — просим ИИ привести к каноничному
        латинскому написанию, как в заказ-наряде. Один пакетный запрос на
        все нераспознанные метки сразу, а не по одной — они всё равно
        сравниваются вместе (см. contract_catalog_import.py).

        Возвращает {метка_как_на_входе: каноничная_марка | None}. Ключ
        "mapping" в ответе модели — словарь; отсутствие метки в ответе
        (модель забыла её обработать) трактуем так же, как None."""
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt("brand_normalization.md", labels=labels)
        text = self._generate(prompt, json_response=True)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc
        mapping = parsed.get("mapping") or {}
        return {label: mapping.get(label) or None for label in labels}
