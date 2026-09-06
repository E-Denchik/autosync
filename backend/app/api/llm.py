"""Настройки LLM: какую модель использовать для предложений по цене,
генерации карточек и LLM-фоллбэка сопоставления — локально скачанную
(Ollama, LM Studio) или облачную через vsegpt.ru (по API-ключу)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.services import llm_settings
from app.services.history import log_change
from app.services.llm_client import LLMClient, LLMClientError
from app.services.model_capability import capability_for_cloud_model, capability_for_local_model
from app.services.parallel import cpu_only_suspected
from app.services.performance_settings import fit_for_model, system_info

bp = Blueprint("llm", __name__)


def _client() -> LLMClient:
    return LLMClient(current_app.config["LLM_SERVICE_URL"])


@bp.get("/models")
def list_models():
    """Discovery всех LLM-провайдеров: что скачано на этой машине (Ollama +
    LM Studio) плюс облачные модели vsegpt.ru (если ключ уже сохранён через
    Администрирование → Интеграции), плюс текущий выбор администратора. Если
    ранее выбранная модель больше не видна в discovery (удалена с диска,
    либо ключ vsegpt.ru убрали/стал невалиден) — выбор автоматически
    сбрасывается, а фронту возвращается previous_selection, чтобы объяснить,
    что произошло."""
    vsegpt_api_key = current_app.config.get("VSEGPT_API_KEY", "")
    try:
        discovery = _client().list_models(vsegpt_api_key=vsegpt_api_key)
    except LLMClientError as exc:
        return jsonify(error=f"llm-service недоступен: {exc}"), 502

    selection = llm_settings.get_selection()
    selected = None
    previous_selection = None

    if selection is not None:
        if llm_settings.is_known_model(discovery, selection.provider, selection.model_name):
            selected = {"provider": selection.provider, "model": selection.model_name}
        else:
            previous_selection = {"provider": selection.provider, "model": selection.model_name}
            llm_settings.clear_selection()

    # Обогащение списка подсказками про возможности модели и вероятную
    # совместимость с этим компьютером (см. Администрирование → LLM-модель/
    # Справка по моделям) — без единого нового сетевого запроса: _client()
    # выше и так уже сходил в llm-service один раз, всё остальное здесь —
    # локальные вычисления (system_info() читает /proc/meminfo один раз,
    # cpu_only_suspected() — сравнение с уже посчитанным monotonic-таймером).
    info = system_info()
    for provider_name in ("ollama", "lmstudio"):
        provider = discovery["providers"].get(provider_name)
        if not provider:
            continue
        for model in provider.get("models", []):
            model["capability"] = capability_for_local_model(
                parameter_size=model.get("parameter_size"),
                name=model["name"],
                size_bytes=model.get("size"),
            )
            model["fit"] = fit_for_model(info, model.get("size"))

    vsegpt_provider = discovery["providers"].get("vsegpt")
    if vsegpt_provider:
        # Облачные модели: только capability (общий текст про оплату за
        # запрос) — "fit" по RAM для них не имеет смысла вовсе, поэтому
        # ключ намеренно отсутствует, а не равен null (фронт должен читать
        # его отсутствие как "неприменимо", а не "неизвестно").
        for model in vsegpt_provider.get("models", []):
            model["capability"] = capability_for_cloud_model(model["name"])

    return jsonify(
        providers=discovery["providers"],
        selected=selected,
        previous_selection=previous_selection,
        vsegpt_configured=bool(vsegpt_api_key),
        cpu_only_suspected=cpu_only_suspected(),
        system={
            "cpu_count": info.get("cpu_count"),
            "memory_total_bytes": info.get("memory_total_bytes"),
            "memory_available_bytes": info.get("memory_available_bytes"),
        },
    )


@bp.get("/vsegpt/status")
def vsegpt_status():
    try:
        status = _client().vsegpt_status(current_app.config.get("VSEGPT_API_KEY", ""))
    except LLMClientError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(status=status)


@bp.post("/select")
def select_model():
    body = request.get_json(force=True) or {}
    provider = body.get("provider")
    model_name = body.get("model")

    if provider not in ("ollama", "lmstudio", "vsegpt") or not model_name:
        return jsonify(error="'provider' ('ollama'|'lmstudio'|'vsegpt') и 'model' обязательны"), 400

    try:
        discovery = _client().list_models(vsegpt_api_key=current_app.config.get("VSEGPT_API_KEY", ""))
    except LLMClientError as exc:
        return jsonify(error=f"llm-service недоступен: {exc}"), 502

    provider_info = discovery["providers"].get(provider, {})
    if provider == "vsegpt" and provider_info.get("temporarily_unavailable"):
        if provider_info.get("reason") == "non_positive_balance":
            message = "Модели vsegpt.ru временно недоступны: баланс равен нулю или меньше нуля. Пополните счёт и обновите список."
        else:
            message = "Модели vsegpt.ru временно недоступны: баланс не удалось подтвердить. Проверьте ключ и обновите список."
        return jsonify(error=message), 409
    if not llm_settings.is_known_model(discovery, provider, model_name):
        return jsonify(error="Эта модель сейчас недоступна — обновите список и попробуйте снова"), 404

    log_change(
        "llm_model_selection",
        llm_settings.SELECTION_ID,
        "selected",
        details={"provider": provider, "model": model_name},
    )
    llm_settings.set_selection(provider, model_name)
    return jsonify(provider=provider, model=model_name)


@bp.post("/test")
def test_model():
    """Реальный пробный запрос к уже выбранной модели (см.
    LLMClient.test_connection) — в отличие от /models, дожидается ответа
    раннера, а не просто проверяет, что модель есть в списке скачанных.
    Ловит нехватку памяти/сбой раннера ДО того, как пользователь потратит
    время на загрузку и разбор файлов (см. UploadPage.jsx)."""
    try:
        message = _client().test_connection()
    except LLMClientError as exc:
        return jsonify(ok=False, error=str(exc))
    return jsonify(ok=True, message=message)


@bp.post("/repair-instructions")
def repair_instructions():
    """Пошаговая инструкция по выполнению произвольной работы (например,
    "замена колодок") — по запросу оператора со страницы проверки
    заказ-наряда. Не привязано к конкретному заказ-наряду/работе на
    уровне API: и кнопка в строке работы, и отдельное поле для
    произвольного запроса (см. ReviewMatches.jsx) используют один и тот же
    stateless-эндпоинт."""
    body = request.get_json(force=True) or {}
    operation_name = (body.get("operation_name") or "").strip()
    if not operation_name:
        return jsonify(error="'operation_name' обязателен"), 400

    try:
        result = _client().generate_repair_instructions(
            operation_name,
            vehicle_make=body.get("vehicle_make"),
            vehicle_model=body.get("vehicle_model"),
        )
    except LLMClientError as exc:
        return jsonify(error=str(exc)), 502

    return jsonify(steps=result.get("steps") or [], note=result.get("note"))
