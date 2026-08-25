"""Единая точка вызова LLM-сервиса (llm-service/server.py, Qwen2.5).

Backend никогда не обращается к Ollama/vLLM напрямую — только через этот
HTTP-клиент, чтобы модель/хост можно было заменить, не трогая backend
(см. ARCHITECTURE.md: «Ключевые решения»).
"""

from __future__ import annotations

import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

# Локальный llm-service (Ollama и т.п.) нередко на первом запросе после
# простоя грузит модель в память по несколько секунд, плюс сеть между
# процессами на одной машине изредка отдаёт мгновенный ConnectionRefused,
# если процесс ещё не успел забиндить порт (гонка при старте приложения) —
# оба случая проходят сами со второй попытки. Раньше ЛЮБОЙ сбой сети
# (даже такой сиюминутный) сразу и безвозвратно ронял конкретную
# позицию/работу в "не найдено" на весь заказ-наряд.
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    # Должен быть БОЛЬШЕ таймаута, с которым llm-service сам ждёт ответа от
    # Ollama/LM Studio (см. llm-service/server.py: requests.post(..., timeout=180))
    # — раньше здесь стояло 120, то есть backend сдавался и рвал соединение
    # РАНЬШЕ, чем llm-service успевал сам получить (или не получить) ответ
    # от раннера. На медленной машине/холодной загрузке крупной модели это
    # выглядело как случайное "llm-service недоступен", хотя раннер просто
    # ещё считал — 200с даёт llm-service возможность честно дождаться своих
    # 180с и вернуть внятную ошибку вместо обрыва с нашей стороны.
    def __init__(self, base_url: str, timeout: int = 200):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_models(self) -> dict:
        """Discovery всех LLM-раннеров, которые видит llm-service (Ollama,
        LM Studio) — что реально скачано на этой машине прямо сейчас."""
        try:
            resp = requests.get(f"{self.base_url}/models", timeout=5)
        except requests.exceptions.RequestException as exc:
            raise LLMClientError(f"llm-service недоступен: {exc}") from exc
        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {resp.text}")
        return resp.json()

    def _generate(self, prompt: str, *, json_response: bool = False) -> str:
        from flask import current_app

        from app.services.llm_settings import get_selection

        payload = {"prompt": prompt, "json_response": json_response}
        selection = get_selection()
        if selection is not None:
            payload["provider"] = selection.provider
            payload["model"] = selection.model_name

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
                resp = requests.post(
                    f"{self.base_url}/generate",
                    json=payload,
                    timeout=self.timeout,
                )
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
                        resp.text,
                        retry_delay,
                    )
                    if retry_delay:
                        time.sleep(retry_delay)
                    continue
                raise LLMClientError(f"llm-service -> {resp.status_code}: {resp.text}")
            break

        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {resp.text}")
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
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt("ocr_table_extraction.md", raw_text=raw_text[:12000], fields=fields)
        text = self._generate(prompt, json_response=True)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc
        rows = parsed.get("rows") or []
        return [{field: row.get(field) for field in fields} for row in rows]

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
