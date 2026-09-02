"""Запуск нескольких независимых блокирующих запросов ОДНОВРЕМЕННО, вместо
строго по одному за раз — LLM-запросов к уже выбранной модели, а также
других сетевых вызовов на позицию (см. nomenclature_matcher.py).

Ollama (и LM Studio) обслуживают несколько параллельных запросов к уже
загруженной в память модели — большая часть времени на позицию тратится на
ожидание ответа модели по сети, а не на CPU/БД, поэтому раньше сопоставление
заказ-наряда с десятками позиций шло заметно дольше, чем могло бы, просто
из-за строго последовательного перебора (см. repair_order_processor.py,
matcher.py, labor_matcher.py, llm_client.py: extract_table_from_text).

ВАЖНО: это НЕ параллель РАЗНЫХ моделей — та рискованна на типичном железе
(см. обсуждение с заказчиком): если несколько разных моделей не помещаются
в память одновременно, раннер будет постоянно выгружать одну и грузить
другую, и станет медленнее, а не быстрее. Здесь же несколько запросов идут
к ОДНОЙ уже загруженной модели — тот же принцип, которым сам Ollama
параллелит несколько ассистентов/вкладок одного чата.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from flask import current_app

from app.services import progress_tracker

T = TypeVar("T")
R = TypeVar("R")

# Разумный предел одновременных запросов к одному раннеру — выше дефолтной
# параллельности Ollama почти нет смысла (лишние запросы просто встанут в
# очередь на его стороне), а слишком много потоков зря грузит CPU на
# сериализацию JSON/HTTP без выигрыша в скорости.
MAX_WORKERS = 4


def map_with_app_context(fn: Callable[[T], R], items: list[T]) -> list[R]:
    """list(map(fn, items)), но для >1 элемента — параллельно, каждый в
    своём потоке со своим app_context (Flask-контекст, включая db.session,
    не наследуется дочерними потоками автоматически — тот же приём, что и
    в job_queue.py для фоновых задач, только на уровень глубже: здесь сама
    обработка заказ-наряда уже идёт в фоновом потоке, а это — параллелизм
    ВНУТРИ неё). Порядок результатов соответствует порядку items.

    На каждое завершённое (в порядке РЕАЛЬНОГО выполнения, не items) —
    сообщает progress_tracker.report(сделано, всего): откуда именно
    вызвали map_with_app_context, знает не эта функция, а
    progress_tracker — здесь просто считаем сделанные элементы
    потокобезопасно и отдаём наверх.

    Для 0-1 элементов выполняет прямо в текущем потоке без пула — не платим
    накладные расходы на поток там, где распараллеливать нечего."""
    if len(items) <= 1:
        results = [fn(item) for item in items]
        if items:
            progress_tracker.report(1, 1)
        return results

    app = current_app._get_current_object()
    # Читаем ОДНО конкретное значение из текущего (вызывающего) потока —
    # ПЕРЕД тем как раздать работу по пулу, а не передаём весь contextvars-
    # контекст целиком: contextvars.copy_context() даёт объект, который
    # нельзя параллельно "войти" (.run()) сразу из нескольких потоков —
    # именно так падало здесь при реальной обработке (RuntimeError: cannot
    # enter context: ... is already entered). Ниже каждый поток пула сам
    # проставляет это же значение в СВОЙ, отдельный контекст.
    repair_order_id = progress_tracker.current_repair_order_id()
    total = len(items)
    lock = threading.Lock()
    state = {"completed": 0}

    def _run(item: T) -> R:
        if repair_order_id is not None:
            progress_tracker.bind_for_worker_thread(repair_order_id)
        with app.app_context():
            result = fn(item)
        with lock:
            state["completed"] += 1
            done = state["completed"]
        progress_tracker.report(done, total)
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="autosync-llm") as executor:
        return list(executor.map(_run, items))
