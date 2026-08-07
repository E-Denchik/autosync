from __future__ import annotations

import logging

from app.models import ConfidenceLevel
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
