"""Кеш результатов LLM-извлечения таблицы из куска текста (см.
llm_client.py: extract_table_from_text) — см. подробный докстринг модели
app/models/llm_extraction_cache.py про то, зачем и как выбран ключ."""

from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.llm_extraction_cache import LlmExtractionCache


def build_key(provider: str, model: str, fields: list[str], chunk_text: str) -> str:
    # \x1f (разделитель полей ASCII) — чтобы конкатенация не давала
    # ложных совпадений на границах частей (например, fields=["a"],
    # chunk="bc" не перепутается с fields=["ab"], chunk="c").
    canonical = "\x1f".join([provider, model, ",".join(sorted(fields)), chunk_text])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get(cache_key: str) -> list[dict] | None:
    entry = LlmExtractionCache.query.filter_by(cache_key=cache_key).first()
    return entry.rows if entry is not None else None


def set(cache_key: str, rows: list[dict]) -> None:
    """Сохраняет результат. Если запись с этим ключом уже появилась между
    get() и этим вызовом (гонка — см. parallel.py: до 4 кусков сразу,
    у двух в редком случае может совпасть содержимое) — тихо ничего не
    делает: значение по факту уже есть, вторая попытка не должна ронять
    всю обработку заказ-наряда/каталога."""
    db.session.add(LlmExtractionCache(cache_key=cache_key, rows=rows))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
