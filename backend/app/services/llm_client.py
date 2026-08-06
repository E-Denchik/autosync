"""Единая точка вызова LLM-сервиса (llm-service/server.py, Qwen2.5).

Backend никогда не обращается к Ollama/vLLM напрямую — только через этот
HTTP-клиент, чтобы модель/хост можно было заменить, не трогая backend
(см. ARCHITECTURE.md: «Ключевые решения»).
"""

from __future__ import annotations

import json

import requests


class LLMClientError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _generate(self, prompt: str, *, json_response: bool = False) -> str:
        resp = requests.post(
            f"{self.base_url}/generate",
            json={"prompt": prompt, "json_response": json_response},
            timeout=self.timeout,
        )
        if not resp.ok:
            raise LLMClientError(f"llm-service -> {resp.status_code}: {resp.text}")
        return resp.json()["text"]

    def generate_card_content(self, product: dict, competitor_cards: list[dict]) -> dict:
        """SEO-текст, буллеты и характеристики карточки на основе конкурентов."""
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt(
            "card_generation.md",
            product=product,
            competitor_cards=competitor_cards,
        )
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

    def suggest_price(self, product: dict, snapshot: dict) -> dict:
        """Предложение по цене с обоснованием. Не применяется автоматически."""
        from app.services.prompt_loader import render_prompt

        prompt = render_prompt("card_generation.md", product=product, competitor_cards=[snapshot])
        text = self._generate(prompt, json_response=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMClientError(f"llm-service вернул невалидный JSON: {text!r}") from exc

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
