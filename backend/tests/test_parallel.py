import threading
import time

import pytest

from app.services import parallel
from app.services import progress_tracker
from app.services.parallel import map_with_app_context


@pytest.fixture(autouse=True)
def _reset_slow_runner_state():
    """_mark_slow_runner() пишет в состояние на уровне МОДУЛЯ (нарочно —
    см. docstring parallel.py про общий на процесс TTL-флаг), которое иначе
    пережило бы отдельный тест и молча превратило бы следующий "быстрый"
    тест в такой же fallback на последовательную обработку."""
    parallel._slow_runner_detected_until = 0.0
    yield
    parallel._slow_runner_detected_until = 0.0


def test_cpu_only_suspected_reflects_slow_runner_flag_and_ttl():
    assert parallel.cpu_only_suspected() is False
    parallel._mark_slow_runner()
    assert parallel.cpu_only_suspected() is True
    parallel._slow_runner_detected_until = time.monotonic() - 1
    assert parallel.cpu_only_suspected() is False


def test_map_with_app_context_preserves_order(app):
    with app.app_context():
        result = map_with_app_context(lambda x: x * 2, [1, 2, 3, 4, 5])
    assert result == [2, 4, 6, 8, 10]


def test_map_with_app_context_single_item_runs_without_pool(app):
    calls = []

    def fn(x):
        calls.append(x)
        return x

    with app.app_context():
        result = map_with_app_context(fn, [42])
    assert result == [42]
    assert calls == [42]


def test_map_with_app_context_zero_items(app):
    with app.app_context():
        assert map_with_app_context(lambda x: x, []) == []


def test_map_with_app_context_reports_progress_when_tracking_bound(app):
    """Регрессия: раньше это падало с 'RuntimeError: cannot enter context:
    ... is already entered' — один и тот же contextvars.Context, скопированный
    ОДИН раз снаружи, нельзя одновременно .run() из нескольких потоков пула.
    Реально воспроизводится только на >1 элементе (см. map_with_app_context:
    для 0-1 элементов вообще нет пула потоков)."""
    with app.app_context():
        with progress_tracker.tracking(555):
            result = map_with_app_context(lambda x: x * 2, list(range(20)))

    assert result == [x * 2 for x in range(20)]
    # К моменту выхода из tracking() прогресс уже очищен (см. progress_tracker.tracking),
    # но во время выполнения report() успел дойти хотя бы до финального (20, 20) —
    # проверяем это не гонкой за живым состоянием, а тем, что общий проход
    # не уронил исключение и все 20 результатов посчитаны корректно.
    assert progress_tracker.get(555) is None


def test_map_with_app_context_progress_reaches_total_before_tracking_exits(app):
    seen_final = {}

    def fn(x):
        time.sleep(0.01)
        seen_final["last"] = progress_tracker.get(777)
        return x

    with app.app_context():
        with progress_tracker.tracking(777):
            map_with_app_context(fn, list(range(8)))
            # Ещё внутри tracking(), после того как map_with_app_context уже
            # вернул управление, — все элементы точно обработаны.
            progress = progress_tracker.get(777)
            assert progress["current"] == 8
            assert progress["total"] == 8
            assert progress["started_at"]


def test_map_with_app_context_falls_back_to_sequential_when_first_item_is_slow(app, monkeypatch):
    """Регрессия: на CPU-only раннере (нет GPU, как выяснилось на машине
    заказчика — см. docstring parallel.py) несколько параллельных запросов
    делят одну и ту же вычислительную мощность и только множат таймауты
    вместо ускорения. Если уже первый (калибровочный, без конкуренции)
    элемент подозрительно медленный — остальные должны пойти строго
    последовательно, а не в пул потоков."""
    monkeypatch.setattr(parallel, "_SLOW_FIRST_REQUEST_SECONDS", -1.0)
    thread_names = []

    def fn(x):
        thread_names.append(threading.current_thread().name)
        return x * 2

    with app.app_context():
        result = map_with_app_context(fn, list(range(5)))

    assert result == [0, 2, 4, 6, 8]
    assert not any(name.startswith("autosync-llm") for name in thread_names)


def test_map_with_app_context_stays_parallel_when_first_item_is_fast(app, monkeypatch):
    """Обратная сторона предыдущего теста: если раннер отвечает быстро
    (обычный случай — GPU или лёгкая модель), калибровка не должна мешать
    параллельной обработке остальных элементов."""
    monkeypatch.setattr(parallel, "_SLOW_FIRST_REQUEST_SECONDS", 20.0)
    thread_names = []
    lock = threading.Lock()

    def fn(x):
        with lock:
            thread_names.append(threading.current_thread().name)
        return x * 2

    with app.app_context():
        result = map_with_app_context(fn, list(range(5)), max_workers=4)

    assert result == [0, 2, 4, 6, 8]
    assert any(name.startswith("autosync-llm") for name in thread_names)


def test_map_with_app_context_sticky_slow_runner_skips_recalibration(app, monkeypatch):
    """_mark_slow_runner() должен защищать СЛЕДУЮЩИЙ, отдельный вызов
    map_with_app_context (например, куски текста внутри следующего файла) —
    не только оставшиеся элементы ТЕКУЩЕЙ пачки. Проверяем это отдельным
    вызовом ПОСЛЕ того, как первый уже обнаружил медленный раннер: второй
    вызов не должен звать fn() медленно ещё раз ради калибровки — первый же
    элемент второй пачки должен пойти в тот же последовательный путь сразу."""
    monkeypatch.setattr(parallel, "_SLOW_FIRST_REQUEST_SECONDS", -1.0)
    thread_names = []

    def fn(x):
        thread_names.append(threading.current_thread().name)
        return x

    with app.app_context():
        map_with_app_context(fn, list(range(3)))  # помечает раннер медленным
        assert parallel._slow_runner_active()

        thread_names.clear()
        result = map_with_app_context(fn, list(range(3)), max_workers=4)

    assert result == [0, 1, 2]
    assert not any(name.startswith("autosync-llm") for name in thread_names)


def test_map_with_app_context_without_tracking_reports_nothing(app):
    """Без tracking() (например, импорт номенклатуры вне обработки
    заказ-наряда) report() тихо не пишет ничего — прогресс для соседнего,
    реально отслеживаемого заказ-наряда (888) не появляется и не путается."""
    with app.app_context():
        map_with_app_context(lambda x: x, list(range(5)))
    assert progress_tracker.get(888) is None
