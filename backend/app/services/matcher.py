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
import re
import threading

from app.extensions import db
from app.models import ConfidenceLevel, ContractPart
from app.services.llm_client import LLMClient
from app.services.parts_supplier_client import PartsSupplierClient

logger = logging.getLogger(__name__)

LLM_CANDIDATE_LIMIT = 20
CONTRACT_CANDIDATE_POOL_LIMIT = 500
_MATCHING_STOPWORDS = {
    "и", "для", "с", "со", "на", "по", "из", "в", "во", "шт", "шт.",
    "комплект", "комплекта", "автомобиля",
}

# Некоторые источники (замечено в выгрузке 1С заказ-наряда) кладут бренд
# прямо в поле артикула вида "PN32661 [AUTOWELT]" — для точного совпадения
# с договором и для запросов к поставщикам (Rossco/АвтоЕвро/Москворечье)
# нужен голый код, иначе искать "PN32661 [AUTOWELT]" как есть — почти
# гарантированно ничего не найти: точное совпадение по артикулу сравнивает
# строки буквально, а часть поставщиков принимает код как строгий параметр
# (не полнотекстовый поиск), где лишние символы обнуляют результат.
_ARTICLE_BRAND_RE = re.compile(r"^(.*\S)\s*\[([^\[\]]+)\]\s*$")


def split_article_brand(raw_article: str | None) -> tuple[str | None, str | None]:
    """Возвращает (голый_артикул, бренд_из_скобок). Если скобок нет —
    (raw_article, None) без изменений."""
    if not raw_article:
        return raw_article, None
    match = _ARTICLE_BRAND_RE.match(raw_article.strip())
    if not match:
        return raw_article, None
    return match.group(1).strip(), match.group(2).strip()


# Артикулы у Kia/Hyundai/Bosch/... — всегда цифры + латинские буквы, без
# смысловых разделителей: "-", " ", ".", "/", "_" в разных источниках
# расставлены непоследовательно (мехник вручную набивает заказ-наряд в
# Excel не так, как отформатирован каталог поставщика) и ничего не значат
# сами по себе — поэтому норма не перечисляет конкретные символы-разделители,
# а оставляет только буквы/цифры, вычищая ЛЮБОЙ разделительный "мусор" разом.
_ARTICLE_KEEP_RE = re.compile(r"[^0-9A-Z]+")

# Кириллица и латиница на глаз неразличимы для части букв — русская
# раскладка клавиатуры физически совпадает по расположению клавиш с
# латинской для этих букв, поэтому при наборе артикула кириллица
# просачивается на автомате (опечатка, а не другой артикул). Отображается
# как есть (contract_article/matched_article не трогаем), но при сравнении
# на этом должно совпадать.
_CYRILLIC_LOOKALIKES = str.maketrans(
    {"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y"}
)


def normalize_article(article: str | None) -> str | None:
    """Сводит два по-разному отформатированных написания ОДНОГО и того же
    артикула к одной строке для сравнения: убирает пробелы/тире/точки/слэши
    и любые другие небуквенно-цифровые разделители, приводит к верхнему
    регистру и схлопывает кириллические буквы-омоглифы в латинские
    аналоги. Пример из реальных данных заказчика: заказ-наряд содержит
    "234102G000", каталог поставщика — "23410-2G000" (тот же физический
    артикул). НЕ используется при запросах к внешним API поставщиков
    (Rossco/АвтоЕвро/Москворечье) — им нужен канонически отформатированный
    код, как в split_article_brand()."""
    if not article:
        return None
    normalized = article.upper().translate(_CYRILLIC_LOOKALIKES)
    normalized = _ARTICLE_KEEP_RE.sub("", normalized)
    return normalized or None


def _shortlist_candidates(name: str | None, order_lines: list[dict]) -> list[dict]:
    if not name or len(order_lines) <= LLM_CANDIDATE_LIMIT:
        return order_lines

    def tokens(value: str | None) -> set[str]:
        if not value:
            return set()
        return {
            token
            for token in re.findall(r"[0-9a-zа-яё]+", value.casefold().replace("ё", "е"))
            if len(token) >= 2 and token not in _MATCHING_STOPWORDS
        }

    normalized = re.sub(r"\s+", " ", name.strip().casefold())
    target_tokens = tokens(name)

    def score(line: dict) -> float:
        candidate_name = line.get("name") or ""
        candidate_normalized = re.sub(r"\s+", " ", candidate_name.strip().casefold())
        candidate_tokens = tokens(candidate_name)
        if not target_tokens or not candidate_tokens:
            token_score = 0.0
        else:
            overlap = len(target_tokens & candidate_tokens)
            token_score = overlap / len(target_tokens | candidate_tokens)
            # Полезно для случаев "кольцо стопорное" / "стопорное кольцо":
            # порядок слов не должен ухудшать результат до уровня случайного.
            if target_tokens <= candidate_tokens:
                token_score = max(token_score, 0.85)
        sequence_score = difflib.SequenceMatcher(None, normalized, candidate_normalized).ratio()
        return 0.6 * token_score + 0.4 * sequence_score

    scored = [
        (score(line), index, line)
        for index, line in enumerate(order_lines)
    ]
    # Индекс сохраняет стабильный порядок при равных оценках.
    scored.sort(key=lambda pair: (pair[0], -pair[1]), reverse=True)
    return [line for _, _, line in scored[:LLM_CANDIDATE_LIMIT]]


def _bounded_confidence(value: object, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


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
                    "confidence_score": _bounded_confidence(llm_result.get("confidence")),
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


def _contract_candidate_pool(
    contract_id: int,
    name: str | None,
    vehicle_make: str | None = None,
    limit: int = CONTRACT_CANDIDATE_POOL_LIMIT,
) -> list[dict]:
    base = ContractPart.query.filter_by(contract_id=contract_id)
    # Многобрендовый каталог (см. document_parser.parse_price_catalog_by_brand)
    # хранит запчасти разных марок в одном договоре, помеченные vehicle_make —
    # без этого фильтра LLM-подбор по названию мог бы предложить механику
    # деталь с вкладки Toyota для заказ-наряда на Hyundai. Строки без марки
    # (однобрендовые/старые договоры, где vehicle_make всегда NULL) фильтр не
    # затрагивает — тот же приём, что в labor_matcher._contract_labor_candidates.
    if vehicle_make:
        base = base.filter(
            ContractPart.vehicle_make.is_(None)
            | (db.func.lower(ContractPart.vehicle_make) == vehicle_make.lower())
        )
    if name:
        words = [w for w in re.findall(r"[0-9a-zа-яё]+", name.casefold()) if len(w) >= 3]
        candidates: list[ContractPart] = []
        seen_ids: set[int] = set()
        for word in words[:5]:
            for candidate in base.filter(ContractPart.name.ilike(f"%{word}%")).limit(limit).all():
                if candidate.id not in seen_ids:
                    seen_ids.add(candidate.id)
                    candidates.append(candidate)
        if candidates:
            rows = candidates[:limit]
        else:
            rows = base.limit(limit).all()
    else:
        rows = base.limit(limit).all()
    # Не передаём ORM-экземпляры между потоками: SQLAlchemy sessions
    # привязаны к worker-потоку. Простые словари безопасны и дешевле для
    # повторного использования в рамках одной операции сопоставления.
    return [
        {
            "article": row.article,
            "name": row.name,
            "price": float(row.price) if row.price is not None else None,
        }
        for row in rows
    ]


def match_line_against_contract(
    order_line: dict,
    contract_id: int,
    supplier_client: PartsSupplierClient,
    llm_client: LLMClient,
    vehicle_make: str | None = None,
    candidate_pool_cache: dict[tuple[int, str | None, str | None], list[dict]] | None = None,
) -> dict:
    article = order_line.get("article")
    name = order_line.get("name")
    clean_article, brand_hint = split_article_brand(article)

    if clean_article:
        exact = ContractPart.query.filter_by(contract_id=contract_id, article=clean_article).first()
        if exact is None and clean_article != article:
            # На случай, если в самом договоре артикулы записаны в том же
            # "код [бренд]" виде — сравниваем и с исходной строкой как есть.
            exact = ContractPart.query.filter_by(contract_id=contract_id, article=article).first()
        source = "exact_article_match"
        if exact is None:
            # Пробелы/тире у механика в заказ-наряде часто расходятся с
            # форматированием каталога (см. matcher.normalize_article) —
            # тот же физический артикул, просто иначе набран.
            normalized = normalize_article(clean_article)
            if normalized:
                exact = ContractPart.query.filter_by(
                    contract_id=contract_id, article_normalized=normalized
                ).first()
                source = "exact_article_match_normalized"
        if exact:
            return {
                "contract_article": article,
                "contract_name": name,
                "contract_qty": order_line.get("qty"),
                "matched_article": exact.article,
                "matched_name": exact.name,
                "matched_price": exact.price,
                "confidence_level": ConfidenceLevel.EXACT,
                "confidence_score": 1.0,
                "raw_match_data": {"source": source},
            }

    if clean_article:
        try:
            cross_refs = supplier_client.find_cross_references(clean_article, brand=brand_hint)
        except Exception:
            cross_refs = []
        for ref in cross_refs:
            ref_article = ref.get("article")
            found = ContractPart.query.filter_by(contract_id=contract_id, article=ref_article).first()
            if found is None:
                ref_normalized = normalize_article(ref_article)
                if ref_normalized:
                    found = ContractPart.query.filter_by(
                        contract_id=contract_id, article_normalized=ref_normalized
                    ).first()
            if found:
                return {
                    "contract_article": article,
                    "contract_name": name,
                    "contract_qty": order_line.get("qty"),
                    "matched_article": found.article,
                    "matched_name": found.name,
                    "matched_price": found.price,
                    "confidence_level": ConfidenceLevel.CROSS_REF,
                    "confidence_score": 0.9,
                    "raw_match_data": {"source": "parts_supplier_cross_reference", "candidates": cross_refs},
                }

    llm_error = None
    pool_key = (contract_id, name, vehicle_make)
    if candidate_pool_cache is not None and pool_key in candidate_pool_cache:
        candidates = candidate_pool_cache[pool_key]
    else:
        candidates = _contract_candidate_pool(contract_id, name, vehicle_make)
        if candidate_pool_cache is not None:
            candidate_pool_cache[pool_key] = candidates
    if candidates:
        shortlist = _shortlist_candidates(name, candidates)
        try:
            llm_result = llm_client.match_part_by_name(order_line, shortlist)
        except Exception as exc:
            llm_result = None
            llm_error = str(exc)
            logger.warning("LLM-сопоставление недоступно для %r: %s", name, exc)

        if llm_result is not None:
            idx = llm_result.get("matched_index")
            if idx is not None and 0 <= idx < len(shortlist):
                candidate = shortlist[idx]
                return {
                    "contract_article": article,
                    "contract_name": name,
                    "contract_qty": order_line.get("qty"),
                    "matched_article": candidate.get("article"),
                    "matched_name": candidate.get("name"),
                    "matched_price": candidate.get("price"),
                    "confidence_level": ConfidenceLevel.LLM_GUESS,
                    "confidence_score": _bounded_confidence(llm_result.get("confidence")),
                    "raw_match_data": {"source": "llm_fallback", "reasoning": llm_result.get("reasoning")},
                }

    return {
        "contract_article": article,
        "contract_name": name,
        "contract_qty": order_line.get("qty"),
        "matched_article": None,
        "matched_name": None,
        "matched_price": None,
        "confidence_level": ConfidenceLevel.LLM_GUESS,
        "confidence_score": 0.0,
        "raw_match_data": {"source": "llm_error", "error": llm_error} if llm_error else {"source": "no_match_found"},
    }


def match_all_against_contract(
    order_lines: list[dict],
    contract_id: int,
    supplier_client: PartsSupplierClient,
    llm_client: LLMClient,
    vehicle_make: str | None = None,
) -> list[dict]:
    from app.services.parallel import llm_workers, map_with_app_context

    # Несколько строк заказа часто имеют одно и то же название (например,
    # одинаковые расходники). Пул каталога неизменен в рамках этой операции,
    # поэтому не нужно выполнять одинаковый SELECT из каждого worker-потока.
    candidate_pool_cache: dict[tuple[int, str | None, str | None], list[dict]] = {}
    cache_lock = threading.Lock()

    def match_line_with_cached_pool(line: dict) -> dict:
        # Сначала берём кеш под блокировкой, затем сам запрос выполняется
        # только одним потоком для конкретного ключа.
        name = line.get("name")
        key = (contract_id, name, vehicle_make)
        with cache_lock:
            cached = candidate_pool_cache.get(key)
        if cached is None:
            with cache_lock:
                cached = candidate_pool_cache.get(key)
                if cached is None:
                    cached = _contract_candidate_pool(contract_id, name, vehicle_make)
                    candidate_pool_cache[key] = cached
        return match_line_against_contract(
            line,
            contract_id,
            supplier_client,
            llm_client,
            vehicle_make,
            candidate_pool_cache,
        )

    return map_with_app_context(
        match_line_with_cached_pool,
        order_lines,
        max_workers=llm_workers(),
    )
