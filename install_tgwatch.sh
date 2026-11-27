#!/bin/bash
# Ставит автозапуск tg_watch.py на маке (launchd): раз в 30 минут, пока мак не спит. VPN не нужен.
# Использование (из папки проекта):
#   bash install_tgwatch.sh          поставить
#   bash install_tgwatch.sh run      запустить прямо сейчас (проверка)
#   bash install_tgwatch.sh off      выключить
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.bigbro.tgwatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$DIR/tg_watch.log"
UIDN="$(id -u)"
PY="$DIR/.venv/bin/python"

if [ "$1" = "off" ]; then
  launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Автозапуск чатов выключен."
  exit 0
fi

if [ "$1" = "run" ]; then
  launchctl kickstart -k "gui/$UIDN/$LABEL" 2>/dev/null || { echo "Сначала поставь: bash install_tgwatch.sh"; exit 1; }
  echo "Запущено. Смотри лог: tail -f \"$LOG\""
  exit 0
fi

[ -x "$PY" ] || { echo "Нет .venv с telethon. Сделай: python3 -m venv .venv && .venv/bin/pip install telethon"; exit 1; }
[ -f "$DIR/config.json" ] || { echo "Не вижу config.json рядом."; exit 1; }
[ -f "$DIR/tg_watch.session" ] || { echo "Сначала войди в Telegram: .venv/bin/python tg_watch.py --login"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$DIR/tg_watch.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UIDN" "$PLIST"
echo "Готово: tg_watch.py будет запускаться раз в 30 минут, пока мак не спит."
echo "Лог: tail -f \"$LOG\""
echo "Выключить: bash install_tgwatch.sh off"
