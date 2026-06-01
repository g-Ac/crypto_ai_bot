#!/usr/bin/env bash
# install_systemd_units.sh — instala os 3 timers do k_collector (watchdog, report, backup).
#
# Idempotente: re-rodar é seguro (daemon-reload + re-enable não duplica).
# REVERSÍVEL: use uninstall_systemd_units.sh para desfazer.
#
# Este script precisa de SUDO porque:
#   1. Copia .service/.timer pra /etc/systemd/system/ (root-owned)
#   2. systemctl daemon-reload (precisa root)
#   3. systemctl enable+start dos timers (precisa root)
#
# NÃO TOCA: cron do collector (que continua disparando o collector a cada hora).
# Apenas adiciona os 3 timers auxiliares.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERRO: precisa rodar com sudo" >&2
  echo "Uso: sudo bash $0" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo "==> Sanity check: arquivos de origem"
for unit in "${UNITS[@]}"; do
  if [[ ! -f "${SRC_DIR}/${unit}" ]]; then
    echo "ERRO: ${SRC_DIR}/${unit} nao existe" >&2
    exit 1
  fi
done

echo "==> Sanity check: /home/pi/crypto_ai_bot/.venv/bin/python existe?"
if [[ ! -x /home/pi/crypto_ai_bot/.venv/bin/python ]]; then
  echo "ERRO: venv ausente em /home/pi/crypto_ai_bot/.venv/bin/python" >&2
  exit 1
fi

echo "==> Sanity check: .env tem TELEGRAM_BOT_TOKEN?"
if [[ ! -f /home/pi/crypto_ai_bot/.env ]]; then
  echo "WARN: /home/pi/crypto_ai_bot/.env nao existe — Telegram nao vai funcionar"
elif ! grep -q "^TELEGRAM_BOT_TOKEN=" /home/pi/crypto_ai_bot/.env; then
  echo "WARN: TELEGRAM_BOT_TOKEN ausente no .env — Telegram nao vai funcionar"
fi

echo "==> Copiando units para ${DEST_DIR}"
for unit in "${UNITS[@]}"; do
  cp "${SRC_DIR}/${unit}" "${DEST_DIR}/${unit}"
  chmod 644 "${DEST_DIR}/${unit}"
  echo "  - ${unit}"
done

echo "==> systemctl daemon-reload"
systemctl daemon-reload

echo "==> Habilitando + iniciando timers"
for timer in "${TIMERS[@]}"; do
  systemctl enable "${timer}"
  systemctl start "${timer}"
  echo "  - ${timer} enabled+started"
done

echo ""
echo "==> Status dos timers:"
systemctl list-timers --no-pager | grep -E "(k-collector|NEXT)" || true

echo ""
echo "==> Done. Próximos disparos visíveis acima."
echo ""
echo "Logs:"
echo "  journalctl -u k-collector-watchdog.service -n 20"
echo "  journalctl -u k-collector-report.service -n 20"
echo "  journalctl -u k-collector-backup.service -n 20"
echo ""
echo "Para forçar uma execução agora (teste):"
echo "  sudo systemctl start k-collector-watchdog.service"
echo "  sudo systemctl start k-collector-report.service"
echo "  sudo systemctl start k-collector-backup.service"
echo ""
echo "Para desinstalar:"
echo "  sudo bash ${SRC_DIR}/uninstall_systemd_units.sh"
