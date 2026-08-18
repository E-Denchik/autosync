"""Генерирует backend/app/_baked_integration_keys.py из переменных
окружения (в CI — подставленных из GitHub Secrets, см.
.github/workflows/build-native.yml) — эти значения PyInstaller вошьёт
прямо в сборку, и приложение подставит их в БД заказчика при самом первом
запуске (см. app/services/settings_store.py: seed_baked_defaults), если
заказчик их ещё не менял через UI сам.

Файл всегда перезаписывается (в т.ч. пустым словарём, если ни один секрет
не задан) — это ожидаемо для локальных сборок без доступа к секретам
репозитория. Сам файл в .gitignore, в git никогда не попадает.

Запускать из корня проекта: python3 scripts/bake_integration_keys.py
"""

from __future__ import annotations

import os

KEYS = [
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "OZON_PERFORMANCE_CLIENT_ID",
    "OZON_PERFORMANCE_CLIENT_SECRET",
]

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "backend", "app", "_baked_integration_keys.py"
)


def main() -> None:
    values = {key: os.environ[key] for key in KEYS if os.environ.get(key)}
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(f"BAKED_INTEGRATION_KEYS = {values!r}\n")
    print(f"Baked {len(values)} key(s) into {OUTPUT_PATH}: {sorted(values)}")


if __name__ == "__main__":
    main()
