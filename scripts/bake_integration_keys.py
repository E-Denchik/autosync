"""Генерирует backend/app/_baked_integration_keys.json из переменных
окружения (в CI — подставленных из GitHub Secrets, см.
.github/workflows/build-native.yml) — build-native-linux.sh/
build-native-windows.ps1 бьют этот файл в сборку через --add-data (как
migrations/icon/frontend_dist — данные, не код), а не через python-импорт:
PyInstaller не гарантированно находит динамический
`from app._baked_integration_keys import ...` внутри try/except при
статическом анализе графа импортов, и ключи молча не попадали в сборку.
Приложение читает файл как обычный bundled-ресурс при самом первом запуске
(см. app/services/settings_store.py: seed_baked_defaults), если заказчик
их ещё не менял через UI сам.

Файл всегда перезаписывается (в т.ч. пустым объектом, если ни один секрет
не задан) — это ожидаемо для локальных сборок без доступа к секретам
репозитория, и делает --add-data безопасным (источник всегда существует).
Сам файл в .gitignore, в git никогда не попадает.

Запускать из корня проекта: python scripts/bake_integration_keys.py
"""

from __future__ import annotations

import json
import os

KEYS = [
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "OZON_PERFORMANCE_CLIENT_ID",
    "OZON_PERFORMANCE_CLIENT_SECRET",
]

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "backend", "app", "_baked_integration_keys.json"
)


def main() -> None:
    values = {key: os.environ[key] for key in KEYS if os.environ.get(key)}
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(values, f)
    print(f"Baked {len(values)} key(s) into {OUTPUT_PATH}: {sorted(values)}")


if __name__ == "__main__":
    main()
