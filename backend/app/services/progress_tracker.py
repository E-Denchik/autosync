"""Прогресс "сколько уже сделано из скольки" для текущей фазы обработки
заказ-наряда (парсинг/сопоставление) — отдельно от RepairOrder.status
(тот знает только НАЗВАНИЕ фазы, не долю выполнения внутри неё).

Живёт только в памяти процесса, не в БД: это сиюминутное состояние
активной фоновой задачи (см. job_queue.py — сама очередь задач тоже без
персистентного состояния, только RepairOrder.status переживает
перезапуск), пересчитывать его после падения приложения всё равно не из
чего. Ключ — repair_order_id, чтобы несколько заказ-нарядов могли
обрабатываться одновременно (job_queue.py: ThreadPoolExecutor(max_workers=2))
без путаницы прогресса одного с другим.

Ключ намеренно типизирован как int | str: массовый импорт каталога
договора (contract_catalog_import.py) переиспользует этот же модуль под
СВОИМ пространством ключей — строкой вида "contract:{id}", а не голым
Contract.id, чтобы не столкнуться с RepairOrder.id той же величины (это
две независимые таблицы с автоинкрементом, ничто не мешает им совпасть
числом).

Кто именно из потоков параллельной обработки (см. parallel.py:
map_with_app_context) сейчас работает над каким repair_order_id — определяется
через contextvars, а не через явный параметр в каждой сигнатуре функции:
tracking() привязывает id к контексту ОДИН раз в самом начале обработки
(job_queue.py), а map_with_app_context копирует контекст в каждый дочерний
поток пула (тот же приём, которым Python asyncio передаёт контекст в задачи).
Поэтому report() из parallel.py работает для ЛЮБОГО вызова
map_with_app_context внутри tracking() — будь то сопоставление запчастей,
работ или разбор текста через LLM (llm_client.py: extract_table_from_text) —
без изменений в каждом из этих мест по отдельности."""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from datetime import datetime

_current_repair_order_id: contextvars.ContextVar[int | str | None] = contextvars.ContextVar(
    "current_repair_order_id", default=None
)

_lock = threading.Lock()
_progress: dict[int | str, dict[str, int]] = {}


@contextmanager
def tracking(repair_order_id: int | str):
    """Обернуть весь жизненный цикл обработки одного заказ-наряда — см.
    job_queue.py: enqueue_process_upload. token/reset (а не просто set)
    обязателен: ThreadPoolExecutor переиспользует потоки между задачами
    (job_queue._executor, max_workers=2), и без reset() значение
    contextvar осталось бы висеть в переиспользованном потоке и
    "утекло" бы в обработку СЛЕДУЮЩЕГО заказ-наряда на том же потоке."""
    token = _current_repair_order_id.set(repair_order_id)
    try:
        yield
    finally:
        _current_repair_order_id.reset(token)
        clear(repair_order_id)


def current_repair_order_id() -> int | str | None:
    """Для parallel.py: узнать, за каким repair_order_id числится текущий
    (главный, вызывающий map_with_app_context) поток — ПЕРЕД тем как
    раздать работу по пулу. Специально не отдаём наружу сам ContextVar
    и не полагаемся на contextvars.copy_context()/Context.run(): один и
    тот же скопированный Context нельзя одновременно "войти" из нескольких
    потоков — ровно так и падало при параллельном исполнении в пуле."""
    return _current_repair_order_id.get()


def bind_for_worker_thread(repair_order_id: int | str) -> None:
    """Пул-воркер из parallel.py: каждый вызывающий поток здесь новый и
    создан заново специально для ОДНОГО вызова map_with_app_context (сам
    ThreadPoolExecutor там создаётся и уничтожается внутри этого вызова,
    не переиспользуется между разными map_with_app_context) — поэтому
    здесь достаточно простого set() без токена/reset, в отличие от
    tracking() для job_queue._executor (тот НАСТОЯЩИЙ переиспользуемый
    пул между разными фоновыми задачами, там reset() обязателен)."""
    _current_repair_order_id.set(repair_order_id)


def report(current: int, total: int) -> None:
    """Вызывается из parallel.py: map_with_app_context на каждое
    завершение элемента. Тихо ничего не делает, если текущий поток не
    внутри tracking() (например, импорт номенклатуры или каталога
    контракта вне обработки конкретного заказ-наряда) — прогресс для
    таких вызовов просто не показывается, это не ошибка.

    started_at фиксируется один раз на "пачку" (один вызов
    map_with_app_context — например, разбор одного файла на куски или
    сопоставление всех позиций заказ-наряда) и держится, пока total не
    изменится: смена total значит, что началась НОВАЯ пачка (например,
    сопоставление перешло с запчастей на работы), и отсчёт времени для
    оценки оставшегося должен начаться заново — иначе фронт считал бы
    скорость новой пачки по времени, натёкшему ещё для старой."""
    repair_order_id = _current_repair_order_id.get()
    if repair_order_id is None:
        return
    with _lock:
        existing = _progress.get(repair_order_id)
        if existing is not None and existing["total"] == total:
            started_at = existing["started_at"]
        else:
            started_at = datetime.utcnow().isoformat()
        _progress[repair_order_id] = {"current": current, "total": total, "started_at": started_at}


def get(repair_order_id: int | str) -> dict[str, int | str] | None:
    with _lock:
        progress = _progress.get(repair_order_id)
        return dict(progress) if progress else None


def clear(repair_order_id: int | str) -> None:
    with _lock:
        _progress.pop(repair_order_id, None)
