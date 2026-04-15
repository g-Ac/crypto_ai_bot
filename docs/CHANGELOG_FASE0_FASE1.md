# Changelog — Fase 0 + Fase 1 (parcial)

> Data: 2026-04-13
> Sessao: Primeira execucao do roadmap V1

---

## Fase 0: Parar a Hemorragia (COMPLETA)

### 0.0 Desativar Agent Trader
- **Arquivo**: `.env`
- **Mudanca**: Adicionado `AGENT_TRADER_ENABLED=false`
- **Motivo**: -21.07% em 40 trades. Haiku nao agrega alpha
- **Validacao**: `config.py:164` le a variavel, `main.py:250` condiciona execucao

### 0.1 Fix liquidacoes invertidas
- **Arquivo**: `market_data.py:235-239`
- **Bug**: `m=True` (maker buyer) era mapeado para `vol_long`, mas o taker VENDEU (pressao short)
- **Fix**: Invertido — `m=True` → `vol_short`, `m=False` → `vol_long`
- **Impacto**: Sinais de liquidacao do scalping agora refletem corretamente a direcao da pressao

### 0.2 Fix win/loss com TP1 parcial
- **Arquivo**: `scalping_trader.py:659-671`
- **Bug**: Trade com TP1 hit (+1%) seguido de SL breakeven (-0.04% fees) era contado como loss
- **Fix**: Win/loss agora classificado pelo PnL TOTAL do trade (`tp1_pnl_usd + pnl_usd`)
- **Extras**: Historico agora inclui `total_trade_pnl_pct` e flag `tp1_hit`

### 0.3 Lock no scalping_state.json
- **Arquivo**: `risk_manager.py:33-62`
- **Bug**: Read/write concorrente entre ciclo principal e Telegram listener podia corromper state
- **Fix**: `threading.Lock` global (`_state_lock`) protege `load_scalping_state()` e `save_scalping_state()`

---

## Fase 1: Fundacao (PARCIAL)

### 1.2 Fix ATR off-by-one
- **Arquivo**: `risk_manager.py:115`
- **Bug**: Guard `len(df_15m) < 21` insuficiente para `iloc[-22:-2]` (precisa 22 linhas)
- **Fix**: Alterado para `< 22`

### 1.4 File handle leak no supervisor
- **Arquivo**: `supervisor.py:71-84`
- **Bug**: `log_file` ficava aberto se `Popen` falhasse
- **Fix**: `try/except` que fecha `log_file` antes de re-raise

### 1.5 label_scalping_outcomes no try/except
- **Arquivo**: `main.py:316-322`
- **Bug**: Falha no labeling pulava o daily report (fora de try/except)
- **Fix**: Envolvido em `try/except Exception` com print de erro

---

## Arquivos modificados

| Arquivo | Linhas alteradas | Tipo |
|---------|-----------------|------|
| `.env` | +1 | config |
| `market_data.py` | 235-239 | bugfix |
| `scalping_trader.py` | 659-690 | bugfix |
| `risk_manager.py` | 13, 33-62, 115 | bugfix + safety |
| `supervisor.py` | 71-84 | bugfix |
| `main.py` | 316-322 | safety |

## Validacao

- Todos os modulos compilam: `python -c "import main; import supervisor; import risk_manager; import market_data; import scalping_trader"` → OK
- Bot precisa de restart para aplicar as mudancas
