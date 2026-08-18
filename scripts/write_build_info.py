"""Генерирует backend/app/_build_info.json с commit SHA, из которого собран
этот бинарник — тем же способом, что и bake_integration_keys.py (данные,
вшиваемые в сборку через --add-data, см. build-native-linux.sh/
build-native-windows.ps1), не Python-модуль и не git-команда в рантайме
(в frozen-бинарнике репозитория рядом нет).

Проверка обновлений (app/services/update_checker.py) сравнивает этот commit
с тем, на который сейчас указывает тег `latest` на GitHub — расхождение
означает, что вышла новая сборка.

Источник SHA: GITHUB_SHA (задан GitHub Actions автоматически) — если его
нет (сборка не в CI), берём HEAD текущего репозитория через git; если и
это не выйдет (например, git не установлен) — "unknown", тогда проверка
обновлений просто ничего не найдёт вместо падения.

Запускать из корня проекта: python scripts/write_build_info.py
"""

from __future__ import annotations

import json
import os
import subprocess

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "backend", "app", "_build_info.json"
)


def _current_commit() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    commit = _current_commit()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"commit": commit}, f)
    print(f"Записан commit сборки в {OUTPUT_PATH}: {commit}")


if __name__ == "__main__":
    main()
