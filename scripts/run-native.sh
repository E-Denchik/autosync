#!/usr/bin/env bash
# Запускает AutoSync как обычное приложение — без Docker, в собственном
# окне (см. backend/native_app.py). Если бинарник ещё не собран, либо
# исходники (backend/, frontend/src, llm-service/) новее уже собранного
# бинарника — сначала пересобирает через build-native-linux.sh (пару минут).
#
# Запускать из корня проекта: ./scripts/run-native.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BINARY="$REPO_ROOT/dist/native-linux/autosync"

needs_build=0
if [ ! -f "$BINARY" ]; then
  needs_build=1
elif find "$REPO_ROOT/backend" "$REPO_ROOT/frontend/src" "$REPO_ROOT/frontend/index.html" "$REPO_ROOT/frontend/public" "$REPO_ROOT/llm-service" "$REPO_ROOT/packaging/icon" \
    \( -name node_modules -o -name '.venv*' -o -name __pycache__ -o -name dist -o -name build \
       -o -name .pytest_cache -o -name tests \) -prune -o \
    -type f -newer "$BINARY" -print -quit 2>/dev/null | grep -q .; then
  needs_build=1
fi

if [ "$needs_build" -eq 1 ]; then
  echo "==> Бинарник не найден или устарел — пересобираю (может занять пару минут)…"
  "$SCRIPT_DIR/build-native-linux.sh"
fi

echo "==> Запускаю AutoSync — откроется окно приложения"
# Собранный бинарник — frozen-приложение, поэтому по умолчанию (см.
# native_app.py: get_data_dir()) использует каталог данных ОС (~/.autosync
# и т.п.) — это верно для реально установленного продукта, но не для
# локального запуска сборки прямо из репозитория: здесь, как и при запуске
# из исходников, БД/загрузки должны оставаться внутри проекта (data/).
export AUTOSYNC_DATA_DIR="${AUTOSYNC_DATA_DIR:-$REPO_ROOT/data}"
exec "$BINARY"
