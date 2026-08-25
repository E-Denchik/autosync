"""Тонкая обёртка над локальными LLM-раннерами, отдаёт единые /models и
/generate эндпоинты.

Backend (llm_client.py) обращается сюда по HTTP, а не к Ollama/LM Studio
напрямую — раннер или модель можно заменить, не трогая backend
(см. ARCHITECTURE.md: «LLM как отдельный сервис»).

Поддержаны два раннера, которые пользователь может держать на своей машине
одновременно:
  - Ollama          — HTTP API на OLLAMA_BASE_URL (по умолчанию localhost:11434)
  - LM Studio       — Local Server (OpenAI-совместимый) на LMSTUDIO_BASE_URL
                       (по умолчанию localhost:1234/v1)

Какую из скачанных моделей реально использовать — решает администратор в
UI (Настройки → LLM), backend хранит выбор в БД и передаёт provider+model
с каждым запросом сюда (см. app/services/llm_settings.py). Если backend
их не передал (прямой curl, обратная совместимость) — используются
переменные окружения LLM_PROVIDER/LLM_MODEL_NAME как раньше.
"""

from __future__ import annotations

import glob
import os

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")
DEFAULT_MODEL = os.environ.get("LLM_MODEL_NAME", "qwen2.5:14b")

# LM Studio хранит скачанные .gguf либо в новом расположении (~/.lmstudio),
# либо в старом (~/.cache/lm-studio) — на разных версиях приложения.
LMSTUDIO_MODEL_DIRS = [
    os.path.expanduser("~/.lmstudio/models"),
    os.path.expanduser("~/.cache/lm-studio/models"),
]


def discover_ollama() -> dict:
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        resp.raise_for_status()
    except requests.RequestException:
        return {"available": False, "models": []}

    models = [
        {"name": m["name"], "size": m.get("size"), "modified_at": m.get("modified_at")}
        for m in resp.json().get("models", [])
    ]
    return {"available": True, "models": models}


def _scan_lmstudio_filesystem() -> list[str]:
    """Best-effort скан каталогов LM Studio на диске — находит модели, даже
    если Local Server сейчас выключен (пользователь просто не открыл
    приложение). Идентификатор модели — путь относительно каталога models
    без расширения .gguf, ровно так LM Studio называет модели в своём API."""
    found: set[str] = set()
    for root in LMSTUDIO_MODEL_DIRS:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*.gguf"), recursive=True):
            rel = os.path.relpath(path, root)
            found.add(rel[: -len(".gguf")] if rel.endswith(".gguf") else rel)
    return sorted(found)


def discover_lmstudio() -> dict:
    try:
        resp = requests.get(f"{LMSTUDIO_BASE_URL}/models", timeout=3)
        resp.raise_for_status()
        names = [m["id"] for m in resp.json().get("data", [])]
        return {"available": True, "server_running": True, "models": [{"name": n} for n in names]}
    except requests.RequestException:
        pass

    # Local Server выключен — покажем то, что найдено на диске, но пометим
    # как недоступное для генерации прямо сейчас (нужно включить сервер в
    # приложении LM Studio).
    names = _scan_lmstudio_filesystem()
    return {"available": bool(names), "server_running": False, "models": [{"name": n} for n in names]}


@app.get("/health")
def health():
    return jsonify(status="ok", provider=DEFAULT_PROVIDER, model=DEFAULT_MODEL)


@app.get("/models")
def models():
    """Что реально стоит на этой машине — для UI выбора модели админом."""
    return jsonify(
        providers={
            "ollama": discover_ollama(),
            "lmstudio": discover_lmstudio(),
        }
    )


def _generate_ollama(model: str, prompt: str, json_response: bool) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if json_response:
        payload["format"] = "json"

    resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=180)
    if not resp.ok:
        raise RuntimeError(f"ollama -> {resp.status_code}: {resp.text}")
    return resp.json().get("response", "")


def _generate_lmstudio(model: str, prompt: str, json_response: bool) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if json_response:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(f"{LMSTUDIO_BASE_URL}/chat/completions", json=payload, timeout=180)
    if not resp.ok:
        raise RuntimeError(f"lmstudio -> {resp.status_code}: {resp.text}")
    return resp.json()["choices"][0]["message"]["content"]


@app.post("/generate")
def generate():
    body = request.get_json(force=True) or {}
    prompt = body.get("prompt")
    if not prompt:
        return jsonify(error="'prompt' обязателен"), 400

    json_response = bool(body.get("json_response", False))
    provider = body.get("provider") or DEFAULT_PROVIDER
    model = body.get("model") or DEFAULT_MODEL

    try:
        if provider == "lmstudio":
            text = _generate_lmstudio(model, prompt, json_response)
        else:
            text = _generate_ollama(model, prompt, json_response)
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 502
    except requests.exceptions.RequestException as exc:
        # Таймаут/обрыв соединения к Ollama/LM Studio (модель ещё грузится в
        # память на первом запросе после простоя, раннер занят другим
        # запросом и т.п.) — не RuntimeError, поэтому раньше пролетало мимо
        # except выше и падало как НЕПОЙМАННОЕ исключение: Flask отдавал
        # голую стандартную страницу 500 без единого объяснения причины, а
        # backend (llm_client.py) эту страницу видел как "llm-service -> 500:
        # The server encountered an internal error..." и ретраи для нём не
        # делал (ретраит только полную недоступность llm-service, а тут
        # llm-service отвечает нормально — это раннер внутри подвёл).
        # Теперь это понятная ошибка с 502, которую backend вдобавок
        # ретраит (см. LLMClient._generate).
        return jsonify(error=f"{provider} не ответил вовремя: {exc}"), 502
    except (ValueError, KeyError, IndexError) as exc:
        # resp.json() / ["choices"][0]["message"]["content"] — раннер
        # ответил 200, но с телом не той формы, которую мы ожидаем (другая
        # версия API, пустой ответ и т.п.). Тоже не RuntimeError — та же
        # история с голой страницей 500 без объяснения.
        return jsonify(error=f"{provider} вернул неожиданный ответ: {exc}"), 502

    return jsonify(text=text)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
