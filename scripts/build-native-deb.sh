#!/usr/bin/env bash
# Собирает AutoSync в .deb как обычное desktop-приложение — БЕЗ Docker,
# БЕЗ debconf-диалогов: один бинарник (PyInstaller) + .desktop-ярлык.
# Открывается в собственном окне (pywebview), первый запуск настраивается
# прямо там (мастер /setup), не в консоли.
#
# Запускать из корня проекта: ./scripts/build-native-deb.sh
# (сначала соберёт бинарник через build-native-linux.sh, если его ещё нет)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BINARY="$REPO_ROOT/dist/native-linux/autosync"
if [ ! -f "$BINARY" ]; then
  echo "==> Бинарник не найден, собираю через build-native-linux.sh"
  "$SCRIPT_DIR/build-native-linux.sh"
fi

for tool in dpkg-deb; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Ошибка: требуется '$tool', но он не установлен." >&2
    exit 1
  fi
done

VERSION="$(tr -d ' \t\n\r' < "$REPO_ROOT/VERSION")"
PKG_NAME="autosync-desktop"
ARCH="amd64"

echo "==> Сборка ${PKG_NAME} v${VERSION} (${ARCH})"

STAGE="$REPO_ROOT/build/native-deb/${PKG_NAME}_${VERSION}_${ARCH}"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/autosync" "$STAGE/usr/share/applications"

cp "$BINARY" "$STAGE/opt/autosync/autosync"
cp "$REPO_ROOT/packaging/native-deb/icon.png" "$STAGE/opt/autosync/icon.png"
cp "$REPO_ROOT/packaging/native-deb/autosync.desktop" "$STAGE/usr/share/applications/autosync.desktop"

cp "$REPO_ROOT/packaging/native-deb/postinst" "$STAGE/DEBIAN/postinst"
cp "$REPO_ROOT/packaging/native-deb/postrm" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

INSTALLED_SIZE_KB="$(du -sk "$STAGE/opt" | cut -f1)"
sed \
  -e "s/__VERSION__/${VERSION}/" \
  -e "s/__INSTALLED_SIZE__/${INSTALLED_SIZE_KB}/" \
  "$REPO_ROOT/packaging/native-deb/control" > "$STAGE/DEBIAN/control"

mkdir -p "$REPO_ROOT/dist"
OUTPUT="$REPO_ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUTPUT" >/dev/null

echo ""
echo "==> Готово: $OUTPUT"
dpkg-deb --info "$OUTPUT" | sed 's/^/    /'
echo ""
echo "Установка: sudo dpkg -i $(basename "$OUTPUT")"
echo "Запуск: из меню приложений («AutoSync») или /opt/autosync/autosync"
