# DB Metrics Post-Reset — 08/04/2026

## Trades por Sistema (desde 06/04)

| System   | Trades | Wins | Losses | Avg PnL% | Total USD |
|----------|--------|------|--------|----------|-----------|
| scalping |      8 |    3 |      5 |   0.0780 |     $0.47 |
| agent    |     12 |    0 |     12 |  -1.3744 |    -$2.93 |
| paper    |      4 |    1 |      3 |  -1.1859 |  -$197.93 |
| pump     |     14 |    4 |     10 |  -1.3322 |    -$0.53 |

## Scalping Trades (detalhe)

| Timestamp           | Symbol   | Dir  | Entry    | Exit     | PnL%   | PnL$   | Reason        |
|---------------------|----------|------|----------|----------|--------|--------|---------------|
| 07/04 16:37         | DOGEUSDT | LONG | 0.0915   | (open)   | -      | -      | open          |
| 07/04 16:48         | DOGEUSDT | LONG | 0.0915   | 0.0917   | +0.22% | +$0.32 | take_profit_2 |
| 07/04 22:56         | ETHUSDT  | LONG | 2236.25  | (open)   | -      | -      | open          |
| 07/04 23:08         | ETHUSDT  | LONG | 2236.25  | 2240.35  | +0.10% | +$0.15 | take_profit_2 |
| 07/04 23:54         | DOGEUSDT | LONG | 0.0946   | (open)   | -      | -      | open          |
| 07/04 23:59         | DOGEUSDT | LONG | 0.0946   | 0.0946   | +0.07% | +$0.11 | manual_reset  |
| 07/04 23:59         | DOGEUSDT | LONG | 0.0945   | (open)   | -      | -      | open          |
| 08/04 00:50         | DOGEUSDT | LONG | 0.0945   | 0.0945   | -0.09% | -$0.11 | stop_loss     |

Nota: Scalping win rate real = 3/5 = 60% (excluindo 3 registros "open" que sao entradas sem saida)

## Agent Trades (detalhe resumido)

- 06/04-07/04: 3 trades com SL hit (-2.08% cada) = -$2.67
- 07/04 23:59: 2 trades fechados por manual_reset = -$0.26
- 08/04: 2 posicoes abertas (XRPUSDT LONG, ETHUSDT LONG)
- **Agent: 0 wins em 12 registros (6 closes, 6 opens)**

## AI Decisions

- Total: 22 decisoes desde 06/04
- Approval rate: ~32% (7 approved de 22)
- Avg latency: ~2800ms
- Ultima decisao: ETHUSDT approved com conf=92 ("Setup de qualidade A")

## Tamanho do Banco

| Tabela              |    Rows |
|---------------------|---------|
| analysis_log        |   1,262 |
| paper_trades        |       4 |
| agent_trades        |      12 |
| scalping_trades     |       8 |
| pump_trades         |      14 |
| ai_decisions        |      22 |
| scalping_decisions  |     906 |
| scalping_audit_log  |     910 |

DB file size: 5.6 MB
