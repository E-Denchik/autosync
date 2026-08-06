#!/usr/bin/env bash
# Собирает AutoSync в один исполняемый файл для Linux (PyInstaller) —
# "обычное приложение", без Docker: SQLite + встроенный планировщик,
# см. backend/native_app.py и backend/app/config.py (NativeConfig).
#
# ВАЖНО: PyInstaller не кросс-компилирует — бинарник, собранный этим
# скриптом, работает только на Linux. Для Windows нужен отдельный запуск
# на Windows-машине (packaging/native/build-native-windows.ps1) или сборка
# в CI (.github/workflows/build-native.yml).
#
# Запускать из корня проекта: ./scripts/build-native-linux.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -d "$REPO_ROOT/backend" ]; then
  echo "Ошибка: запускать из корня проекта autosync (не найден backend/)." >&2
  exit 1
fi

echo "==> Собираю frontend"
(cd "$REPO_ROOT/frontend" && npm install --silent && npm run build --silent)

echo "==> Готовлю Python-окружение для сборки (backend/.venv-native)"
VENV_DIR="$REPO_ROOT/backend/.venv-native"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$REPO_ROOT/backend/requirements-native.txt"

echo "==> Запускаю PyInstaller"
BUILD_WORK="$REPO_ROOT/build/native-linux"
OUT_DIR="$REPO_ROOT/dist/native-linux"
rm -rf "$BUILD_WORK" "$OUT_DIR"
mkdir -p "$BUILD_WORK" "$OUT_DIR"

cd "$REPO_ROOT/backend"
pyinstaller \
  --name autosync \
  --onefile \
  --noconfirm \
  --distpath "$OUT_DIR" \
  --workpath "$BUILD_WORK/work" \
  --specpath "$BUILD_WORK" \
  --add-data "$REPO_ROOT/frontend/dist:frontend_dist" \
  --add-data "$REPO_ROOT/llm-service:llm_service_src" \
  --add-data "$REPO_ROOT/backend/migrations:migrations" \
  --hidden-import=waitress \
  --hidden-import=apscheduler.schedulers.background \
  --collect-submodules apscheduler \
  --hidden-import=logging.config \
  --collect-all numpy \
  --collect-all pandas \
  native_app.py

deactivate

echo ""
echo "==> Готово: $OUT_DIR/autosync"
echo "    Запуск: $OUT_DIR/autosync  (откроет браузер на http://127.0.0.1:5000/)"
