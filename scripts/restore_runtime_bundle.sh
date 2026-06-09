#!/usr/bin/env bash
# restore_runtime_bundle.sh — restore CONSERVADOR de um runtime bundle.
#
# Uso:
#   bash scripts/restore_runtime_bundle.sh <bundle.tar.gz> [--verify-only] [--with-crontab] [--yes]
#
# O que faz:        valida checksums; restaura bot.db + JSONs de estado em
#                   runtime/baseline/ (preservando o estado atual em *.pre-restore.<ts>).
# O que NÃO faz:    não inicia serviço nenhum; não instala units; não toca no
#                   crontab (salvo --with-crontab); não restaura .env (secrets
#                   nunca viajam no bundle — restore manual, ver
#                   docs/DISASTER_RECOVERY.md §5); não ativa nada live (não
#                   existe caminho live — e restore jamais deve criar um).
#
# Próximo passo após restore:  bash scripts/healthcheck.sh --full
# Serviços sobem MANUALMENTE depois do healthcheck (DISASTER_RECOVERY.md §6).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${REPO_DIR}/runtime/baseline"

BUNDLE="" ; VERIFY_ONLY=false ; WITH_CRONTAB=false ; ASSUME_YES=false
for arg in "$@"; do
  case "$arg" in
    --verify-only)  VERIFY_ONLY=true ;;
    --with-crontab) WITH_CRONTAB=true ;;
    --yes)          ASSUME_YES=true ;;
    -*)             echo "ERRO: flag desconhecida: $arg" >&2; exit 1 ;;
    *)              BUNDLE="$arg" ;;
  esac
done

fail() { echo "ERRO: $*" >&2; exit 1; }
[[ -n "$BUNDLE" ]] || fail "uso: $0 <bundle.tar.gz> [--verify-only] [--with-crontab] [--yes]"
[[ -f "$BUNDLE" ]] || fail "bundle não encontrado: $BUNDLE"

# Segurança: nunca restaurar debaixo de serviço escrevendo no banco
if systemctl is-active --quiet cryptobot 2>/dev/null && ! $VERIFY_ONLY; then
  fail "cryptobot está RODANDO. Pare antes: sudo systemctl stop cryptobot"
fi
if systemctl is-active --quiet liquidation-collector 2>/dev/null && ! $VERIFY_ONLY; then
  fail "liquidation-collector está RODANDO. Pare antes: sudo systemctl stop liquidation-collector"
fi

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
tar -xzf "$BUNDLE" -C "$staging"
inner="$(find "$staging" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$inner" && -f "${inner}/SHA256SUMS" ]] || fail "bundle inválido (sem SHA256SUMS)"

echo "==> Validando checksums..."
(cd "$inner" && sha256sum -c SHA256SUMS --quiet) || fail "checksum FALHOU — bundle corrompido"
echo "    OK ($(wc -l < "${inner}/SHA256SUMS") arquivos)"

echo "==> Conteúdo do bundle:"
(cd "$inner" && ls -la | grep -v '^total\|^d.*\.$')
[[ -f "${inner}/git_state.txt" ]] && { echo "--- git_state.txt ---"; cat "${inner}/git_state.txt"; }

if $VERIFY_ONLY; then
  echo "==> --verify-only: nada restaurado. Bundle íntegro."
  exit 0
fi

if ! $ASSUME_YES; then
  read -rp "Restaurar este bundle para ${RUNTIME_DIR}? [digite 'sim'] " resp
  [[ "$resp" == "sim" ]] || fail "abortado pelo operador"
fi

ts="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUNTIME_DIR"

restore_file() {
  local f="$1"
  [[ -f "${inner}/${f}" ]] || { echo "    (ausente no bundle: ${f})"; return 0; }
  if [[ -f "${RUNTIME_DIR}/${f}" ]]; then
    mv "${RUNTIME_DIR}/${f}" "${RUNTIME_DIR}/${f}.pre-restore.${ts}"
    echo "    estado atual preservado: ${f}.pre-restore.${ts}"
  fi
  cp "${inner}/${f}" "${RUNTIME_DIR}/${f}"
  echo "    restaurado: ${f}"
}

echo "==> Restaurando banco e estado..."
# WAL/SHM antigos não podem conviver com um db restaurado de outro momento
rm -f "${RUNTIME_DIR}/bot.db-wal" "${RUNTIME_DIR}/bot.db-shm"
restore_file "bot.db"
for f in momentum_state.json paper_state.json bot_control.json runtime_manifest.json; do
  restore_file "$f"
done

if $WITH_CRONTAB && [[ -f "${inner}/crontab.txt" ]]; then
  echo "==> Aplicando crontab do bundle (--with-crontab)..."
  crontab "${inner}/crontab.txt"
  echo "    crontab aplicado ($(grep -c . "${inner}/crontab.txt") linhas)"
else
  echo "==> Crontab NÃO aplicado (use --with-crontab, ou: crontab ops/crontab.current)"
fi

echo ""
echo "==> Restore concluído. NENHUM serviço foi iniciado. Próximos passos:"
[[ -f "${inner}/env_keys.txt" ]] && {
  echo "  1. Restaurar .env MANUALMENTE (local seguro). Chaves esperadas:"
  sed 's/^/       - /' "${inner}/env_keys.txt"
}
echo "  2. bash scripts/healthcheck.sh --full"
echo "  3. Revisar posições em momentum_state.json (órfãs: python close_orphan_trades.py)"
echo "  4. Start manual: sudo systemctl start liquidation-collector cryptobot"
