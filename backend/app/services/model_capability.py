"""Грубая, но честная оценка возможностей LLM-модели для оператора,
выбирающего модель в Администрирование → LLM-модель/Справка по моделям.

Не претендует на точность — это ориентир по числу параметров (или, если
оно неизвестно, по размеру файла/имени), а не бенчмарк. Цель — предупредить
о том, что реально всплыло на практике: маленькая локальная модель (1-3B)
технически отвечает на любой запрос, включая открытую генерацию (например,
"расписать работу"), но эти ответы часто общие/неточные — в отличие от
задач классификации/сопоставления по названию, где той же модели обычно
достаточно.
"""

from __future__ import annotations

import re

_PARAM_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*([BMK])\s*$", re.IGNORECASE)

# Требуем разделитель (дефис/подчёркивание/пробел/начало-конец строки)
# сразу перед числом и сразу после буквы размера — иначе "v2" в
# "model-v2-beta" или "b" внутри случайного слова ложно матчились бы как
# указание на число параметров.
_NAME_SIZE_RE = re.compile(r"(?:^|[-_ :])(\d+(?:\.\d+)?)[Bb](?:[-_ .]|$)")

_UNIT_MULTIPLIERS = {"K": 1e-6, "M": 1e-3, "B": 1.0}

_TIER_ORDER = ("tiny", "small", "medium", "large")
_TIER_BOUNDARIES = (2.0, 8.0, 20.0)  # tiny<2B<=small<8B<=medium<20B<=large

_TIER_LABELS = {
    "tiny": "компактная",
    "small": "сбалансированная",
    "medium": "мощная",
    "large": "очень мощная",
}

_TIER_NOTES = {
    "tiny": (
        "Быстро отвечает даже на слабом железе, но для открытой генерации "
        "(например, «расписать работу») ответы часто общие или неточные. "
        "Хорошо подходит для классификации и сопоставления по названию."
    ),
    "small": (
        "Разумный компромисс скорости и качества. Для генерации инструкций "
        "может давать общие формулировки без специфики модели/операции."
    ),
    "medium": (
        "Заметно лучше держит контекст и специфику задачи — подходит для "
        "генерации пошаговых инструкций, но требует больше памяти и "
        "работает медленнее."
    ),
    "large": (
        "Лучшее качество генерации из локальных моделей, но требовательна "
        "к памяти — на слабом железе может быть непрактично медленной."
    ),
}

_UNKNOWN_NOTE = "Размер модели не определён — оценить пригодность для задачи нельзя."

_CLOUD_NOTE = (
    "Качество и скорость не зависят от железа этого компьютера — оплата по "
    "факту запроса. Модели vsegpt.ru сильно различаются по возможностям "
    "(от простых до топовых) — ориентируйтесь на цену и репутацию "
    "конкретной модели, а не на этот список."
)


def parse_param_billions(parameter_size: str | None) -> float | None:
    """'999.89M' -> 0.99989, '3.2B' -> 3.2, '7B' -> 7.0. None/непонятный
    формат -> None."""
    if not parameter_size:
        return None
    match = _PARAM_SIZE_RE.match(parameter_size)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value * _UNIT_MULTIPLIERS[match.group(2).upper()]


def guess_param_billions_from_name(name: str) -> float | None:
    """Резервная оценка по имени/имени файла модели, например
    'llama3.2:3b' -> 3.0, 'Meta-Llama-3.1-8B-Instruct-Q4_K_M' -> 8.0.
    Возвращает последнее совпадение — конечное "…-8B-…" обычно и есть
    число параметров, тогда как ведущие числа в имени чаще версия модели."""
    matches = _NAME_SIZE_RE.findall(name or "")
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def guess_param_billions_from_size_bytes(size_bytes: int | None) -> float | None:
    """Последний резерв: очень грубая оценка по размеру файла в
    предположении ~4-битного квантования (Q4_K_M и подобные — самые
    распространённые готовые сборки на Ollama/LM Studio), где на 1B
    параметров уходит примерно 0.6 ГБ. Используется только когда ни
    метаданные, ни имя модели ничего не дали."""
    if not size_bytes or size_bytes <= 0:
        return None
    return (size_bytes / 1024**3) / 0.6


def _tier_for_billions(params_billions: float) -> str:
    for tier, boundary in zip(_TIER_ORDER, _TIER_BOUNDARIES):
        if params_billions < boundary:
            return tier
    return "large"


def capability_for_local_model(
    *, parameter_size: str | None, name: str, size_bytes: int | None = None
) -> dict:
    """Оценка локальной (Ollama/LM Studio) модели. Порядок источника:
    parameter_size (реальные метаданные Ollama) -> оценка по имени ->
    оценка по размеру файла -> unknown, если ничего не дало результата."""
    params_billions = parse_param_billions(parameter_size)
    source = "details" if params_billions is not None else None

    if params_billions is None:
        params_billions = guess_param_billions_from_name(name)
        source = "name_guess" if params_billions is not None else None

    if params_billions is None:
        params_billions = guess_param_billions_from_size_bytes(size_bytes)
        source = "size_guess" if params_billions is not None else None

    if params_billions is None:
        return {
            "tier": "unknown",
            "params_billions": None,
            "label": None,
            "note": _UNKNOWN_NOTE,
            "source": "unknown",
        }

    tier = _tier_for_billions(params_billions)
    return {
        "tier": tier,
        "params_billions": params_billions,
        "label": _TIER_LABELS[tier],
        "note": _TIER_NOTES[tier],
        "source": source,
    }


def capability_for_cloud_model(name: str) -> dict:
    return {
        "tier": "cloud",
        "params_billions": None,
        "label": "облачная",
        "note": _CLOUD_NOTE,
        "source": "cloud",
    }
