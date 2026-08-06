"""Загрузка и рендер промптов из llm-service/prompts/ (общие для backend и llm-service)."""

from __future__ import annotations

import json
import os
import sys


def _prompts_dir() -> str:
    if getattr(sys, "frozen", False):
        # PyInstaller: llm-service целиком упакован как data ("llm_service_src",
        # см. scripts/build-native-linux.sh), относительный обход через
        # __file__ здесь не работает — во frozen-сборке это не настоящий путь.
        return os.path.join(sys._MEIPASS, "llm_service_src", "prompts")
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "llm-service", "prompts")


def render_prompt(name: str, **context) -> str:
    path = os.path.join(_prompts_dir(), name)
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()
    context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    return template.replace("{{CONTEXT_JSON}}", context_json)
