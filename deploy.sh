#!/bin/bash
# Deploy: commit local -> push GitHub -> pull no Pi -> restart servico
set -e

# IP local (mesma rede) ou Tailscale (rede externa)
# Local: 192.168.0.24 | Tailscale: 100.99.44.92
PI="pi@100.99.44.92"
BOT_DIR="~/crypto_ai_bot"

echo "=== [1/4] Commit e push para o GitHub ==="
cd "$(dirname "$0")"

# Stage apenas arquivos de codigo e configuracao — nunca estado, banco ou segredos
git add *.py templates/ deploy.sh .gitignore requirements.txt 2>/dev/null || true

# Safety net: aborta se arquivos sensiveis foram staged acidentalmente
STAGED_FILES=$(git diff --cached --name-only)
BLOCKED_PATTERN='\.env|credentials|\.secret|\.pem|\.key|token'
BLOCKED=$(echo "$STAGED_FILES" | grep -iE "$BLOCKED_PATTERN" || true)
if [ -n "$BLOCKED" ]; then
    echo "ERRO: Arquivos sensiveis detectados no staging:"
    echo "$BLOCKED"
    echo "Removendo do staging e abortando. Use 'git reset HEAD <file>' se necessario."
    echo "$BLOCKED" | xargs git reset HEAD -- 2>/dev/null || true
    exit 1
fi

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
echo "=== [2/4] Atualizando o Pi ==="
# --ff-only: falha limpo se houver conflito em vez de criar merge silencioso
if ! ssh "$PI" "cd $BOT_DIR && git pull --ff-only"; then
    echo "ERRO: git pull falhou no Pi (possivel conflito ou divergencia)."
    echo "Corrija manualmente antes de reiniciar o bot."
    exit 1
fi

echo ""
echo "=== [3/4] Verificacao de saude pre-restart ==="
# Verifica sintaxe Python dos arquivos principais antes de reiniciar
HEALTH_CHECK="cd $BOT_DIR && python3 -c 'import main; import supervisor; import dashboard_server; print(\"OK\")'"
if ! ssh "$PI" "$HEALTH_CHECK" 2>/dev/null; then
    echo "ERRO: Health check falhou — imports Python quebraram apos o pull."
    echo "O bot NAO foi reiniciado. Codigo no Pi pode estar inconsistente."
    echo "Corrija o erro e faca deploy novamente."
    exit 1
fi
echo "  Health check OK — imports validados."

echo ""
echo "=== [4/4] Reiniciando o bot ==="
ssh "$PI" "sudo systemctl restart cryptobot && sleep 2 && sudo systemctl status cryptobot --no-pager | grep -E 'Active|Main PID'"

echo ""
echo "Deploy concluido! Bot rodando com o codigo mais recente."
