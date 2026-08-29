"""Настройки LLM: какую скачанную модель (Ollama или LM Studio) использовать
для предложений по цене, генерации карточек и LLM-фоллбэка сопоставления."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.services import llm_settings
from app.services.history import log_change
from app.services.llm_client import LLMClient, LLMClientError

bp = Blueprint("llm", __name__)


def _client() -> LLMClient:
    return LLMClient(current_app.config["LLM_SERVICE_URL"])


@bp.get("/models")
def list_models():
    """Discovery всех моделей, скачанных на этой машине (Ollama + LM Studio),
    плюс текущий выбор администратора. Если ранее выбранная модель больше не
    видна в discovery (удалена с диска) — выбор автоматически сбрасывается,
    а фронту возвращается previous_selection, чтобы объяснить, что произошло."""
    try:
        discovery = _client().list_models()
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

    return jsonify(providers=discovery["providers"], selected=selected, previous_selection=previous_selection)


@bp.post("/select")
def select_model():
    body = request.get_json(force=True) or {}
    provider = body.get("provider")
    model_name = body.get("model")

    if provider not in ("ollama", "lmstudio") or not model_name:
        return jsonify(error="'provider' ('ollama'|'lmstudio') и 'model' обязательны"), 400

    try:
        discovery = _client().list_models()
    except LLMClientError as exc:
        return jsonify(error=f"llm-service недоступен: {exc}"), 502

    if not llm_settings.is_known_model(discovery, provider, model_name):
        return jsonify(error="Эта модель не найдена среди скачанных — обновите список и попробуйте снова"), 404

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
