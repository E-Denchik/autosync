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
# Именно /usr/bin/python3, а не просто "python3" из PATH: apt (python3-gi
# ниже) ставит биндинги ТОЛЬКО для системного Python по этому пути. Если в
# PATH перед ним стоит другой Python (например, actions/setup-python в CI —
# он ставит СВОЙ отдельный Python в /opt/hostedtoolcache и подставляет его
# первым в PATH; локально то же самое сделал бы pyenv/conda), --system-site-
# packages унаследует site-packages ЭТОГО чужого Python, где gi нет и не
# будет — PyInstaller потом молча соберёт бинарник без gi ("skipping data
# collection for module 'gi' as it is not a package"), а упадёт это только
# на этапе selftest в конце сборки (или вовсе у пользователя). Воспроизведено
# и исправлено: сборка в GitHub Actions падала именно так, хотя тот же
# скрипт локально (без setup-python) работал.
SYSTEM_PYTHON3="/usr/bin/python3"
if [ ! -x "$SYSTEM_PYTHON3" ]; then
  echo "    /usr/bin/python3 не найден — использую python3 из PATH (может не совпадать с тем, для кого apt поставил python3-gi)"
  SYSTEM_PYTHON3="python3"
fi
if [ ! -d "$VENV_DIR" ]; then
  # --system-site-packages: окно приложения (pywebview) на Linux использует
  # WebKitGTK через PyGObject (модуль gi) — тот ставится системным пакетным
  # менеджером (python3-gi), а не pip, и его нужно унаследовать из системного
  # Python. Без system-python3-gi/gir1.2-webkit2-4.1 (или 4.0) установленных
  # через apt сборка всё равно пройдёт, но окно на этой машине не откроется.
  "$SYSTEM_PYTHON3" -m venv --system-site-packages "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python3 -m pip install -q --upgrade pip
python3 -m pip install -q -r "$REPO_ROOT/backend/requirements.txt"

echo "==> Проверяю, что модуль gi (GTK-биндинги) виден из venv"
# Быстрая проверка ДО ~2-минутной сборки PyInstaller — если venv-python
# создан не от того системного Python (см. комментарий выше), gi будет
# недоступен уже здесь, и лучше узнать об этом сразу с понятной причиной,
# а не после долгой сборки через selftest в конце этого скрипта.
if ! python3 -c "import gi" 2>/tmp/gi-import-error.log; then
  echo "" >&2
  echo "ОШИБКА: модуль gi не импортируется из backend/.venv-native — venv, похоже," >&2
  echo "создан не от системного Python (/usr/bin/python3), для которого apt" >&2
  echo "поставил python3-gi. Обычно помогает: rm -rf backend/.venv-native и" >&2
  echo "пересборка — сейчас использован: $SYSTEM_PYTHON3" >&2
  cat /tmp/gi-import-error.log >&2
  rm -f /tmp/gi-import-error.log
  exit 1
fi
rm -f /tmp/gi-import-error.log

echo "==> Записываю commit сборки (для проверки обновлений)"
python3 "$REPO_ROOT/scripts/write_build_info.py"

echo "==> Запускаю PyInstaller"
BUILD_WORK="$REPO_ROOT/build/native-linux"
OUT_DIR="$REPO_ROOT/dist/native-linux"
rm -rf "$BUILD_WORK" "$OUT_DIR"
mkdir -p "$BUILD_WORK" "$OUT_DIR"

# --hidden-import=app.services.builtin_brand_aliases ниже: этот модуль
# нигде в app/ не импортируется обычным import'ом (только миграцией
# b7e3a9c5d1f8_add_brand_aliases_table.py и тестами) — без явного
# hidden-import PyInstaller не находит его транзитивным анализом и не
# включает в архив, а FileNotFoundError, к которому это приводит, если
# миграция вдобавок пытается грузить его по относительному пути к файлу
# (а не обычным import), см. саму миграцию.
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
  --add-data "$REPO_ROOT/backend/app/_build_info.json:app" \
  --hidden-import=waitress \
  --hidden-import=apscheduler.schedulers.background \
  --collect-submodules apscheduler \
  --hidden-import=logging.config \
  --hidden-import=pytesseract \
  --hidden-import=app.services.builtin_brand_aliases \
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

echo "==> Проверяю, что в сборке действительно есть рабочий GUI-бэкенд (gi/WebKit2)"
# Ловит именно тот класс багов, что уже случался локально: PyInstaller
# "успешно" собирает бинарник (--collect-all gi отрабатывает без ошибок),
# но модуль gi в итоге в архив не попадает, и окно на старте падает с
# ModuleNotFoundError уже у пользователя — при этом при перезапуске после
# обновления этот вывод никуда не показывается (см. update_checker.py),
# так что молчаливо собранный битый бинарник — самый опасный вариант.
# AUTOSYNC_SELFTEST_GUI лишь импортирует GTK-биндинги (см. native_app.py:
# _selftest_gui) — к дисплею не подключается, поэтому не требует Xvfb.
if ! AUTOSYNC_SELFTEST_GUI=1 timeout 15 "$OUT_DIR/autosync"; then
  echo "" >&2
  echo "ОШИБКА: собранный бинарник не может загрузить GTK/WebKit — см. вывод выше." >&2
  echo "Обычно помогает пересборка (rm -rf backend/.venv-native и заново)." >&2
  exit 1
fi

echo ""
echo "==> Готово: $OUT_DIR/autosync"
echo "    Запуск: $OUT_DIR/autosync  (откроет своё окно, backend на http://127.0.0.1:5000/)"
echo "    Нужны системные пакеты: python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 (или -4.0)"
