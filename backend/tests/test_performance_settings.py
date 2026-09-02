from app.services import performance_settings


def test_performance_endpoint_returns_system_and_recommendation(client):
    response = client.get("/api/performance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["settings"]["mode"] == "auto"
    assert body["settings"]["workers"] >= 1
    assert body["recommendation"]["workers"] >= 1
    assert "cpu_count" in body["system"]


def test_performance_manual_settings_are_persisted(client):
    response = client.put(
        "/api/performance",
        json={"mode": "manual", "workers": 1, "timeout_seconds": 120},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["settings"] == {"mode": "manual", "workers": 1, "timeout_seconds": 120}

    response = client.get("/api/performance")
    assert response.get_json()["settings"] == body["settings"]


def test_performance_auto_mode_clears_manual_values(client):
    client.put("/api/performance", json={"mode": "manual", "workers": 1, "timeout_seconds": 120})
    response = client.put("/api/performance", json={"mode": "auto"})

    assert response.status_code == 200
    assert response.get_json()["settings"]["mode"] == "auto"


def test_performance_rejects_unsafe_manual_values(client):
    response = client.put(
        "/api/performance",
        json={"mode": "manual", "workers": 9, "timeout_seconds": 10},
    )

    assert response.status_code == 400


def test_recommendation_warns_when_model_does_not_fit_total_ram():
    """8 ГБ RAM, модель 14B (~9 ГБ) — не помещается даже в ВЕСЬ объём
    памяти, не только в доступный сейчас остаток. Это сценарий "6 из 179
    файлов за 10 минут": сам локальный раннер не откажет, а будет
    отвечать на порядок медленнее из-за свопирования."""
    info = {
        "platform": "Linux",
        "cpu_count": 4,
        "memory_total_bytes": 8 * 1024**3,
        "memory_available_bytes": 6 * 1024**3,
    }
    result = performance_settings.recommendation(info, model_size_bytes=9 * 1024**3)

    assert result["timeout_seconds"] == 600
    assert any("не помещается" not in w and "весит" in w for w in result["warnings"])


def test_recommendation_no_ram_warning_when_model_fits_easily():
    info = {
        "platform": "Linux",
        "cpu_count": 8,
        "memory_total_bytes": 32 * 1024**3,
        "memory_available_bytes": 20 * 1024**3,
    }
    result = performance_settings.recommendation(info, model_size_bytes=9 * 1024**3)

    assert result["warnings"] == []
