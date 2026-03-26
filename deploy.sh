#!/bin/bash
# Deploy: commit local -> push GitHub -> pull no Pi -> restart servico
set -e

PI="pi@192.168.0.24"
BOT_DIR="~/crypto_ai_bot"

echo "=== [1/3] Commit e push para o GitHub ==="
cd "$(dirname "$0")"

git add -A

# Verifica se tem algo para commitar
if git diff --cached --quiet; then
    echo "  Nenhuma mudanca para commitar."
else
    MSG="deploy $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$MSG"
    echo "  Commit criado: $MSG"
fi

git push
echo "  Push concluido!"

echo ""
echo "=== [2/3] Atualizando o Pi ==="
ssh "$PI" "cd $BOT_DIR && git pull"

echo ""
echo "=== [3/3] Reiniciando o bot ==="
ssh "$PI" "sudo systemctl restart cryptobot && sleep 2 && sudo systemctl status cryptobot --no-pager | grep -E 'Active|Main PID'"

echo ""
echo "Deploy concluido! Bot rodando com o codigo mais recente."
