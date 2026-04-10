#!/bin/bash
# Script completo para verificar P0/P1 e re-rodar o benchmark AI local.
# Uso: bash scripts/verify_and_benchmark.sh

set -e
cd ~/crypto_ai_bot

# ── Scripts Python temporarios ────────────────────────────────────────────
cat > /tmp/check_p0.py <<'PYEOF'
from datetime import datetime, timedelta
import re

cutoff = (datetime.now() - timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M')
count = 0
try:
    with open('runtime/baseline/logs/scalping.log') as f:
        for line in f:
            if 'division by zero' in line.lower():
                m = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', line)
                if m and m.group(1) >= cutoff:
                    count += 1
    print(f'Div by zero novos (2min): {count}')
except FileNotFoundError:
    print('Log scalping.log nao encontrado')
PYEOF

cat > /tmp/check_p1.py <<'PYEOF'
import sqlite3

conn = sqlite3.connect('runtime/baseline/bot.db')
cols = [c[1] for c in conn.execute('PRAGMA table_info(market_microstructure)').fetchall()]

for c in ['futures_price', 'spot_price', 'liquidation_count', 'liquidation_is_proxy', 'next_funding_time']:
    ok = 'OK' if c in cols else 'FALTA'
    print(f'  {c}: {ok}')

idxs = [r[1] for r in conn.execute('PRAGMA index_list(market_microstructure)').fetchall()]
idx_ok = 'OK' if 'idx_microstructure_sym_ts' in idxs else 'FALTA'
print(f'Indice composto: {idx_ok}')
PYEOF

# ── Execucao ───────────────────────────────────────────────────────────────
echo "=== Restart do bot ==="
sudo systemctl restart cryptobot
sleep 60

echo ""
echo "=== P0: division by zero recentes ==="
python3 /tmp/check_p0.py

echo ""
echo "=== SANITIZE / POSICAO CORROMPIDA ==="
grep -a "SANITIZE\|POSICAO CORROMPIDA" runtime/baseline/logs/scalping.log | tail -5 || echo "(nenhum)"

echo ""
echo "=== P1: schema microstructure ==="
python3 /tmp/check_p1.py

echo ""
echo "=== Modelos GGUF ==="
ls -lh ~/models/

echo ""
echo "=== Re-download TinyLlama (se necessario) ==="
cd ~/models
TINY_SIZE=$(stat -c%s tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf 2>/dev/null || echo 0)
if [ "$TINY_SIZE" -lt 600000000 ]; then
    echo "TinyLlama corrompido ou ausente, re-descarregando..."
    rm -f tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
    wget -q https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
    ls -lh tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
else
    echo "TinyLlama OK ($(ls -lh tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf | awk '{print $5}'))"
fi

echo ""
echo "=== Benchmark ==="
cd ~/crypto_ai_bot
python3 benchmark_ai_local.py
