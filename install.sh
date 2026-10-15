#!/usr/bin/env bash
# Installs zen-ext for the current user (no root needed):
#   ~/.local/share/zen-ext/app      program files
#   ~/.local/bin/zen-ext            command
#   ~/.local/share/applications     menu entry, also opens .xpi/.crx on double click
#   ~/.config/systemd/user          zen-ext-watch: rebuilds linked source folders
# and prepares Zen's default profile (user.js, see README).
#
#   ./install.sh [--profile PATH]... [--no-service] [--no-setup]
#   --no-setup leaves the Zen profile alone; the window offers the setup later.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA/zen-ext/app"
BIN="$HOME/.local/bin/zen-ext"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE=1
SETUP=1
SETUP_ARGS=()

# Messages follow the same language rules as the app (ZEN_EXT_LANG, then the locale).
case "${ZEN_EXT_LANG:-${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}}" in
  ru*) RU=1 ;;
  *) RU=0 ;;
esac
say() { if [ "$RU" = 1 ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --profile) SETUP_ARGS+=(--profile "$2"); shift 2 ;;
    --no-service) SERVICE=0; shift ;;
    --no-setup) SETUP=0; shift ;;
    -h|--help) sed -n 2,11p "$0"; exit 0 ;;
    *) say "Unknown option: $1" "Неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done

python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || { say "Python 3.9 or newer is required" "Нужен Python 3.9 или новее" >&2; exit 1; }
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
  say "Warning: PyGObject with GTK 4 and libadwaita is missing, the app window won't start (commands will work)." \
      "Внимание: нет PyGObject с GTK 4 и libadwaita, окно программы не запустится (команды будут работать)."
  echo "         Fedora: sudo dnf install python3-gobject gtk4 libadwaita"
fi

say "Copying the app to $APP_DIR" "Копирую программу в $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$ROOT/zen_ext" "$APP_DIR/"
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +

mkdir -p "$(dirname "$BIN")"
cat > "$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m zen_ext "\$@"
EOF
chmod +x "$BIN"

install -Dm644 "$ROOT/data/zen-ext.svg" "$DATA/icons/hicolor/scalable/apps/zen-ext.svg"
install -Dm644 /dev/stdin "$DATA/applications/zen-ext.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Zen Extensions
Name[ru]=Расширения Zen
Comment=Your own and any other extensions in Zen, no store needed
Comment[ru]=Свои и любые расширения в Zen без магазина
Exec=$BIN gui %U
Icon=zen-ext
Terminal=false
Categories=Utility;
MimeType=application/x-xpinstall;application/x-chrome-extension;
StartupNotify=true
EOF
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
gtk-update-icon-cache -q -t "$DATA/icons/hicolor" >/dev/null 2>&1 || true

if [ "$SERVICE" = 1 ] && command -v systemctl >/dev/null; then
  install -Dm644 /dev/stdin "$UNIT_DIR/zen-ext-watch.service" <<EOF
[Unit]
Description=zen-ext: rebuild extensions from linked folders

[Service]
ExecStart=$BIN watch
Restart=on-failure
RestartSec=5
Nice=10

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now zen-ext-watch.service
  systemctl --user restart zen-ext-watch.service
  say "Background service zen-ext-watch enabled" "Фоновый сервис zen-ext-watch включён"
fi

if [ "$SETUP" = 1 ]; then
  "$BIN" setup "${SETUP_ARGS[@]}"
  "$BIN" sync >/dev/null || true
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) say "Add ~/.local/bin to PATH so the zen-ext command can be found." \
         "Добавь ~/.local/bin в PATH, чтобы команда zen-ext находилась." ;;
esac
echo
say "Done. Open \"Zen Extensions\" from the app menu or run zen-ext --help." \
    "Готово. Открой «Расширения Zen» в меню приложений или используй zen-ext --help."
