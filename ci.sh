#!/bin/bash
# CI basico: roda testes e verifica sintaxe antes de deploy
# Uso: bash ci.sh [--notify]
#   --notify  envia resultado via Telegram (requer .env com TELEGRAM_*)
set -euo pipefail

cd "$(dirname "$0")"

# Cores (desativa se nao for terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; NC=''
fi

NOTIFY=false
[ "${1:-}" = "--notify" ] && NOTIFY=true

FAILED=0
SUMMARY=""

log() { echo -e "${1}${2}${NC}"; }

# ── Step 1: Ativar venv ─────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    log "$RED" "ERRO: .venv nao encontrado. Rode: python3 -m venv .venv"
    exit 1
fi
source .venv/bin/activate
log "$GREEN" "[1/3] venv ativado"

# ── Step 2: pytest ───────────────────────────────────────────────────
log "$YELLOW" "[2/3] Rodando testes..."
if python -m pytest tests/ --tb=short -q 2>&1; then
    SUMMARY+="pytest: OK\n"
    log "$GREEN" "  pytest OK"
else
    SUMMARY+="pytest: FALHOU\n"
    log "$RED" "  pytest FALHOU"
    FAILED=1
fi

# ── Step 3: py_compile nos arquivos criticos ─────────────────────────
log "$YELLOW" "[3/3] Verificando sintaxe Python..."
CRITICAL_FILES=(
    main.py
    supervisor.py
    dashboard_server.py
    database.py
    config.py
    scalping_trader.py
    pump_scanner.py
    pump_trader.py
    confluence.py
    risk_manager.py
    proactive_alerts.py
    daily_report.py
    market.py
    market_data.py
    strategy.py
    indicators.py
    htf.py
)
COMPILE_FAIL=0
for f in "${CRITICAL_FILES[@]}"; do
    if [ -f "$f" ]; then
        if ! python -m py_compile "$f" 2>&1; then
            log "$RED" "  ERRO sintaxe: $f"
            COMPILE_FAIL=1
        fi
    fi
done
if [ $COMPILE_FAIL -eq 0 ]; then
    SUMMARY+="py_compile: OK (${#CRITICAL_FILES[@]} arquivos)\n"
    log "$GREEN" "  py_compile OK (${#CRITICAL_FILES[@]} arquivos)"
else
    SUMMARY+="py_compile: FALHOU\n"
    log "$RED" "  py_compile FALHOU"
    FAILED=1
fi

# ── Resultado ────────────────────────────────────────────────────────
echo ""
echo "================================"
echo -e "$SUMMARY"
if [ $FAILED -eq 0 ]; then
    log "$GREEN" "CI PASSED"
else
    log "$RED" "CI FAILED"
fi
echo "================================"

# ── Notificacao Telegram (opcional) ──────────────────────────────────
if [ "$NOTIFY" = true ] && [ -f ".env" ]; then
    # Carrega TELEGRAM_TOKEN e TELEGRAM_CHAT_ID do .env
    export $(grep -E '^TELEGRAM_(BOT_TOKEN|CHAT_ID)=' .env | xargs)
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        if [ $FAILED -eq 0 ]; then
            MSG="✅ <b>CI PASSED</b>"
        else
            MSG="❌ <b>CI FAILED</b>"
        fi
        MSG+="%0A$(echo -e "$SUMMARY" | sed 's/\\n/%0A/g')"
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${MSG}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
fi

exit $FAILED
