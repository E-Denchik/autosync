"""Настройки LLM: какую скачанную модель (Ollama или LM Studio) использовать
для предложений по цене, генерации карточек и LLM-фоллбэка сопоставления.

Только администратор — это системная настройка, влияющая на все модули
(см. app/api/auth.py — тот же admin_required-паттерн для /users)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.auth import admin_required
from app.services import llm_settings
from app.services.llm_client import LLMClient, LLMClientError

bp = Blueprint("llm", __name__)
bp.before_request(admin_required(lambda: None))


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

    llm_settings.set_selection(provider, model_name)
    return jsonify(provider=provider, model=model_name)
