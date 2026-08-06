def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_api_responses_are_not_cached(client):
    # См. app/__init__.py: _no_store_api_responses — без этого заголовка
    # WebKitGTK (окно native-режима) кэширует GET-запросы через reload,
    # из-за чего /api/auth/setup-required могла молча отдавать устаревший
    # ответ и держать пользователя на уже пройденном мастере /setup.
    resp = client.get("/api/health")
    assert resp.headers.get("Cache-Control") == "no-store"
