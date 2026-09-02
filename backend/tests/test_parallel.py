import time

from app.services import progress_tracker
from app.services.parallel import map_with_app_context


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


def test_map_with_app_context_without_tracking_reports_nothing(app):
    """Без tracking() (например, импорт номенклатуры вне обработки
    заказ-наряда) report() тихо не пишет ничего — прогресс для соседнего,
    реально отслеживаемого заказ-наряда (888) не появляется и не путается."""
    with app.app_context():
        map_with_app_context(lambda x: x, list(range(5)))
    assert progress_tracker.get(888) is None
