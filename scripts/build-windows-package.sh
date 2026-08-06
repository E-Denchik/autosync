#!/usr/bin/env bash
# Собирает дистрибутив AutoSync для Windows: zip-архив с исходниками +
# PowerShell-инсталлятор (packaging/windows/install.ps1) + инструкция.
# Запускать из корня проекта:
#   ./scripts/build-windows-package.sh
#
# В отличие от build-deb.sh, здесь ничего не выполняется на сборочной
# машине специфичного для дистрибутива — просто раскладка файлов + zip,
# поэтому скрипт можно гонять и на Linux/macOS (что и предполагается: сам
# .zip потом переносится и запускается уже на Windows).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f "$REPO_ROOT/docker-compose.yml" ] || [ ! -d "$REPO_ROOT/backend" ]; then
  echo "Ошибка: запускать из корня проекта autosync (не найден docker-compose.yml/backend/)." >&2
  exit 1
fi

for tool in zip rsync; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Ошибка: требуется '$tool', но он не установлен." >&2
    exit 1
  fi
done

VERSION="$(tr -d ' \t\n\r' < "$REPO_ROOT/VERSION")"
PKG_NAME="autosync-windows"

echo "==> Сборка ${PKG_NAME} v${VERSION}"

BUILD_DIR="$REPO_ROOT/build/windows"
STAGE="$BUILD_DIR/${PKG_NAME}_${VERSION}"
rm -rf "$STAGE"
mkdir -p "$STAGE"

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
    "$REPO_ROOT/$name" "$STAGE/"
}

copy_source backend
copy_source frontend
copy_source llm-service
cp "$REPO_ROOT/docker-compose.yml" "$STAGE/"
cp "$REPO_ROOT/.env.example" "$STAGE/"
cp "$REPO_ROOT/VERSION" "$STAGE/"
[ -f "$REPO_ROOT/README.md" ] && cp "$REPO_ROOT/README.md" "$STAGE/"

echo "==> Кладу Windows-инсталлятор"
cp "$REPO_ROOT/packaging/windows/install.ps1" "$STAGE/install.ps1"
cp "$REPO_ROOT/packaging/windows/uninstall.ps1" "$STAGE/uninstall.ps1"
cp "$REPO_ROOT/packaging/windows/README-WINDOWS.md" "$STAGE/README-WINDOWS.md"

# CRLF-переводы строк для .ps1/.md — Notepad и старые редакторы на Windows
# плохо переваривают голые LF. Остальные файлы (Python/JS/YAML/Dockerfile)
# оставляем как есть — их будут читать внутри Linux-контейнеров, где LF ожидаем.
if command -v unix2dos >/dev/null 2>&1; then
  unix2dos --quiet "$STAGE/install.ps1" "$STAGE/uninstall.ps1" "$STAGE/README-WINDOWS.md" 2>/dev/null || true
else
  for f in "$STAGE/install.ps1" "$STAGE/uninstall.ps1" "$STAGE/README-WINDOWS.md"; do
    sed -i 's/$/\r/' "$f"
  done
fi

echo "==> Собираю .zip"
mkdir -p "$REPO_ROOT/dist"
OUTPUT="$REPO_ROOT/dist/${PKG_NAME}_${VERSION}.zip"
rm -f "$OUTPUT"
(cd "$BUILD_DIR" && zip -rq "$OUTPUT" "${PKG_NAME}_${VERSION}")

echo ""
echo "==> Готово: $OUTPUT"
echo "    $(du -h "$OUTPUT" | cut -f1)"
echo ""
echo "Установка на Windows-машине (PowerShell от администратора):"
echo "  Expand-Archive ${PKG_NAME}_${VERSION}.zip"
echo "  cd ${PKG_NAME}_${VERSION}"
echo "  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass"
echo "  .\\install.ps1"
