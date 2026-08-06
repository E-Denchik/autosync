"""Загрузка и рендер промптов из llm-service/prompts/ (общие для backend и llm-service)."""

from __future__ import annotations

import json
import os

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "llm-service", "prompts")


def render_prompt(name: str, **context) -> str:
    path = os.path.join(_PROMPTS_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()
    context_json = json.dumps(context, ensure_ascii=False, indent=2, default=str)
    return template.replace("{{CONTEXT_JSON}}", context_json)
