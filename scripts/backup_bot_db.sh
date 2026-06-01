#!/usr/bin/env bash
# backup_bot_db.sh — backup diário consistente do bot.db
#
# Usa `sqlite3 .backup` (online backup API): consistente mesmo se collector
# estiver escrevendo, sem precisar parar o serviço. Comprime e mantém últimos
# 7 dias rotativos.
#
# IMPORTANT — LIMITE DESTE BACKUP:
#   Backup local fica no MESMO cartão SD do DB original. Cobre:
#     - bug, crash no meio da escrita, apagão durante write
#     - corrupção lógica (esquema, constraints)
#   NÃO cobre:
#     - cartão SD falhando (perde DB E backup juntos)
#     - roubo/perda do Pi
#
# TODO (manual, importante porque dado LSR/OI é insubstituível após 30d):
#   Agendar cópia SEMANAL pra outra máquina via Tailscale OU nuvem.
#   Exemplos no fim deste arquivo.

set -euo pipefail

DB_PATH="/home/pi/crypto_ai_bot/runtime/baseline/bot.db"
BACKUP_DIR="${K_COLLECTOR_BACKUP_DIR:-/home/pi/backups}"
KEEP_DAYS=7

ts="$(date +%Y%m%d_%H%M%S)"
out_uncompressed="${BACKUP_DIR}/bot.db.${ts}"
out="${out_uncompressed}.gz"

# Sanity check
if [[ ! -f "$DB_PATH" ]]; then
  echo "ERRO: DB nao encontrado: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

# Online backup via sqlite3 .backup (consistente, não precisa lock exclusivo)
# Diferente de `cp`, este respeita WAL e checkpoint corretamente.
sqlite3 "$DB_PATH" ".backup '${out_uncompressed}'"

# Compressão (reduz ~3-5x; LSR/OHLCV são valores numéricos compressíveis)
gzip -9 "$out_uncompressed"

size=$(du -h "$out" | cut -f1)
echo "[$(date -Iseconds)] backup OK: $out ($size)"

# Rotação — remove backups mais antigos que KEEP_DAYS
find "$BACKUP_DIR" -name "bot.db.*.gz" -type f -mtime "+${KEEP_DAYS}" -delete
remaining=$(find "$BACKUP_DIR" -name "bot.db.*.gz" -type f | wc -l)
echo "[$(date -Iseconds)] rotacao: mantidos $remaining backups (KEEP_DAYS=$KEEP_DAYS)"

# ----------------------------------------------------------------------
# TODO (offsite backup — manual setup quando tiver):
#
# OPÇÃO A — Tailscale pro seu PC (recomendado, sem custo, criptografado):
#   No PC: instalar Tailscale, anotar hostname (e.g., gabriel-pc).
#   Aqui no Pi, adicionar ao final deste script:
#     scp "$out" "gabriel@gabriel-pc:/path/to/backups/" || \
#       echo "WARN: offsite scp falhou (PC offline?)" >&2
#
# OPÇÃO B — Rclone pra Google Drive/Dropbox/B2 (offline-resilient):
#   rclone copy "$out" remote:crypto_ai_bot_backups/ --max-age 1d || \
#     echo "WARN: rclone offsite falhou" >&2
#
# OPÇÃO C — git lfs num repo privado (versionamento + offsite):
#   Complexo; só se já usa LFS.
#
# Frequência sugerida: cópia LOCAL diária (este script) + OFFSITE semanal.
# ----------------------------------------------------------------------
