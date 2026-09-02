import threading
from concurrent.futures import ThreadPoolExecutor

from app.services import progress_tracker


def test_report_without_tracking_is_a_silent_noop():
    """Вызов report() вне tracking() (например, импорт номенклатуры/каталога
    контракта сам по себе, без привязки к конкретному заказ-наряду) не должен
    ничего записывать и не должен падать."""
    progress_tracker.report(1, 10)
    assert progress_tracker.get(999999) is None


def test_tracking_makes_report_visible_by_repair_order_id():
    with progress_tracker.tracking(42):
        progress_tracker.report(3, 10)
        progress = progress_tracker.get(42)
        assert progress["current"] == 3
        assert progress["total"] == 10
        assert progress["started_at"]  # фронт считает по нему оценку оставшегося времени


def test_started_at_stays_the_same_within_one_batch():
    """started_at фиксируется один раз на пачку (см. report()) — иначе
    оценка оставшегося времени считала бы скорость от каждого нового
    вызова report(), а не от начала всей пачки."""
    with progress_tracker.tracking(42):
        progress_tracker.report(1, 10)
        first_started_at = progress_tracker.get(42)["started_at"]
        progress_tracker.report(2, 10)
        assert progress_tracker.get(42)["started_at"] == first_started_at


def test_started_at_resets_when_a_new_batch_starts():
    """Смена total (например, сопоставление перешло с запчастей на
    работы) — это НОВАЯ пачка, отсчёт времени должен начаться заново."""
    with progress_tracker.tracking(42):
        progress_tracker.report(9, 10)
        first_started_at = progress_tracker.get(42)["started_at"]
        progress_tracker.report(1, 5)  # другой total — новая пачка
        assert progress_tracker.get(42)["started_at"] != first_started_at


def test_progress_cleared_after_tracking_block_exits():
    with progress_tracker.tracking(42):
        progress_tracker.report(3, 10)
    assert progress_tracker.get(42) is None


def test_progress_cleared_even_if_exception_raised_inside_tracking():
    try:
        with progress_tracker.tracking(42):
            progress_tracker.report(3, 10)
            raise ValueError("бум")
    except ValueError:
        pass
    assert progress_tracker.get(42) is None


def test_tracking_does_not_leak_into_unrelated_repair_order_id():
    with progress_tracker.tracking(1):
        progress_tracker.report(5, 5)
    with progress_tracker.tracking(2):
        progress_tracker.report(1, 5)
        # Прогресс первого заказ-наряда уже очищен, а не "утёк" во второй.
        assert progress_tracker.get(1) is None
        progress = progress_tracker.get(2)
        assert progress["current"] == 1
        assert progress["total"] == 5


def test_tracking_does_not_leak_into_reused_pool_thread():
    """job_queue.py переиспользует потоки пула между разными фоновыми
    задачами (ThreadPoolExecutor(max_workers=2)) — без правильного
    reset() в tracking() значение привязки могло бы "утечь" в обработку
    следующей задачи, случайно запущенной на том же переиспользованном
    потоке. max_workers=1 гарантирует, что обе задачи ниже реально
    выполнятся на ОДНОМ и том же потоке, последовательно."""
    seen_in_second_task = {}

    def task_one():
        with progress_tracker.tracking(100):
            progress_tracker.report(1, 1)

    def task_two():
        # Не привязываем ничего — как выглядела бы задача ВНЕ tracking()
        # (например, отдельный enqueue_import_contract на том же потоке пула).
        seen_in_second_task["repair_order_id"] = progress_tracker.current_repair_order_id()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(task_one).result()
        executor.submit(task_two).result()

    assert seen_in_second_task["repair_order_id"] is None
    assert progress_tracker.get(100) is None


def test_tracking_accepts_string_key_without_colliding_with_int_ids():
    """contract_catalog_import.py использует ключ "contract:{id}" в том же
    модуле, что и repair_order_id (int) из job_queue.py — Contract.id и
    RepairOrder.id независимые автоинкременты, ничто не мешает им
    совпасть числом (например, оба = 42), поэтому пространства ключей
    должны оставаться раздельными по типу/содержимому строки, не только по
    значению."""
    with progress_tracker.tracking(42):
        progress_tracker.report(1, 5)
        with progress_tracker.tracking("contract:42"):
            progress_tracker.report(3, 10)
            assert progress_tracker.get(42)["current"] == 1
            assert progress_tracker.get("contract:42")["current"] == 3
        assert progress_tracker.get("contract:42") is None
        assert progress_tracker.get(42)["current"] == 1


def test_bind_for_worker_thread_is_visible_only_in_that_thread():
    results = {}

    def worker():
        progress_tracker.bind_for_worker_thread(7)
        results["seen"] = progress_tracker.current_repair_order_id()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert results["seen"] == 7
    # Главный поток теста не был привязан — воркер работал в СВОЁМ контексте.
    assert progress_tracker.current_repair_order_id() is None
