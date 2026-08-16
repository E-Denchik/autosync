"""Логика сопоставления позиций договора с позициями поставщика/заказ-наряда.

Вся логика сопоставления живёт здесь (см. PROJECT.md, «Для новых
разработчиков»). LLM вызывается только как fallback, когда нет прямого
совпадения по артикулу — ни точного, ни через кросс-номера API поставщика.

Порядок:
    1. Точное совпадение артикула (ConfidenceLevel.EXACT)
    2. Кросс-номера через parts_supplier_client (ConfidenceLevel.CROSS_REF)
    3. LLM по названию (ConfidenceLevel.LLM_GUESS) — самый ненадёжный статус
"""

from __future__ import annotations

import difflib
import logging

from app.models import ConfidenceLevel
from app.services.llm_client import LLMClient
from app.services.parts_supplier_client import PartsSupplierClient

logger = logging.getLogger(__name__)

LLM_CANDIDATE_LIMIT = 20


def _shortlist_candidates(name: str | None, order_lines: list[dict]) -> list[dict]:
    if not name or len(order_lines) <= LLM_CANDIDATE_LIMIT:
        return order_lines
    normalized = name.strip().lower()
    scored = [
        (difflib.SequenceMatcher(None, normalized, (line.get("name") or "").strip().lower()).ratio(), line)
        for line in order_lines
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [line for _, line in scored[:LLM_CANDIDATE_LIMIT]]


def match_line(
    contract_line: dict,
    order_lines: list[dict],
    supplier_client: PartsSupplierClient,
    llm_client: LLMClient,
) -> dict:
    """Сопоставляет одну позицию договора с позициями заказ-наряда/поставщика.

    Возвращает dict, совместимый с полями модели PartMatch (без repair_order_id).
    """
    article = contract_line.get("article")

    # 1. Точное совпадение артикула внутри самого заказ-наряда
    if article:
        exact = next(
            (line for line in order_lines if line.get("article") and line["article"] == article),
            None,
        )
        if exact:
            return {
                "contract_article": article,
                "contract_name": contract_line.get("name"),
                "matched_article": exact.get("article"),
                "matched_name": exact.get("name"),
                "matched_price": exact.get("price"),
                "confidence_level": ConfidenceLevel.EXACT,
                "confidence_score": 1.0,
                "raw_match_data": {"source": "exact_article_match"},
            }

    # 2. Кросс-номера через API поставщика
    if article:
        try:
            cross_refs = supplier_client.find_cross_references(article)
        except Exception:
            cross_refs = []
        if cross_refs:
            best = cross_refs[0]
            return {
                "contract_article": article,
                "contract_name": contract_line.get("name"),
                "matched_article": best.get("article"),
                "matched_name": best.get("name"),
                "matched_price": best.get("price"),
                "confidence_level": ConfidenceLevel.CROSS_REF,
                "confidence_score": 0.9,
                "raw_match_data": {"source": "parts_supplier_cross_reference", "candidates": cross_refs},
            }

    # 3. Fallback: LLM сопоставляет по названию среди позиций заказ-наряда.
    # Если LLM недоступна/вернула ошибку — это НЕ должно ронять всю обработку
    # заказ-наряда (иначе он зависает в статусе "matching" навсегда без
    # единого сообщения об ошибке, см. историю багов). Просто считаем
    # позицию несопоставленной и отправляем на ручную проверку.
    llm_error = None
    if order_lines:
        shortlist = _shortlist_candidates(contract_line.get("name"), order_lines)
        try:
            llm_result = llm_client.match_part_by_name(contract_line, shortlist)
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление недоступно для %r: %s", contract_line.get("name"), exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(shortlist):
                candidate = shortlist[idx]
                return {
                    "contract_article": article,
                    "contract_name": contract_line.get("name"),
                    "matched_article": candidate.get("article"),
                    "matched_name": candidate.get("name"),
                    "matched_price": candidate.get("price"),
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    "confidence_score": llm_result.get("confidence", 0.0),
                    "raw_match_data": {"source": "llm_fallback", "reasoning": llm_result.get("reasoning")},
                }

    # Ничего не найдено (или LLM недоступна) — всё равно возвращаем запись
    # для ручной проверки, вместо того чтобы прервать обработку остальных позиций.
    return {
        "contract_article": article,
        "contract_name": contract_line.get("name"),
        "matched_article": None,
        "matched_name": None,
        "matched_price": None,
        "confidence_level": ConfidenceLevel.LLM_GUESS,
        "confidence_score": 0.0,
        "raw_match_data": {"source": "llm_error", "error": llm_error} if llm_error else {"source": "no_match_found"},
    }


def match_all(
    contract_lines: list[dict],
    order_lines: list[dict],
    supplier_client: PartsSupplierClient,
    llm_client: LLMClient,
) -> list[dict]:
    return [
        match_line(line, order_lines, supplier_client, llm_client)
        for line in contract_lines
    ]
