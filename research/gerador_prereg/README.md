# Gerador de Pré-Registros (forward-only)

Máquina de **disciplina**, não de edge. Congela hipóteses ex-ante e julga
mecanicamente no marco — sem nunca testar contra o passado já varrido. Substitui o
anti-padrão "loop que re-roda hipóteses no histórico" (viés temporal ~80% GO falso).

Desenho completo e decisões congeladas: **[MINI_MOLDURA.md](MINI_MOLDURA.md)**.

## Arquivos

| Arquivo | Papel |
|---|---|
| `catalogo.py` | primitivas auto-executáveis do **espaço novo** (sinais/filtros/exits) + `build_trades` |
| `schema.py` | schema + validação + IO do `journal.jsonl` (a guarda de integridade) |
| `gerador.py` | congela 1 hipótese nova por execução (criatividade curada, forward-only) |
| `colhedor.py` | juiz mecânico: mede no forward, BH-FDR por batch, grava verdict (Python puro) |
| `journal.jsonl` | log de pré-registros congelados (1 linha cada) |
| `resultado.json` | saída do colhedor (gerado no marco) |

Trigger cron: `scripts/gerador_prereg_trigger.py`. Testes: `tests/test_gerador_*.py`.

## Fluxo

```
gerador.gerar()         # congela 1 hipótese (status=frozen, verdict=null). Cap 5/lote.
        │  (espera o marco — o dado forward acumula sozinho)
        ▼
colhedor.colher()       # no marco: mede SÓ bucket_ts >= corte, BH-FDR por batch, grava verdict
        ▲
scripts/gerador_prereg_trigger.py   # cron diário; dispara o colhedor quando o marco vence
```

## Uso

```bash
cd ~/crypto_ai_bot && source .venv/bin/activate

# congelar uma hipótese nova (até 5 por lote/dia)
python -c "from research.gerador_prereg import gerador; print(gerador.gerar())"

# inspecionar o journal
python -c "from research.gerador_prereg import schema, colhedor as c; \
[print(r['id'], r['status'], r['spec']['signal']) for r in schema.read_journal(str(c.JOURNAL_DEFAULT))]"

# trigger (idempotente; só roda quando o marco vence) — instalar no cron:
#   10 6 * * *  cd /home/pi/crypto_ai_bot && .venv/bin/python scripts/gerador_prereg_trigger.py
```

## Estado atual

- **Batch `B-20260618`**: 5 pré-registros `frozen`, marco **2026-08-01**, `verdict=null`.
- Custos travados: 10 bps fee round-trip + 2 bps slippage = **12 bps**.
- O colhedor NÃO foi rodado contra o dado real (forward-only): só validado com fixtures
  sintéticas. O veredito real sai no marco, via cron.

## Regras invioláveis

1. O gerador **nunca** vê o dado forward; o colhedor **nunca** usa Claude.
2. Primitiva fora do catálogo = rejeitada pelo schema.
3. `corte_ts` estritamente futuro vs `created_at` (validado).
4. Não toca o Juiz Forward (`research/juiz_forward/`) nem os dados de coleta.
