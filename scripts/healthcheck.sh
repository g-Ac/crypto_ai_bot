#!/usr/bin/env bash
# healthcheck.sh — verificação consolidada de saúde do crypto_ai_bot.
#
# Uso:
#   bash scripts/healthcheck.sh           # checks operacionais (rápido, ~10s)
#   bash scripts/healthcheck.sh --full    # + ci.sh (pytest completo + py_compile)
#
# Saída: PASS/WARN/FAIL por check + resumo. Exit 1 se houver qualquer FAIL.
# Serviços parados geram WARN (não FAIL) — é o estado esperado pós-restore,
# antes do start manual (docs/DISASTER_RECOVERY.md §6-7).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${REPO_DIR}/runtime/baseline"
DB="${RUNTIME_DIR}/bot.db"
FULL=false
[[ "${1:-}" == "--full" ]] && FULL=true

if [ -t 1 ]; then G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
else G=''; Y=''; R=''; N=''; fi

NPASS=0; NWARN=0; NFAIL=0
pass() { echo -e "${G}PASS${N}  $*"; NPASS=$((NPASS+1)); }
warn() { echo -e "${Y}WARN${N}  $*"; NWARN=$((NWARN+1)); }
fail() { echo -e "${R}FAIL${N}  $*"; NFAIL=$((NFAIL+1)); }

echo "=== healthcheck crypto_ai_bot — $(date -Iseconds) ==="

# ── 1. Ambiente e código ────────────────────────────────────────────
[[ -x "${REPO_DIR}/.venv/bin/python" ]] \
  && pass "venv presente" \
  || fail "venv ausente (${REPO_DIR}/.venv) — python3 -m venv .venv && pip install -r requirements.txt"

if (cd "$REPO_DIR" && ./.venv/bin/python -m py_compile main.py supervisor.py dashboard_server.py 2>/dev/null); then
  pass "código compila (main, supervisor, dashboard_server)"
else
  fail "py_compile falhou em módulo crítico"
fi

# ── 2. Secrets ──────────────────────────────────────────────────────
if [[ -f "${REPO_DIR}/.env" ]]; then
  missing=""
  for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID MOMENTUM_TRADER_ENABLED; do
    grep -q "^${k}=" "${REPO_DIR}/.env" || missing="${missing} ${k}"
  done
  [[ -z "$missing" ]] && pass ".env presente com chaves esperadas" \
                      || fail ".env presente mas faltam:${missing}"
else
  fail ".env AUSENTE — restaurar manualmente (DISASTER_RECOVERY.md §5)"
fi

# ── 3. Banco ────────────────────────────────────────────────────────
if [[ -f "$DB" ]]; then
  if [[ "$(sqlite3 "$DB" 'PRAGMA quick_check;' 2>/dev/null)" == "ok" ]]; then
    pass "bot.db íntegro ($(du -h "$DB" | cut -f1))"
  else
    fail "bot.db corrompido (PRAGMA quick_check != ok)"
  fi
  for t in momentum_trades momentum_decisions k_prices k_liquidations; do
    n="$(sqlite3 "$DB" "SELECT COUNT(*) FROM ${t};" 2>/dev/null)" \
      && pass "tabela ${t}: ${n} linhas" \
      || fail "tabela ausente: ${t}"
  done
else
  fail "bot.db AUSENTE em ${DB}"
fi

# ── 4. Estado operacional ───────────────────────────────────────────
for f in momentum_state.json paper_state.json bot_control.json; do
  [[ -f "${RUNTIME_DIR}/${f}" ]] && pass "estado: ${f}" || fail "estado AUSENTE: ${f}"
done

# ── 5. systemd ──────────────────────────────────────────────────────
for u in cryptobot.service liquidation-collector.service; do
  if [[ -f "/etc/systemd/system/${u}" ]]; then
    if systemctl is-active --quiet "$u"; then
      pass "${u} instalado e ATIVO"
    else
      warn "${u} instalado mas PARADO (esperado pós-restore; start manual)"
    fi
  else
    fail "${u} NÃO instalado em /etc/systemd/system/"
  fi
done
for t in k-collector-backup.timer k-collector-report.timer k-collector-watchdog.timer; do
  systemctl is-enabled --quiet "$t" 2>/dev/null \
    && pass "timer ${t} enabled" \
    || warn "timer ${t} não instalado — sudo bash systemd/install_systemd_units.sh"
done

# ── 6. Loop vivo + dashboard (só cobra se o serviço estiver de pé) ──
if systemctl is-active --quiet cryptobot 2>/dev/null; then
  if [[ -f "$DB" ]]; then
    last="$(sqlite3 "$DB" "SELECT MAX(timestamp) FROM momentum_decisions;" 2>/dev/null)"
    # timestamps do bot.db são UTC naive — anexar "UTC" para o date converter certo
    age=$(( $(date +%s) - $(date -d "${last:-1970-01-01} UTC" +%s 2>/dev/null || echo 0) ))
    if (( age < 1800 )); then
      pass "momentum_decisions recente (${age}s atrás)"
    else
      fail "cryptobot ativo mas última decisão tem ${age}s (>30min) — loop travado?"
    fi
  fi
  if curl -sf -m 5 http://127.0.0.1:5000/api/status >/dev/null; then
    pass "dashboard responde em :5000/api/status"
  else
    fail "cryptobot ativo mas dashboard NÃO responde em :5000"
  fi
else
  warn "cryptobot parado — checks de loop/dashboard pulados"
fi

# ── 7. Backups ──────────────────────────────────────────────────────
newest="$(ls -1t /home/pi/backups/bot.db.*.gz /home/pi/backups/bundles/runtime_bundle_*.tar.gz 2>/dev/null | head -1)"
if [[ -n "$newest" ]]; then
  age_h=$(( ($(date +%s) - $(stat -c %Y "$newest")) / 3600 ))
  (( age_h <= 48 )) && pass "backup mais recente: ${newest##*/} (${age_h}h)" \
                    || warn "backup mais recente tem ${age_h}h (>48h): ${newest##*/}"
else
  warn "NENHUM backup em /home/pi/backups — rodar scripts/backup_runtime_bundle.sh"
fi

# ── 8. Disco e git ──────────────────────────────────────────────────
free_mb="$(df -m / | awk 'NR==2{print $4}')"
(( free_mb > 1024 )) && pass "disco: ${free_mb}MB livres" || warn "disco: só ${free_mb}MB livres"
dirty="$(git -C "$REPO_DIR" status --short | wc -l)"
echo "INFO  git: branch $(git -C "$REPO_DIR" branch --show-current), ${dirty} arquivos não commitados"

# ── 9. Suite completa (--full) ──────────────────────────────────────
if $FULL; then
  echo "--- ci.sh (pytest + py_compile) ---"
  if (cd "$REPO_DIR" && bash ci.sh); then pass "ci.sh (testes completos)"; else fail "ci.sh FALHOU"; fi
fi

echo ""
echo "=== resumo: ${NPASS} PASS / ${NWARN} WARN / ${NFAIL} FAIL ==="
(( NFAIL == 0 )) || exit 1
