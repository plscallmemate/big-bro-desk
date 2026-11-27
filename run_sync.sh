#!/bin/bash
# Обёртка для автозапуска: включает VPN (через Команды), гоняет ym_sync.py, выключает VPN.
# Имена команд из приложения «Команды». Пусто = этот шаг пропускается.
VPN_ON="VPN Вкл"
VPN_OFF="VPN Выкл"
WAIT=25          # сколько секунд ждать, пока VPN поднимется

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1
echo "=== $(date '+%d.%m.%Y %H:%M:%S') старт ==="

if [ -n "$VPN_ON" ]; then
  echo "включаю VPN: $VPN_ON"
  shortcuts run "$VPN_ON" || echo "⚠️ команда «$VPN_ON» не отработала"
  sleep "$WAIT"
fi

# VPN выключаем при любом исходе, даже если скрипт упал
SLEEP_AFTER=1    # 1 = если за маком никого нет (не трогали >5 мин), после синхронизации усыпить его обратно
trap '[ -n "$VPN_OFF" ] && { echo "выключаю VPN: $VPN_OFF"; shortcuts run "$VPN_OFF" || echo "⚠️ команда «$VPN_OFF» не отработала"; }; echo "=== конец ==="; if [ "$SLEEP_AFTER" = 1 ]; then idle=$(ioreg -c IOHIDSystem | awk "/HIDIdleTime/ {print int(\$NF/1000000000); exit}"); if [ "${idle:-0}" -gt 300 ]; then echo "мак не трогали ${idle} сек, усыпляю"; pmset sleepnow; fi; fi' EXIT

# caffeinate не даёт маку уснуть, пока идёт синхронизация
caffeinate -i "$(command -v python3)" "$DIR/ym_sync.py"
