#!/usr/bin/env bash
# backup_runtime_bundle.sh — pacote completo de disaster recovery do runtime.
#
# Empacota tudo que MORRE com o SD e não está no git:
#   - bot.db (via sqlite3 .backup — consistente com WAL, nunca cp a quente)
#   - JSONs de estado operacional (momentum_state, paper_state, bot_control,
#     runtime_manifest)
#   - crontab exportado
#   - systemd units INSTALADOS em /etc (estado real do sistema)
#   - metadata git (branch, commit, working tree)
#   - nomes das chaves do .env (NUNCA os valores — secrets ficam fora, ver
#     docs/DISASTER_RECOVERY.md §5)
#   - SHA256SUMS de tudo
#
# Saída: /home/pi/backups/bundles/runtime_bundle_<ts>.tar.gz (retenção: últimos 8)
#
# IMPORTANTE — backup local no mesmo SD é cache operacional, não disaster
# recovery. Defina OFFSITE_DEST (ex.: "gabriel@pc:/backups/") para o scp
# automático ao final, ou copie o bundle para fora da Pi manualmente.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${REPO_DIR}/runtime/baseline"
DB_PATH="${RUNTIME_DIR}/bot.db"
BUNDLE_DIR="${RUNTIME_BUNDLE_DIR:-/home/pi/backups/bundles}"
KEEP_BUNDLES=8

ts="$(date +%Y%m%d_%H%M%S)"
name="runtime_bundle_${ts}"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

fail() { echo "ERRO: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }

[[ -f "$DB_PATH" ]] || fail "bot.db não encontrado em ${DB_PATH}"
mkdir -p "${BUNDLE_DIR}" "${staging}/${name}"
dest="${staging}/${name}"

# 1. Banco — online backup (consistente mesmo com collector escrevendo)
sqlite3 "$DB_PATH" ".backup '${dest}/bot.db'"

# 2. JSONs de estado operacional (WARN se faltar — backup prossegue)
for f in momentum_state.json paper_state.json bot_control.json runtime_manifest.json; do
  if [[ -f "${RUNTIME_DIR}/${f}" ]]; then
    cp "${RUNTIME_DIR}/${f}" "${dest}/${f}"
  else
    warn "estado ausente (não incluído): ${f}"
  fi
done

# 3. Crontab
crontab -l > "${dest}/crontab.txt" 2>/dev/null || warn "crontab vazio/inacessível"

# 4. systemd units instalados (estado real, pode divergir do repo)
mkdir -p "${dest}/systemd_installed"
for u in cryptobot.service liquidation-collector.service \
         k-collector-backup.service k-collector-backup.timer \
         k-collector-report.service k-collector-report.timer \
         k-collector-watchdog.service k-collector-watchdog.timer; do
  if [[ -f "/etc/systemd/system/${u}" ]]; then
    cp "/etc/systemd/system/${u}" "${dest}/systemd_installed/${u}"
  else
    warn "unit não instalado (não incluído): ${u}"
  fi
done

# 5. Metadata git
{
  echo "exported_at: $(date -Iseconds)"
  echo "branch: $(git -C "$REPO_DIR" branch --show-current)"
  echo "commit: $(git -C "$REPO_DIR" rev-parse HEAD)"
  echo "--- git status --short ---"
  git -C "$REPO_DIR" status --short
} > "${dest}/git_state.txt"

# 6. Nomes das chaves do .env (sem valores!) — conferência no restore
if [[ -f "${REPO_DIR}/.env" ]]; then
  grep -oE '^[A-Z_0-9]+' "${REPO_DIR}/.env" > "${dest}/env_keys.txt"
else
  warn ".env não encontrado — env_keys.txt não gerado"
fi

# 7. Checksums
(cd "$dest" && find . -type f ! -name SHA256SUMS -exec sha256sum {} \; > SHA256SUMS)

# 8. Empacota
out="${BUNDLE_DIR}/${name}.tar.gz"
tar -czf "$out" -C "$staging" "$name"
size="$(du -h "$out" | cut -f1)"
echo "[$(date -Iseconds)] bundle OK: ${out} (${size})"

# 9. Retenção — mantém os últimos KEEP_BUNDLES
ls -1t "${BUNDLE_DIR}"/runtime_bundle_*.tar.gz 2>/dev/null | tail -n "+$((KEEP_BUNDLES + 1))" \
  | xargs -r rm -f
remaining="$(ls -1 "${BUNDLE_DIR}"/runtime_bundle_*.tar.gz 2>/dev/null | wc -l)"
echo "[$(date -Iseconds)] retenção: ${remaining} bundles mantidos (max ${KEEP_BUNDLES})"

# 10. Offsite
if [[ -n "${OFFSITE_DEST:-}" ]]; then
  if scp -q "$out" "${OFFSITE_DEST}"; then
    echo "[$(date -Iseconds)] offsite OK: ${OFFSITE_DEST}"
  else
    warn "offsite scp FALHOU (${OFFSITE_DEST} offline?) — bundle só local!"
  fi
else
  echo "TODO OFFSITE: bundle está no mesmo SD do original — copie para fora da Pi."
  echo "  Ex.: scp ${out} usuario@pc:/backups/   (ou defina OFFSITE_DEST)"
fi
