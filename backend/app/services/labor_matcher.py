from __future__ import annotations

import logging

from app.models import ConfidenceLevel, ContractLaborNorm
from app.services.autodata_client import AutoDataClient, AutoDataError
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


def match_labor_line(
    description: str,
    vehicle_make: str | None,
    vehicle_model: str | None,
    autodata_client: AutoDataClient,
    llm_client: LLMClient,
) -> dict:
    normalized = (description or "").strip().lower()

    try:
        candidates = autodata_client.find_norm_hours(vehicle_make or "", vehicle_model)
    except AutoDataError as exc:
        candidates = []
        logger.warning("AutoData недоступен для %r: %s", description, exc)

    for candidate in candidates:
        if candidate["operation_name"].strip().lower() == normalized:
            return {
                "description": description,
                "matched_operation_name": candidate["operation_name"],
                "norm_hours": candidate["norm_hours"],
                "confidence_level": ConfidenceLevel.EXACT,
                "confidence_score": 1.0,
                "raw_match_data": {"source": "autodata_exact"},
            }

    llm_error = None
    if candidates:
        try:
            llm_result = llm_client.match_labor_by_name(description, candidates)
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление работы недоступно для %r: %s", description, exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(candidates):
                candidate = candidates[idx]
                return {
                    "description": description,
                    "matched_operation_name": candidate["operation_name"],
                    "norm_hours": candidate["norm_hours"],
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    "confidence_score": llm_result.get("confidence", 0.0),
                    "raw_match_data": {"source": "llm_fallback", "reasoning": llm_result.get("reasoning")},
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
    return [
        match_labor_line(desc, vehicle_make, vehicle_model, autodata_client, llm_client)
        for desc in descriptions
    ]


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


def _contract_labor_candidates(contract_id: int, vehicle_make: str | None, vehicle_model: str | None) -> list[dict]:
    query = ContractLaborNorm.query.filter_by(contract_id=contract_id)
    if vehicle_make:
        query = query.filter(
            ContractLaborNorm.vehicle_make.is_(None) | (ContractLaborNorm.vehicle_make == vehicle_make)
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
    normalized = (description or "").strip().lower()
    candidates = _contract_labor_candidates(contract_id, vehicle_make, vehicle_model)

    exact_matches = [c for c in candidates if c["operation_name"].strip().lower() == normalized]
    distinct_hours = {c["norm_hours"] for c in exact_matches}
    if len(distinct_hours) == 1:
        candidate = exact_matches[0]
        return {
            "description": description,
            "matched_operation_name": candidate["operation_name"],
            "norm_hours": candidate["norm_hours"],
            "confidence_level": ConfidenceLevel.EXACT,
            "confidence_score": 1.0,
            "raw_match_data": {"source": "contract_catalog_exact"},
        }

    llm_error = None
    if candidates:
        try:
            llm_result = llm_client.match_labor_by_name(description, candidates)
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление работы недоступно для %r: %s", description, exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(candidates):
                candidate = candidates[idx]
                return {
                    "description": description,
                    "matched_operation_name": candidate["operation_name"],
                    "norm_hours": candidate["norm_hours"],
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    "confidence_score": llm_result.get("confidence", 0.0),
                    "raw_match_data": {"source": "llm_fallback_contract_catalog", "reasoning": llm_result.get("reasoning")},
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
    return [
        match_labor_line_against_contract(desc, contract_id, vehicle_make, vehicle_model, llm_client)
        for desc in descriptions
    ]


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
