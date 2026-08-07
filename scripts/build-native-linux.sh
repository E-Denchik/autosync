#!/usr/bin/env bash
# Собирает AutoSync в один исполняемый файл для Linux (PyInstaller) —
# "обычное приложение", без Docker: SQLite + встроенный планировщик,
# см. backend/native_app.py и backend/app/config.py.
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
# VITE_API_BASE_URL=/api (относительный, не абсолютный) — фронт и backend
# это один и тот же процесс/origin (окно pywebview на 127.0.0.1), поэтому
# относительный путь резолвится webview против текущего origin сам, без
# нужды знать порт заранее.
(cd "$REPO_ROOT/frontend" && npm install --silent && VITE_API_BASE_URL=/api npm run build --silent)

echo "==> Готовлю Python-окружение для сборки (backend/.venv-native)"
VENV_DIR="$REPO_ROOT/backend/.venv-native"
if [ ! -d "$VENV_DIR" ]; then
  # --system-site-packages: окно приложения (pywebview) на Linux использует
  # WebKitGTK через PyGObject (модуль gi) — тот ставится системным пакетным
  # менеджером (python3-gi), а не pip, и его нужно унаследовать из системного
  # Python. Без system-python3-gi/gir1.2-webkit2-4.1 (или 4.0) установленных
  # через apt сборка всё равно пройдёт, но окно на этой машине не откроется.
  python3 -m venv --system-site-packages "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$REPO_ROOT/backend/requirements.txt"

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
  --add-data "$REPO_ROOT/packaging/icon:icon" \
  --hidden-import=waitress \
  --hidden-import=apscheduler.schedulers.background \
  --collect-submodules apscheduler \
  --hidden-import=logging.config \
  --collect-all numpy \
  --collect-all pandas \
  --collect-all gi \
  --exclude-module PyQt5 \
  --exclude-module PySide2 \
  --exclude-module PySide6 \
  --exclude-module django \
  --exclude-module scipy \
  --exclude-module matplotlib \
  native_app.py
# ^ Явные исключения нужны из-за --system-site-packages (см. выше): venv
# видит ВСЁ, что стоит в системном Python на машине сборки, а на некоторых
# машинах (замечено на Kali) там оказываются Django/PyQt5/scipy/matplotlib
# от совершенно других инструментов — PyInstaller их честно подхватывает по
# графу импортов (в основном через необязательные хуки pandas/SQLAlchemy) и
# раздувает бинарник на сотни мегабайт, хотя AutoSync их не использует.

deactivate

echo ""
echo "==> Готово: $OUT_DIR/autosync"
echo "    Запуск: $OUT_DIR/autosync  (откроет своё окно, backend на http://127.0.0.1:5000/)"
echo "    Нужны системные пакеты: python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 (или -4.0)"
