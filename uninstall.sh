#!/usr/bin/env bash
# Removes zen-ext.
#   ./uninstall.sh          program only; added extensions keep working in Zen
#   ./uninstall.sh --purge  also removes those extensions from Zen and undoes user.js
set -euo pipefail

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA/zen-ext/app"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/zen-ext-watch.service"

if [ "${1:-}" = "--purge" ] && [ -d "$APP_DIR/zen_ext" ]; then
  PYTHONPATH="$APP_DIR" python3 -c '
from zen_ext import core
for p in core.purge():
    print(f"Профиль очищен: {p.name}")'
fi

if [ -f "$UNIT" ]; then
  systemctl --user disable --now zen-ext-watch.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
fi
rm -rf "$APP_DIR"
rm -f "$HOME/.local/bin/zen-ext" "$DATA/applications/zen-ext.desktop" \
      "$DATA/icons/hicolor/scalable/apps/zen-ext.svg"
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
echo "zen-ext удалён. Перезапусти Zen, если использовал --purge."
