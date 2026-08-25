"""Нормализация ОДНОЙ конкретной марки (в отличие от пакетной версии в
contract_catalog_import.py::_normalize_unresolved_brands, которая проверяет
сразу все нераспознанные марки каталога одним запросом к ИИ) — нужна там,
где маркой является единственное значение, а не набор строк каталога:
марка САМОГО заказ-наряда (см. repair_order_processor.py).

До этой функции марка заказ-наряда никак не нормализовалась — бралась как
есть из текста файла ("Автомобиль: Шевроле Лачетти") и в таком виде шла
в фильтр по марке при сопоставлении (matcher._contract_candidate_pool) и в
поиск ставки/нормо-часов (repair_order_processor._find_hourly_rate,
labor_matcher.py) — там сравнение со справочником BrandAlias/каталогом
ТОЧНОЕ, так что кириллица или опечатка в заказ-наряде их не находили,
даже если каталог сам по себе уже правильно затегирован."""

from __future__ import annotations


def normalize_brand_with_ai_fallback(label: str | None, llm_client=None) -> str | None:
    """label -> каноничное название марки: сначала справочник BrandAlias
    (см. document_parser._normalize_brand_label), а для того, чего там нет
    — тот же принцип "иишка проверяет и адаптирует", что и при импорте
    каталога: одиночный запрос к ИИ, результат кэшируется в справочник, так
    что при следующей встрече с этой же меткой (у ЭТОГО заказ-наряда или у
    любого другого) ИИ уже не понадобится. Best-effort — недоступность LLM
    просто оставляет марку как определил справочник (или как есть)."""
    if not label or not label.strip():
        return label

    from app.extensions import db
    from app.models import BrandAlias
    from app.services.document_parser import _normalize_brand_label

    canonical = _normalize_brand_label(label)

    # _normalize_brand_label при отсутствии совпадения в справочнике
    # молча возвращает upper(label) — само по себе не отличить "нашли" от
    # "не нашли", поэтому сверяемся явно: канонична ли эта марка хоть для
    # какой-то записи справочника.
    known = {
        row[0] for row in db.session.query(BrandAlias.canonical_make).filter(BrandAlias.canonical_make.isnot(None))
    }
    if canonical in known or llm_client is None:
        return canonical

    try:
        mapping = llm_client.normalize_brand_labels([label])
    except Exception:
        return canonical

    result = mapping.get(label)
    if not result or not result.strip():
        return canonical
    result = result.strip().upper()

    existing = BrandAlias.query.filter(db.func.upper(BrandAlias.alias) == label.upper()).first()
    if existing is None:
        db.session.add(BrandAlias(alias=label, canonical_make=result, source="llm"))
    elif existing.canonical_make is None:
        existing.canonical_make = result
        existing.source = "llm"
    return result
