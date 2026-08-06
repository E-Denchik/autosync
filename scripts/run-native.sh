#!/usr/bin/env bash
# Запускает AutoSync как обычное приложение — без Docker, в собственном
# окне (см. backend/native_app.py). Если бинарник ещё не собран, сначала
# собирает его через build-native-linux.sh (пару минут на первый раз).
#
# Запускать из корня проекта: ./scripts/run-native.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BINARY="$REPO_ROOT/dist/native-linux/autosync"

if [ ! -f "$BINARY" ]; then
  echo "==> Бинарник не найден, собираю (может занять пару минут)…"
  "$SCRIPT_DIR/build-native-linux.sh"
fi

echo "==> Запускаю AutoSync — откроется окно приложения"
exec "$BINARY"
