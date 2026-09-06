"""Адаптивные параметры производительности приложения.

Системные характеристики читаются локально, а ручной профиль хранится в
каталоге данных приложения. Секреты и пользовательские интеграции сюда не
попадают.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import threading
from pathlib import Path

from flask import current_app

_lock = threading.Lock()
_DEFAULTS = {"mode": "auto", "workers": None, "timeout_seconds": None}


def _settings_path() -> Path:
    return Path(current_app.config["DATA_DIR"]) / "performance-settings.json"


def _read_manual() -> dict:
    try:
        with _settings_path().open(encoding="utf-8") as stream:
            value = json.load(stream)
        return {**_DEFAULTS, **value} if isinstance(value, dict) else dict(_DEFAULTS)
    except (OSError, ValueError):
        return dict(_DEFAULTS)


def save_settings(updates: dict) -> dict:
    settings = _read_manual()
    settings.update(updates)
    settings["mode"] = "manual" if settings.get("mode") == "manual" else "auto"
    for key in ("workers", "timeout_seconds"):
        value = settings.get(key)
        if value is not None:
            settings[key] = int(value)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        fd, temp_path = tempfile.mkstemp(prefix="performance-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(settings, stream, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    return settings


def system_info() -> dict:
    memory_total = memory_available = None
    try:
        values = {}
        with open("/proc/meminfo", encoding="ascii") as stream:
            for line in stream:
                key, value = line.split(":", 1)
                values[key] = int(value.split()[0]) * 1024
        memory_total = values.get("MemTotal")
        memory_available = values.get("MemAvailable")
    except (OSError, ValueError):
        pass
    cpu_count = os.cpu_count() or 1
    return {
        "platform": platform.platform(),
        "cpu_count": cpu_count,
        "memory_total_bytes": memory_total,
        "memory_available_bytes": memory_available,
    }


def recommendation(info: dict, model_size_bytes: int | None = None) -> dict:
    available = info.get("memory_available_bytes") or 0
    available_gb = available / 1024**3
    if available_gb < 2.5:
        workers = 1
    elif available_gb < 5.5:
        workers = 2
    elif available_gb < 10:
        workers = 3
    else:
        workers = 4
    workers = min(workers, info.get("cpu_count") or 1, 4)
    timeout_seconds = 300 if available_gb < 5.5 else 180
    warnings = []
    if available_gb < 2.5:
        warnings.append("Свободной оперативной памяти мало: выбран один поток, чтобы не уйти в swap.")
    if model_size_bytes and available and model_size_bytes > available * 0.7:
        workers = 1
        warnings.append("Размер модели близок к доступной памяти: параллельная обработка отключена.")

    # Модель не помещается даже в ВЕСЬ объём RAM компьютера (не только в
    # доступный сейчас остаток) — это не "медленнее", а постоянное
    # свопирование при каждом запросе, независимо от числа потоков и
    # свободной памяти в моменте. Именно этот сценарий стоял за жалобой
    # "6 из 179 файлов за 10 минут" на слабой машине: сам локальный раннер
    # (Ollama) не откажет сразу, а будет отвечать на порядок медленнее.
    # workers=1 здесь уже ничего не спасает — единственный выход снаружи
    # это UI: выбрать модель поменьше или облачного провайдера (vsegpt.ru).
    total = info.get("memory_total_bytes") or 0
    if model_size_bytes and total and model_size_bytes > total * 0.85:
        timeout_seconds = 600
        warnings.append(
            "Выбранная модель весит "
            f"{model_size_bytes / 1024**3:.1f} ГБ — больше, чем есть RAM на этом компьютере "
            f"({total / 1024**3:.1f} ГБ) даже без учёта остальных программ. Обработка будет "
            "в разы медленнее из-за постоянного свопирования, а не быстрее с новыми настройками. "
            "Выберите модель меньшего размера (например, 7B вместо 14B) в Администрирование → "
            "LLM-модель, либо облачного провайдера (vsegpt.ru)."
        )

    return {
        "workers": max(1, workers),
        "timeout_seconds": timeout_seconds,
        "reason": f"Доступно RAM: {available_gb:.1f} ГБ; CPU: {info.get('cpu_count')}",
        "warnings": warnings,
    }


def fit_for_model(info: dict, size_bytes: int | None) -> dict:
    """Вердикт "поместится ли" для ЛЮБОЙ модели из списка — до того, как её
    выбрали (см. Администрирование → LLM-модель/Справка по моделям). Не
    путать с recommendation(): та считает workers/timeout только для уже
    ВЫБРАННОЙ модели, здесь же переиспользуются те же самые пороги 0.7/0.85,
    чтобы не заводить вторую, чуть другую политику "помещается/не помещается".

    Возвращает {"status": "comfortable"|"tight"|"too_big"|"unknown", "note": str|None}.
    """
    if not size_bytes:
        return {"status": "unknown", "note": None}

    total = info.get("memory_total_bytes") or 0
    if total and size_bytes > total * 0.85:
        return {
            "status": "too_big",
            "note": (
                f"Весит {size_bytes / 1024**3:.1f} ГБ — больше, чем есть RAM на этом "
                f"компьютере ({total / 1024**3:.1f} ГБ) даже без учёта остальных "
                "программ. Скорее всего будет работать в разы медленнее из-за "
                "постоянного свопирования."
            ),
        }

    available = info.get("memory_available_bytes") or 0
    if available and size_bytes > available * 0.7:
        return {
            "status": "tight",
            "note": (
                f"Весит {size_bytes / 1024**3:.1f} ГБ — близко к тому, сколько сейчас "
                f"свободно ({available / 1024**3:.1f} ГБ). Может быть медленно, "
                "особенно вместе с другими запущенными программами."
            ),
        }

    return {"status": "comfortable", "note": None}


def effective_settings() -> dict:
    manual = _read_manual()
    info = system_info()
    model_size = None
    selected_model = None
    try:
        from app.services.llm_settings import get_selection

        selection = get_selection()
        selected_model = selection.model_name if selection else None
        if selection and selection.provider == "ollama":
            from app.services.llm_client import LLMClient

            discovery = LLMClient(current_app.config["LLM_SERVICE_URL"]).list_models()
            for model in discovery.get("providers", {}).get("ollama", {}).get("models", []):
                if model.get("name") == selection.model_name:
                    model_size = model.get("size")
                    break
    except Exception:
        pass
    recommended = recommendation(info, model_size)
    result = _compose_effective(manual, info, recommended, model_size)
    result["selected_model"] = selected_model
    return result


def _compose_effective(manual: dict, info: dict, recommended: dict, model_size: int | None) -> dict:
    if manual["mode"] == "manual":
        workers = max(1, min(int(manual.get("workers") or recommended["workers"]), 4))
        timeout = max(30, min(int(manual.get("timeout_seconds") or recommended["timeout_seconds"]), 600))
    else:
        workers = recommended["workers"]
        timeout = recommended["timeout_seconds"]
    from app.services.parallel import cpu_only_suspected

    return {
        "settings": {"mode": manual["mode"], "workers": workers, "timeout_seconds": timeout},
        "system": info,
        "recommendation": recommended,
        "model_size_bytes": model_size,
        "cpu_only_suspected": cpu_only_suspected(),
    }


def runtime_settings() -> dict:
    """Быстрые лимиты для каждого LLM-вызова, без сетевого discovery."""
    info = system_info()
    recommended = recommendation(info)
    return _compose_effective(_read_manual(), info, recommended, None)
