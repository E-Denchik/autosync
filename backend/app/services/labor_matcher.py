from __future__ import annotations

import logging
import re

from app.extensions import db
from app.models import ConfidenceLevel, ContractLaborNorm
from app.services.autodata_client import AutoDataClient, AutoDataError
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _normalize_operation_text(value: str | None) -> str:
    """Нормализует только форму записи, не приравнивая разные операции."""
    tokens = re.findall(r"[0-9a-zа-яё]+", (value or "").casefold().replace("ё", "е"))
    return " ".join(sorted(tokens))


def _find_exact_operation(candidates: list[dict], description: str) -> dict | None:
    normalized = _normalize_operation_text(description)
    if not normalized:
        return None
    matches = [c for c in candidates if _normalize_operation_text(c.get("operation_name")) == normalized]
    distinct_hours = {c["norm_hours"] for c in matches}
    return matches[0] if len(matches) == 1 or len(distinct_hours) == 1 and matches else None


def _bounded_confidence(value: object, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def match_labor_line(
    description: str,
    vehicle_make: str | None,
    vehicle_model: str | None,
    autodata_client: AutoDataClient,
    llm_client: LLMClient,
) -> dict:
    try:
        candidates = autodata_client.find_norm_hours(vehicle_make or "", vehicle_model)
    except AutoDataError as exc:
        candidates = []
        logger.warning("AutoData недоступен для %r: %s", description, exc)

    candidate = _find_exact_operation(candidates, description)
    if candidate:
        return {
            "description": description,
            "matched_operation_name": candidate["operation_name"],
            "norm_hours": candidate["norm_hours"],
            "confidence_level": ConfidenceLevel.EXACT,
            "confidence_score": 1.0,
            "raw_match_data": {"source": "autodata_exact"},
        }

    # Точной марки в справочнике нет вовсе (частый случай для бизнеса без
    # 1С/AutoData, который только начал вести свой список) — раньше это
    # значило, что LLM даже не звали, и работа сразу уходила в "не найдено".
    # Пробуем более широкий пул (другие марки) как материал для LLM —
    # см. prompts/labor_matching.md про то, когда переносить норму уместно.
    cross_make = False
    if not candidates:
        try:
            candidates = autodata_client.find_norm_hours_any_make()
            cross_make = bool(candidates)
        except AutoDataError as exc:
            candidates = []
            logger.warning("AutoData (общий пул) недоступен для %r: %s", description, exc)

    llm_error = None
    if candidates:
        try:
            llm_result = llm_client.match_labor_by_name(
                description, candidates, vehicle_make=vehicle_make, vehicle_model=vehicle_model
            )
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление работы недоступно для %r: %s", description, exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(candidates):
                candidate = candidates[idx]
                source = "llm_fallback_cross_make" if cross_make else "llm_fallback"
                return {
                    "description": description,
                    "matched_operation_name": candidate["operation_name"],
                    "norm_hours": candidate["norm_hours"],
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    "confidence_score": min(_bounded_confidence(llm_result.get("confidence")), 0.6)
                    if cross_make
                    else _bounded_confidence(llm_result.get("confidence")),
                    "raw_match_data": {
                        "source": source,
                        "reasoning": llm_result.get("reasoning"),
                        **(
                            {
                                "estimate_from_make": candidate.get("vehicle_make"),
                                "estimate_from_model": candidate.get("vehicle_model"),
                            }
                            if cross_make
                            else {}
                        ),
                    },
                }

    return {
        "description": description,
        "matched_operation_name": None,
        "norm_hours": None,
        "confidence_level": ConfidenceLevel.LLM_GUESS,
        "confidence_score": 0.0,
        "raw_match_data": {"source": "llm_error", "error": llm_error} if llm_error else {"source": "no_match_found"},
    }


def match_all_labor(
    descriptions: list[str],
    vehicle_make: str | None,
    vehicle_model: str | None,
    autodata_client: AutoDataClient,
    llm_client: LLMClient,
) -> list[dict]:
    from app.services.parallel import map_with_app_context

    return map_with_app_context(
        lambda desc: match_labor_line(desc, vehicle_make, vehicle_model, autodata_client, llm_client),
        descriptions,
        max_workers=1,
    )


LABOR_SUGGESTION_CANDIDATE_LIMIT = 60


def suggest_missing_labor_operations(
    matched_results: list[dict],
    vehicle_make: str | None,
    vehicle_model: str | None,
    autodata_client: AutoDataClient,
    llm_client: LLMClient,
) -> list[dict]:
    if not matched_results:
        return []

    try:
        candidates = autodata_client.find_norm_hours(vehicle_make or "", vehicle_model)
    except AutoDataError as exc:
        logger.warning("AutoData недоступен для подбора недостающих работ: %s", exc)
        return []

    existing_operations = [
        r.get("matched_operation_name") or r.get("description") for r in matched_results
    ]
    already_covered = {name.strip().lower() for name in existing_operations if name}
    remaining = [c for c in candidates if c["operation_name"].strip().lower() not in already_covered]
    if not remaining or len(remaining) > LABOR_SUGGESTION_CANDIDATE_LIMIT:
        return []

    try:
        llm_result = llm_client.suggest_additional_labor_operations(
            existing_operations, vehicle_make, vehicle_model, remaining
        )
    except Exception as exc:
        logger.warning("LLM-подбор недостающих работ недоступен: %s", exc)
        return []

    suggestions = []
    for item in llm_result.get("suggestions") or []:
        idx = item.get("index")
        if idx is None or not (0 <= idx < len(remaining)):
            continue
        candidate = remaining[idx]
        suggestions.append(
            {
                "description": candidate["operation_name"],
                "matched_operation_name": candidate["operation_name"],
                "norm_hours": candidate["norm_hours"],
                "confidence_level": ConfidenceLevel.LLM_GUESS,
                "confidence_score": item.get("confidence", 0.0),
                "raw_match_data": {
                    "source": "llm_suggested_addition",
                    "reasoning": item.get("reasoning"),
                },
            }
        )
    return suggestions


def _contract_labor_candidates_any_make(contract_id: int, limit: int = 200) -> list[dict]:
    """Как _contract_labor_candidates, но без фильтра по марке — запасной
    пул для LLM, когда по точной марке в каталоге ЭТОГО контракта нет ни
    одной операции (см. match_labor_line_against_contract)."""
    rows = ContractLaborNorm.query.filter_by(contract_id=contract_id).limit(limit).all()
    return [
        {
            "operation_name": r.operation_name,
            "norm_hours": float(r.norm_hours),
            "vehicle_make": r.vehicle_make,
            "vehicle_model": r.vehicle_model,
        }
        for r in rows
    ]


def _contract_labor_candidates(contract_id: int, vehicle_make: str | None, vehicle_model: str | None) -> list[dict]:
    query = ContractLaborNorm.query.filter_by(contract_id=contract_id)
    if vehicle_make:
        # Регистронезависимо — см. тот же комментарий в repair_order_processor.py
        # (ставка по марке) и AutoDataClient._find_local (уже так делает).
        query = query.filter(
            ContractLaborNorm.vehicle_make.is_(None)
            | (db.func.lower(ContractLaborNorm.vehicle_make) == vehicle_make.lower())
        )
    rows = query.all()
    if vehicle_model:
        rows = [r for r in rows if not r.vehicle_model or r.vehicle_model.lower() == vehicle_model.lower()]
    return [
        {
            "operation_name": r.operation_name,
            "norm_hours": float(r.norm_hours),
            "vehicle_make": r.vehicle_make,
            "vehicle_model": r.vehicle_model,
        }
        for r in rows
    ]


def match_labor_line_against_contract(
    description: str,
    contract_id: int,
    vehicle_make: str | None,
    vehicle_model: str | None,
    llm_client: LLMClient,
) -> dict:
    candidates = _contract_labor_candidates(contract_id, vehicle_make, vehicle_model)

    candidate = _find_exact_operation(candidates, description)
    if candidate:
        return {
            "description": description,
            "matched_operation_name": candidate["operation_name"],
            "norm_hours": candidate["norm_hours"],
            "confidence_level": ConfidenceLevel.EXACT,
            "confidence_score": 1.0,
            "raw_match_data": {"source": "contract_catalog_exact"},
        }

    # Точной марки в каталоге ЭТОГО контракта нет вовсе — тот же запасной
    # ход, что и в match_labor_line (см. её комментарий).
    cross_make = False
    if not candidates:
        candidates = _contract_labor_candidates_any_make(contract_id)
        cross_make = bool(candidates)

    llm_error = None
    if candidates:
        try:
            llm_result = llm_client.match_labor_by_name(
                description, candidates, vehicle_make=vehicle_make, vehicle_model=vehicle_model
            )
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление работы недоступно для %r: %s", description, exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(candidates):
                candidate = candidates[idx]
                source = "llm_fallback_cross_make_contract_catalog" if cross_make else "llm_fallback_contract_catalog"
                return {
                    "description": description,
                    "matched_operation_name": candidate["operation_name"],
                    "norm_hours": candidate["norm_hours"],
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    # Перенос нормы между марками — только подсказка, даже
                    # если модель необоснованно вернула высокий confidence.
                    "confidence_score": min(float(llm_result.get("confidence", 0.0)), 0.6)
                    if cross_make
                    else float(llm_result.get("confidence", 0.0)),
                    "raw_match_data": {
                        "source": source,
                        "reasoning": llm_result.get("reasoning"),
                        **(
                            {
                                "estimate_from_make": candidate.get("vehicle_make"),
                                "estimate_from_model": candidate.get("vehicle_model"),
                            }
                            if cross_make
                            else {}
                        ),
                    },
                }

    return {
        "description": description,
        "matched_operation_name": None,
        "norm_hours": None,
        "confidence_level": ConfidenceLevel.LLM_GUESS,
        "confidence_score": 0.0,
        "raw_match_data": {"source": "llm_error", "error": llm_error} if llm_error else {"source": "no_match_found"},
    }


def match_all_labor_against_contract(
    descriptions: list[str],
    contract_id: int,
    vehicle_make: str | None,
    vehicle_model: str | None,
    llm_client: LLMClient,
) -> list[dict]:
    from app.services.parallel import map_with_app_context

    return map_with_app_context(
        lambda desc: match_labor_line_against_contract(desc, contract_id, vehicle_make, vehicle_model, llm_client),
        descriptions,
        max_workers=1,
    )


def suggest_missing_labor_operations_from_contract(
    matched_results: list[dict],
    contract_id: int,
    vehicle_make: str | None,
    vehicle_model: str | None,
    llm_client: LLMClient,
) -> list[dict]:
    if not matched_results:
        return []

    candidates = _contract_labor_candidates(contract_id, vehicle_make, vehicle_model)
    existing_operations = [
        r.get("matched_operation_name") or r.get("description") for r in matched_results
    ]
    already_covered = {name.strip().lower() for name in existing_operations if name}
    remaining = [c for c in candidates if c["operation_name"].strip().lower() not in already_covered]
    if not remaining or len(remaining) > LABOR_SUGGESTION_CANDIDATE_LIMIT:
        return []

    try:
        llm_result = llm_client.suggest_additional_labor_operations(
            existing_operations, vehicle_make, vehicle_model, remaining
        )
    except Exception as exc:
        logger.warning("LLM-подбор недостающих работ (каталог контракта) недоступен: %s", exc)
        return []

    suggestions = []
    for item in llm_result.get("suggestions") or []:
        idx = item.get("index")
        if idx is None or not (0 <= idx < len(remaining)):
            continue
        candidate = remaining[idx]
        suggestions.append(
            {
                "description": candidate["operation_name"],
                "matched_operation_name": candidate["operation_name"],
                "norm_hours": candidate["norm_hours"],
                "confidence_level": ConfidenceLevel.LLM_GUESS,
                "confidence_score": item.get("confidence", 0.0),
                "raw_match_data": {
                    "source": "llm_suggested_addition_contract_catalog",
                    "reasoning": item.get("reasoning"),
                },
            }
        )
    return suggestions
