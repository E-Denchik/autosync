#!/usr/bin/env bash
# Собирает AutoSync в .deb-пакет. Запускать из корня проекта:
#   ./scripts/build-deb.sh
#
# Пакет НЕ содержит собранных Docker-образов — он разворачивает исходники
# (backend/, frontend/, llm-service/, docker-compose.yml) в каталог,
# который пользователь выбирает при `dpkg -i` (через debconf), и сам
# запускает `docker compose up -d --build` при установке. См.
# packaging/deb/postinst — там же создание первого администратора и
# systemd-юнит для автозапуска после перезагрузки.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SKIP_VERIFY=0
for arg in "$@"; do
  case "$arg" in
    --skip-verify) SKIP_VERIFY=1 ;;
    --help|-h)
      echo "Usage: $0 [--skip-verify]"
      echo "  --skip-verify   пропустить прогон backend-тестов перед сборкой"
      exit 0
      ;;
  esac
done

if [ ! -f "$REPO_ROOT/docker-compose.yml" ] || [ ! -d "$REPO_ROOT/backend" ]; then
  echo "Ошибка: запускать из корня проекта autosync (не найден docker-compose.yml/backend/)." >&2
  exit 1
fi

for tool in dpkg-deb rsync; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Ошибка: требуется '$tool', но он не установлен." >&2
    exit 1
  fi
done

VERSION="$(tr -d ' \t\n\r' < "$REPO_ROOT/VERSION")"
ARCH="all"
PKG_NAME="autosync"

echo "==> Сборка ${PKG_NAME} v${VERSION}"

if [ "$SKIP_VERIFY" -eq 0 ] && [ -d "$REPO_ROOT/backend/.venv" ]; then
  echo "==> Прогоняю backend-тесты перед упаковкой (--skip-verify чтобы пропустить)"
  (
    cd "$REPO_ROOT/backend"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    python -m pytest tests/ -q
  )
fi

BUILD_DIR="$REPO_ROOT/build/deb"
STAGE="$BUILD_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/share/autosync/dist"

echo "==> Копирую исходники приложения"
copy_source() {
  local name="$1"
  rsync -a \
    --exclude='.venv/' \
    --exclude='node_modules/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='dist/' \
    --exclude='npm-cache/' \
    --exclude='.env' \
    --exclude='uploads/' \
    --exclude='.git/' \
    "$REPO_ROOT/$name" "$STAGE/usr/share/autosync/dist/"
}

copy_source backend
copy_source frontend
copy_source llm-service
cp "$REPO_ROOT/docker-compose.yml" "$STAGE/usr/share/autosync/dist/"
cp "$REPO_ROOT/.env.example" "$STAGE/usr/share/autosync/dist/"
cp "$REPO_ROOT/VERSION" "$STAGE/usr/share/autosync/dist/"
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$STAGE/usr/share/autosync/dist/"

cp "$REPO_ROOT/packaging/deb/autosync.service.template" "$STAGE/usr/share/autosync/autosync.service.template"

echo "==> Пишу управляющие файлы пакета (DEBIAN/*)"
cp "$REPO_ROOT/packaging/deb/postinst" "$STAGE/DEBIAN/postinst"
cp "$REPO_ROOT/packaging/deb/postrm" "$STAGE/DEBIAN/postrm"
cp "$REPO_ROOT/packaging/deb/config" "$STAGE/DEBIAN/config"
cp "$REPO_ROOT/packaging/deb/templates" "$STAGE/DEBIAN/templates"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm" "$STAGE/DEBIAN/config"

INSTALLED_SIZE_KB="$(du -sk "$STAGE/usr" | cut -f1)"
sed \
  -e "s/__VERSION__/${VERSION}/" \
  -e "s/__INSTALLED_SIZE__/${INSTALLED_SIZE_KB}/" \
  "$REPO_ROOT/packaging/deb/control" > "$STAGE/DEBIAN/control"

echo "==> Собираю .deb"
mkdir -p "$REPO_ROOT/dist"
OUTPUT="$REPO_ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT" >/dev/null

echo ""
echo "==> Готово: $OUTPUT"
dpkg-deb --info "$OUTPUT" | sed 's/^/    /'
echo ""
echo "Установка на целевой машине:"
echo "  sudo dpkg -i $(basename "$OUTPUT")"
echo "  (при отсутствии зависимостей: sudo apt-get install -f)"
