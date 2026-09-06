"""Свёртка подробной уверенности сопоставления (exact/cross_ref/llm_guess +
множество категорий-нюансов, см. matching.py::_match_category и
labor.py::_labor_category) до одного бинарного статуса для оператора:
"проверено" или "догадка". Общая для запчастей и работ — раньше эта
классификация дублировалась бы отдельно в двух блюпринтах.

Чистые примитивы, без ORM/Flask — вызывающий код сам достаёт нужные поля из
своих моделей (PartMatch/LaborLine)."""

from __future__ import annotations

# Эти категории уже отдельно помечены во фронте как требующие особого
# внимания (перенос нормы с другой марки, работа, которой не было в
# исходном заказ-наряде, норма без подтверждения каталогом) — не считаем их
# "проверено" по одному лишь порогу уверенности, даже если он пройден.
_ALWAYS_GUESS_CATEGORIES = ("cross_make_estimate", "suggested_addition", "from_repair_order")
_ALWAYS_VERIFIED_CATEGORIES = ("exact", "cross_ref")


def is_verified(
    *,
    match_category: str,
    confidence_score: float | None,
    review_status: str,
    manually_edited: bool,
    threshold: float,
    has_value: bool,
) -> bool:
    """has_value обязателен для и manually_edited, и approved: edit_labor_line
    можно вызвать с одним matched_operation_name, оставив norm_hours пустым
    (manually_edited=True, но норма всё ещё не заполнена), а approve_match/
    approve_match не проверяет, что matched_name реально заполнен — без
    этой проверки пустая строка выглядела бы "проверено" только потому, что
    кто-то её отредактировал или нажал "Принять"."""
    if match_category in _ALWAYS_VERIFIED_CATEGORIES:
        return True
    if not has_value:
        return False
    if manually_edited:
        return True
    if review_status == "approved":
        return True
    if match_category in _ALWAYS_GUESS_CATEGORIES:
        return False
    return confidence_score is not None and confidence_score >= threshold
