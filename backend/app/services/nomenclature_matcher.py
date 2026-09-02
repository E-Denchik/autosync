"""Обогащение уже найденного PartMatch данными из внутренней номенклатуры
заказчика (код, № кат., производитель, остаток/резерв/склад) — см.
nomenclature_client.py. Отдельный шаг ПОСЛЕ matcher.py: matcher.py решает,
с какой позицией сопоставить запчасть, а этот модуль только подтягивает
складские метаданные для уже сопоставленной позиции, не влияя на
confidence_level самого сопоставления.
"""

from __future__ import annotations

import logging

from app.services.nomenclature_client import NomenclatureClient, NomenclatureClientError

logger = logging.getLogger(__name__)

_ENRICHMENT_FIELDS = (
    "code",
    "cat_number",
    "manufacturer",
    "unit",
    "stock_qty",
    "reserved_qty",
    "in_production_qty",
    "ordered_qty",
    "warehouse",
)


def enrich_part_match(match: dict, nomenclature_client: NomenclatureClient) -> dict:
    """Возвращает копию match с добавленными полями nomenclature_* — либо
    без изменений (все nomenclature_* = None), если искать не по чему или
    ничего не нашлось. Никогда не поднимает исключение выше — как и в
    matcher.py, недоступность внешнего источника не должна ронять
    обработку заказ-наряда (см. repair_order_processor.py)."""
    enriched = dict(match)
    for field in _ENRICHMENT_FIELDS:
        enriched[f"nomenclature_{field}"] = None
    enriched["nomenclature_source"] = None

    code = match.get("matched_article") or match.get("contract_article")
    name = match.get("matched_name") or match.get("contract_name")
    if not code and not name:
        return enriched

    try:
        found = nomenclature_client.find_match(code, name)
    except NomenclatureClientError as exc:
        logger.warning("Поиск по номенклатуре недоступен для %r: %s", name, exc)
        return enriched

    if not found:
        return enriched

    for field in _ENRICHMENT_FIELDS:
        enriched[f"nomenclature_{field}"] = found.get(field)
    enriched["nomenclature_source"] = found.get("match_source")
    return enriched


def enrich_all(matches: list[dict], nomenclature_client: NomenclatureClient) -> list[dict]:
    """Каждая позиция обогащается независимо от остальных — как и
    сопоставление в matcher.py/labor_matcher.py, идёт параллельно (см.
    services/parallel.py), а не строго по одной. Особенно заметно при
    настроенном ALFAAUTO_BASE_URL: это реальный сетевой запрос к OData
    на каждую позицию (см. NomenclatureClient._find_remote), сотни
    позиций подряд иначе ощутимо копятся во времени."""
    from app.services.parallel import map_with_app_context

    return map_with_app_context(lambda m: enrich_part_match(m, nomenclature_client), matches)
