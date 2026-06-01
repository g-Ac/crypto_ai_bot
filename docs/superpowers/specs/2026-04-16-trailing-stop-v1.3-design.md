# Trailing Stop v1.3 — Design Spec

**Data:** 2026-04-16
**Status:** Aprovado
**Base:** momentum-pullback-v1.2 (breakeven ativo)

## Problema

O momentum pullback v1.2 tem MFE medio de 0.57-0.76% nos trades, mas capture ratio negativo (-1.85). O breakeven protege de loss, porem 188 trades sairam a 0% que tinham MFE medio de 0.57% — lucro deixado na mesa. Timeout rigido de 16 candles fecha trades em pontos desfavoraveis mesmo quando a tendencia continua.

Trade real (16-Apr-2026): BTCUSDT LONG entry $74,858, MFE +0.376% (~$75,140), timeout fechou a $74,748 (-0.15%). Mercado foi a $75,000 logo apos.

## Solucao

Fixed percentage trailing stop que acompanha o highest high (LONG) ou lowest low (SHORT), ativado apos threshold de MFE.

## Comportamento

```
Entrada -> SL fixo (original)
  -> MFE >= 50% de TP1 -> breakeven (SL = entry)         [v1.2]
    -> MFE continua -> trailing (SL = high - X%)          [v1.3]
      -> SL so avanca, nunca recua
        -> Preco toca trailing_sl -> exit "trailing_stop"
```

Prioridade de exit (nao muda): SL/breakeven/trailing > TP2 > TP1 > timeout.

## Parametros novos (MomentumConfig)

| Parametro | Tipo | Default | Descricao |
|---|---|---|---|
| `trailing_pct` | float | 0.0 | Percentual abaixo do high para trail. 0 = disabled |
| `trailing_trigger_pct` | float | 0.5 | Fracao do TP1 distance para ativar trailing |

Default 0.0 garante backward-compatibility total.

## Logica de check_exit (pseudo-codigo)

```python
# Apos breakeven (effective_sl ja pode ser entry_price)
if trailing_pct > 0:
    tp1_distance = abs(tp1_price - entry_price)
    trigger = trailing_trigger_pct * tp1_distance
    mfe_in_price = mfe / 100 * entry_price

    if mfe_in_price >= trigger:
        if is_long:
            candidate = candle_high * (1 - trailing_pct / 100)
            new_trailing_sl = max(current_trailing_sl, candidate)
            new_trailing_sl = max(new_trailing_sl, effective_sl)
        else:  # SHORT
            candidate = candle_low * (1 + trailing_pct / 100)
            new_trailing_sl = min(current_trailing_sl, candidate)
            new_trailing_sl = min(new_trailing_sl, effective_sl)
        effective_sl = new_trailing_sl

# Hit checks usam effective_sl (sem mudanca)
if sl_hit:
    reason = "trailing_stop" se veio do trailing
           | "breakeven" se veio do breakeven
           | "sl_hit" se SL original
```

## Assinatura modificada de check_exit

3 novos keyword args com default 0.0:

```python
def check_exit(
    *,
    # ... params existentes ...
    breakeven_trigger_pct: float = 0.0,
    trailing_pct: float = 0.0,           # NOVO
    trailing_trigger_pct: float = 0.0,    # NOVO
    current_trailing_sl: float = 0.0,     # NOVO (estado acumulado)
) -> Dict[str, Any]:
```

Retorno ganha campo `"new_trailing_sl"` para propagacao de estado.

## Estado da posicao (paper_executor JSON)

1 campo novo: `"trailing_sl_price": 0.0`

Backward-compatible via `pos.get("trailing_sl_price", 0.0)`.

## Research runner (backtest)

- `research_db.py`: adicionar `trailing_sl_price REAL DEFAULT 0.0` na DDL de momentum_trades
- `_manage_positions()`: propagar current_trailing_sl entre candles via campo no DB
- DBs de research sao recriados a cada run (sem migracao)

## Variantes de backtest (tuning_matrix.py)

| Variante | trailing_pct | breakeven | sl_floor |
|---|---|---|---|
| D1_trail05 | 0.5% | 0.5 | 0.5% |
| D2_trail10 | 1.0% | 0.5 | 0.5% |
| D3_trail15 | 1.5% | 0.5 | 0.5% |
| D4_trail20 | 2.0% | 0.5 | 0.5% |

Base de comparacao: B3_floor05_be (v1.2, breakeven sem trailing).

## Arquivos a modificar

| Arquivo | Mudanca |
|---|---|
| `momentum/config.py` | +2 campos no dataclass |
| `momentum/research_runner.py` | check_exit +3 params, logica trailing, _exit +campo |
| `momentum/paper_executor.py` | open_position +campo, manage_positions passa/recebe trailing |
| `momentum/research_db.py` | DDL +coluna, update function |
| `scripts/tuning_matrix.py` | +4 variantes |
| `tests/test_check_exit_trailing.py` | NOVO: ~10 testes da funcao pura |

## Testes necessarios

1. Trailing nao ativa antes do threshold
2. Trailing ativa e calcula SL correto (LONG)
3. Trailing ativa e calcula SL correto (SHORT)
4. Trailing so avanca, nunca recua
5. Trailing nao recua abaixo do breakeven
6. Exit reason = "trailing_stop" quando trailing SL e atingido
7. trailing_pct=0.0 = comportamento identico ao v1.2
8. new_trailing_sl propagado no retorno (closed e no-exit)
9. Coexistencia breakeven + trailing
10. Posicoes antigas sem trailing_sl_price continuam funcionando

## Impacto esperado (baseado em simulacao)

Com trailing capturando ~50% do MFE (simulacao no dataset de 90 dias):
- total_pnl: +19.17% -> ~+110-159% (depende do trailing_pct final)
- Trades timeout com MFE positivo: de -0.15% avg -> captura parcial do MFE

## Riscos

- Trailing muito tight (0.5%) pode stopar em noise normal de BTC 15m
- Trailing muito wide (2.0%) pode devolver lucro demais antes de sair
- Backtest determinara o valor otimo antes de ativar em producao
