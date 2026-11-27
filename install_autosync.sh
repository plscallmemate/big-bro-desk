#!/bin/bash
# Ставит ежедневный автозапуск ym_sync.py на маке (launchd).
# Использование (из папки, где лежат ym_sync.py и config.json):
#   bash install_autosync.sh            поставить, запуск каждый день в 07:50
#   bash install_autosync.sh 7 30       поставить на 07:30
#   bash install_autosync.sh run        запустить прямо сейчас (проверка)
#   bash install_autosync.sh off        выключить автозапуск
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.bigbro.ymsync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$DIR/ym_sync.log"
UIDN="$(id -u)"

if [ "$1" = "off" ]; then
  launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Автозапуск выключен."
  exit 0
fi

if [ "$1" = "run" ]; then
  launchctl kickstart -k "gui/$UIDN/$LABEL" 2>/dev/null || { echo "Сначала поставь: bash install_autosync.sh"; exit 1; }
  echo "Запущено. Смотри лог: tail -f \"$LOG\""
  exit 0
fi

[ -f "$DIR/run_sync.sh" ] || { echo "Не вижу run_sync.sh рядом."; exit 1; }
[ -f "$DIR/ym_sync.py" ] || { echo "Не вижу ym_sync.py рядом с установщиком ($DIR)."; exit 1; }
[ -f "$DIR/config.json" ] || { echo "Не вижу config.json рядом с ym_sync.py. Сначала запусти ym_sync.py руками один раз."; exit 1; }
case "$DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "⚠️  Папка лежит в Desktop/Documents/Downloads. macOS может не пустить туда фоновый запуск."
    echo "   Надёжнее перенести папку, например, в $HOME/ym и запустить установщик оттуда."
    ;;
esac

PY="$(command -v python3)" || { echo "Не нашёл python3."; exit 1; }
H="${1:-7}"; M="${2:-50}"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DIR/run_sync.sh</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$H</integer><key>Minute</key><integer>$M</integer></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UIDN" "$PLIST"
echo "Готово: ym_sync.py будет запускаться каждый день в $(printf '%02d:%02d' "$H" "$M")."
echo "Если в это время мак спал, запуск случится сразу после пробуждения."
echo "Проверить сейчас:  bash install_autosync.sh run   (потом: tail -f \"$LOG\")"
echo "Выключить:         bash install_autosync.sh off"
