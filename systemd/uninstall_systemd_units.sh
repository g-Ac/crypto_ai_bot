#!/usr/bin/env bash
# uninstall_systemd_units.sh — reverte o install_systemd_units.sh.
# Para+desabilita+remove os 6 unit files. Não toca em logs ou backups.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERRO: precisa rodar com sudo" >&2
  exit 1
fi

DEST_DIR="/etc/systemd/system"

UNITS=(
  "k-collector-watchdog.service"
  "k-collector-watchdog.timer"
  "k-collector-report.service"
  "k-collector-report.timer"
  "k-collector-backup.service"
  "k-collector-backup.timer"
)

TIMERS=(
  "k-collector-watchdog.timer"
  "k-collector-report.timer"
  "k-collector-backup.timer"
)

echo "==> Parando e desabilitando timers"
for timer in "${TIMERS[@]}"; do
  systemctl stop "${timer}" 2>/dev/null || true
  systemctl disable "${timer}" 2>/dev/null || true
  echo "  - ${timer} stopped+disabled"
done

echo "==> Removendo unit files"
for unit in "${UNITS[@]}"; do
  if [[ -f "${DEST_DIR}/${unit}" ]]; then
    rm "${DEST_DIR}/${unit}"
    echo "  - removed ${unit}"
  fi
done

echo "==> systemctl daemon-reload"
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

echo ""
echo "==> Done. Cron do collector NÃO foi tocado (continua rodando :05)."
echo "    Logs em ~/crypto_ai_bot/logs/ preservados."
echo "    Backups em ~/backups/ preservados."
