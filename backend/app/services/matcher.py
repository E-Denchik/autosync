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

from app.models import ConfidenceLevel
from app.services.llm_client import LLMClient
from app.services.parts_supplier_client import PartsSupplierClient


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

    # 3. Fallback: LLM сопоставляет по названию среди позиций заказ-наряда
    if order_lines:
        llm_result = llm_client.match_part_by_name(contract_line, order_lines)
        idx = llm_result.get("matched_index")
        if idx is not None and 0 <= idx < len(order_lines):
            candidate = order_lines[idx]
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

    # Ничего не найдено — всё равно возвращаем запись для ручной проверки
    return {
        "contract_article": article,
        "contract_name": contract_line.get("name"),
        "matched_article": None,
        "matched_name": None,
        "matched_price": None,
        "confidence_level": ConfidenceLevel.LLM_GUESS,
        "confidence_score": 0.0,
        "raw_match_data": {"source": "no_match_found"},
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
