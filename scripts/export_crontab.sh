#!/usr/bin/env bash
# export_crontab.sh — exporta o crontab do usuário para ops/crontab.current (versionável).
#
# Disaster recovery: o crontab vive só no SD; sem export versionado ele morre
# junto com o cartão. Rodar este script sempre que o cron mudar e commitar o
# resultado. Restore: `crontab ops/crontab.current` (revisar antes!).
#
# Sanity check: aborta se detectar padrão de secret (token/key/pass com valor),
# para nunca versionar credencial por engano.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_DIR}/ops"
OUT_FILE="${OUT_DIR}/crontab.current"

content="$(crontab -l 2>/dev/null)" || {
  echo "ERRO: crontab vazio ou inacessível para $(whoami)" >&2
  exit 1
}

# Bloqueia linhas tipo FOO_TOKEN=valor / api_key=valor (atribuição com valor real)
if echo "$content" | grep -qiE '(token|secret|passw|api_?key)[a-z_]*=[^[:space:]]+'; then
  echo "ERRO: possível secret detectado no crontab — não vou exportar." >&2
  echo "Remova/parametrize a linha e rode de novo." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
{
  echo "# crontab.current — exportado por scripts/export_crontab.sh em $(date -Iseconds)"
  echo "# Restore: revisar e aplicar com:  crontab ops/crontab.current"
  echo "$content"
} > "$OUT_FILE"

echo "OK: crontab exportado para ${OUT_FILE} ($(echo "$content" | grep -c .) linhas)"
