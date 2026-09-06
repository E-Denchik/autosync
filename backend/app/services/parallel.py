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

Но и это верно ТОЛЬКО пока раннер считает на GPU — там узкое место
действительно сеть/ожидание. Если модель крутится на CPU (нет GPU, не
хватило VRAM, драйвер не установлен — как оказалось на машине заказчика:
NVIDIA-карта есть, но драйвер не отвечает, и Ollama сам переключился на
100% CPU), несколько одновременных запросов делят одну и ту же
вычислительную мощность между собой, а не выполняются независимо — и
только добавляют накладные расходы на переключение контекста. На практике
это выглядело так: 4 параллельных запроса к загруженной в CPU-режиме
gemma3:1b упирались в таймаут 295с ОДИН ЗА ДРУГИМ (видно в data/autosync.log
за 2026-09-02 22:48-22:57), а очередь backend'а (waitress) распухала,
потому что все воркер-потоки были заняты ожиданием. Заранее отличить
GPU-раннер от CPU-раннера универсально (Windows/macOS/Linux, Ollama/LM
Studio) не выйдет — вместо этого калибруемся эмпирически на первом
элементе пачки (см. _SLOW_FIRST_REQUEST_SECONDS ниже): если он и БЕЗ
конкуренции с другими потоками уже медленный — это CPU-раннер (или иная
перегрузка), и остальные элементы идут строго последовательно, а не в пул.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from flask import current_app

from app.services import progress_tracker

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Разумный предел одновременных запросов к одному раннеру — выше дефолтной
# параллельности Ollama почти нет смысла (лишние запросы просто встанут в
# очередь на его стороне), а слишком много потоков зря грузит CPU на
# сериализацию JSON/HTTP без выигрыша в скорости.
MAX_WORKERS = 4

# Калибровка в map_with_app_context (см. ниже) обнаруживает "раннер на CPU"
# на первом элементе КАЖДОЙ отдельной пачки — а пачек за один заказ-наряд
# или импорт каталога несколько (файлы, куски текста внутри файла,
# сопоставление запчастей, сопоставление работ — это разные, независимые
# вызовы map_with_app_context). Без общего состояния каждая пачка заново
# платит те же ~20с на калибровку и заново пытается параллелить, хотя ответ
# уже известен. Флаг с TTL решает это: один раз обнаружили медленный раннер —
# на ближайшие 5 минут ВСЕ вызовы (включая llm_workers() ниже, а значит и
# глобальный gate в llm_client.py) сразу знают об этом. TTL, а не постоянный
# флаг — раннер мог не быть медленным ("проиграл" за CPU другой программе
# в моменте) или пользователь мог переключить модель/провайдера.
_SLOW_RUNNER_COOLDOWN_SECONDS = 300.0
_slow_runner_lock = threading.Lock()
_slow_runner_detected_until = 0.0


def _mark_slow_runner() -> None:
    global _slow_runner_detected_until
    with _slow_runner_lock:
        _slow_runner_detected_until = time.monotonic() + _SLOW_RUNNER_COOLDOWN_SECONDS


def _slow_runner_active() -> bool:
    with _slow_runner_lock:
        return time.monotonic() < _slow_runner_detected_until


def cpu_only_suspected() -> bool:
    """Публичная обёртка над _slow_runner_active() — для UI-подсказок
    (Администрирование → LLM-модель/Производительность/Справка по
    моделям), которым нужно только прочитать уже вычисленное состояние
    (TTL 5 минут), без побочных эффектов и без нового замера."""
    return _slow_runner_active()


# Две параллельные генерации заметно повышают throughput небольших моделей,
# но четыре запроса часто забивают CPU/RAM и только увеличивают очередь Ollama.
# Для тяжёлых моделей значение можно снизить до 1 через окружение.
def llm_workers() -> int:
    if _slow_runner_active():
        return 1
    try:
        from app.services.performance_settings import effective_settings

        return effective_settings()["settings"]["workers"]
    except Exception:
        return max(1, int(os.environ.get("AUTOSYNC_LLM_WORKERS", "2")))


# Если ПЕРВЫЙ элемент пачки — без какой-либо конкуренции за CPU, других
# потоков ещё нет — уже занял больше этого времени, дальнейшее
# распараллеливание не ускорит обработку, а только заставит несколько таких
# же тяжёлых запросов делить одну и ту же CPU между собой (см. докстринг
# модуля). 20с с запасом отделяет нормальный ответ уже загруженной модели
# (обычно единицы секунд, даже на скромном железе) от явно CPU-bound
# генерации на крупном промпте/OCR-таблице.
_SLOW_FIRST_REQUEST_SECONDS = 20.0


def map_with_app_context(fn: Callable[[T], R], items: list[T], max_workers: int = MAX_WORKERS) -> list[R]:
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
    накладные расходы на поток там, где распараллеливать нечего.

    Для >1 элемента первый элемент — калибровочный: выполняется ДО пула,
    в одиночку, и его время решает, стоит ли параллелить остальные (см.
    _SLOW_FIRST_REQUEST_SECONDS и докстринг модуля про CPU-only раннер)."""
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

    if max_workers <= 1:
        return [_run(item) for item in items]

    if _slow_runner_active():
        # Уже знаем по другой, недавней пачке (см. _mark_slow_runner) — не
        # платим повторно за калибровку первого элемента здесь.
        return [_run(item) for item in items]

    calibration_started = time.monotonic()
    first_result = _run(items[0])
    calibration_elapsed = time.monotonic() - calibration_started
    if calibration_elapsed > _SLOW_FIRST_REQUEST_SECONDS:
        logger.warning(
            "Первый запрос занял %.1fс (порог %.0fс) — похоже, раннер считает "
            "на CPU без ускорителя. Остальные %s элементов идут последовательно "
            "вместо %s параллельных потоков, чтобы не делить CPU и не множить "
            "таймауты. Следующие %.0fс это же будут знать все остальные пачки "
            "(файлы/куски текста/сопоставление), не только эта.",
            calibration_elapsed,
            _SLOW_FIRST_REQUEST_SECONDS,
            total - 1,
            max_workers,
            _SLOW_RUNNER_COOLDOWN_SECONDS,
        )
        _mark_slow_runner()
        max_workers = 1

    remaining = items[1:]
    if max_workers <= 1:
        remaining_results = [_run(item) for item in remaining]
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="autosync-llm") as executor:
            remaining_results = list(executor.map(_run, remaining))
    return [first_result] + remaining_results
