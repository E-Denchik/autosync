"""Тонкая обёртка над Ollama, отдаёт единый /generate эндпоинт.

Оба модуля backend (llm_client.py) обращаются сюда по HTTP, а не к Ollama
напрямую — модель или хост можно заменить, не трогая backend
(см. ARCHITECTURE.md: «LLM как отдельный сервис»).
"""

from __future__ import annotations

import os

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "qwen2.5:14b")


@app.get("/health")
def health():
    return jsonify(status="ok", model=MODEL_NAME)


@app.post("/generate")
def generate():
    body = request.get_json(force=True) or {}
    prompt = body.get("prompt")
    if not prompt:
        return jsonify(error="'prompt' обязателен"), 400

    json_response = bool(body.get("json_response", False))

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if json_response:
        payload["format"] = "json"

    resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=180)
    if not resp.ok:
        return jsonify(error=f"ollama -> {resp.status_code}: {resp.text}"), 502

    data = resp.json()
    return jsonify(text=data.get("response", ""))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
