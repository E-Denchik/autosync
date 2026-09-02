from app.services import llm_extraction_cache


def test_build_key_is_stable_for_same_inputs():
    key1 = llm_extraction_cache.build_key("ollama", "qwen2.5:7b", ["article", "name"], "строка текста")
    key2 = llm_extraction_cache.build_key("ollama", "qwen2.5:7b", ["article", "name"], "строка текста")
    assert key1 == key2


def test_build_key_ignores_field_order():
    key1 = llm_extraction_cache.build_key("ollama", "qwen2.5:7b", ["article", "name"], "текст")
    key2 = llm_extraction_cache.build_key("ollama", "qwen2.5:7b", ["name", "article"], "текст")
    assert key1 == key2


def test_build_key_differs_for_different_model():
    """Смена модели должна давать другой ключ — иначе после апгрейда
    модели пользователь молча получал бы результат от старой."""
    key1 = llm_extraction_cache.build_key("ollama", "qwen2.5:7b", ["article"], "текст")
    key2 = llm_extraction_cache.build_key("ollama", "qwen2.5:14b", ["article"], "текст")
    assert key1 != key2


def test_build_key_differs_for_different_provider():
    key1 = llm_extraction_cache.build_key("ollama", "m", ["article"], "текст")
    key2 = llm_extraction_cache.build_key("vsegpt", "m", ["article"], "текст")
    assert key1 != key2


def test_build_key_differs_for_different_chunk_text():
    key1 = llm_extraction_cache.build_key("ollama", "m", ["article"], "текст A")
    key2 = llm_extraction_cache.build_key("ollama", "m", ["article"], "текст B")
    assert key1 != key2


def test_build_key_does_not_confuse_field_chunk_boundary():
    """fields=["a"] + chunk="bc" не должно совпасть с fields=["ab"] + chunk="c" —
    без разделителя простая конкатенация строк дала бы одинаковый ключ."""
    key1 = llm_extraction_cache.build_key("p", "m", ["a"], "bc")
    key2 = llm_extraction_cache.build_key("p", "m", ["ab"], "c")
    assert key1 != key2


def test_get_returns_none_for_unknown_key(app):
    with app.app_context():
        assert llm_extraction_cache.get("не существует") is None


def test_set_then_get_roundtrips(app):
    key = llm_extraction_cache.build_key("ollama", "m", ["article"], "текст")
    rows = [{"article": "A1", "name": "Болт"}]
    with app.app_context():
        llm_extraction_cache.set(key, rows)
        assert llm_extraction_cache.get(key) == rows


def test_set_is_idempotent_on_key_collision(app):
    """Гонка параллельных потоков (см. parallel.py) может привести к тому,
    что set() вызовется дважды для одного ключа — вторая попытка не должна
    падать или дублировать запись."""
    key = llm_extraction_cache.build_key("ollama", "m", ["article"], "текст")
    with app.app_context():
        llm_extraction_cache.set(key, [{"article": "A1"}])
        llm_extraction_cache.set(key, [{"article": "A1"}])  # не должно бросить исключение

        from app.models import LlmExtractionCache

        count = LlmExtractionCache.query.filter_by(cache_key=key).count()
        assert count == 1
