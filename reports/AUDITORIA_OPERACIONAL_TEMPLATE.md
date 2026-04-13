# Auditoria Operacional - Template

Este arquivo define o template minimo para sair do modo "acho que" e
entrar no modo "decisao operacional".

Objetivo:

1. Medir expectancy bruta e liquida por sistema.
2. Separar resultado por regime, ativo e horario.
3. Medir executabilidade real (slippage, spread, atraso).
4. Testar robustez a pequenas mudancas.
5. Fazer ablacao para descobrir qual motor realmente carrega sinal.

## Regra de ouro

Use dois datasets, nao um:

1. `trade_audit_log`
   Uma linha por trade fechado.
   Serve para expectancy, custo, regime e executabilidade.
2. `signal_decision_log`
   Uma linha por oportunidade avaliada, incluindo bloqueios.
   Serve para funnel, ablacao e contribuicao marginal.

Sem o `signal_decision_log`, voce nao consegue responder:

- "o filtro ajudou ou so cortou frequencia?"
- "a IA melhora ou so aprova menos trades?"
- "funding/basis/liquidation carregam edge ou so maquiagem?"

## Template 1 - trade_audit_log

Uma linha por trade fechado, para todos os sistemas:

| Coluna | Tipo | Obrigatoria | Uso |
|---|---|---:|---|
| `trade_id` | TEXT | sim | ID unico do trade |
| `lifecycle_id` | TEXT | sim | ID do ciclo de vida completo |
| `system` | TEXT | sim | `paper`, `agent`, `scalping_v2`, `scalping_v2_1b`, `pump` |
| `strategy_family` | TEXT | sim | `trend_breakout`, `mean_reversion`, `microstructure`, `pump_event` |
| `strategy_variant` | TEXT | sim | nome curto da variante |
| `bot_id` | TEXT | sim | instancia runtime |
| `git_sha` | TEXT | sim | versao do codigo |
| `param_version` | TEXT | sim | versao do set de parametros |
| `symbol` | TEXT | sim | ativo |
| `side` | TEXT | sim | `LONG` ou `SHORT` |
| `signal_tf` | TEXT | sim | timeframe do sinal |
| `execution_tf` | TEXT | sim | timeframe de execucao/gestao |
| `opened_at` | TEXT | sim | timestamp de abertura |
| `closed_at` | TEXT | sim | timestamp de fechamento |
| `holding_minutes` | REAL | sim | duracao da posicao |
| `signal_price` | REAL | sim | preco no momento do sinal |
| `expected_entry_price` | REAL | sim | preco teorico usado na regra |
| `realized_entry_price` | REAL | sim | preco efetivo do fill |
| `entry_slippage_bps` | REAL | sim | slippage de entrada em bps |
| `expected_exit_price` | REAL | sim | preco teorico de saida |
| `realized_exit_price` | REAL | sim | preco efetivo de saida |
| `exit_slippage_bps` | REAL | sim | slippage de saida em bps |
| `spread_bps_est` | REAL | sim | spread estimado no momento |
| `signal_to_order_ms` | REAL | sim | atraso entre sinal e ordem |
| `fill_model` | TEXT | sim | `paper_close`, `paper_next_open`, `market`, `maker_sim`, etc |
| `capital_before` | REAL | sim | capital antes do trade |
| `capital_after` | REAL | sim | capital depois do trade |
| `position_size_usd` | REAL | sim | tamanho da posicao |
| `leverage` | INTEGER | sim | alavancagem |
| `risk_amount_usd` | REAL | sim | risco previsto no trade |
| `sl_price_init` | REAL | sim | stop inicial |
| `tp1_price_init` | REAL | nao | tp1 inicial |
| `tp2_price_init` | REAL | nao | tp2 inicial |
| `sl_distance_pct` | REAL | sim | distancia do stop em % |
| `rr_ratio_planned` | REAL | sim | RR planejado |
| `tp1_hit` | INTEGER | sim | 0/1 |
| `tp1_at` | TEXT | nao | timestamp do TP1 |
| `tp2_hit` | INTEGER | sim | 0/1 |
| `breakeven_armed` | INTEGER | sim | 0/1 |
| `exit_reason` | TEXT | sim | `stop_loss`, `take_profit`, `take_profit_2`, `timeout`, etc |
| `gross_pnl_pct` | REAL | sim | pnl antes de custos |
| `gross_pnl_usd` | REAL | sim | pnl bruto em USD |
| `fee_entry_bps` | REAL | sim | custo de fee de entrada |
| `fee_exit_bps` | REAL | sim | custo de fee de saida |
| `funding_cost_bps` | REAL | nao | custo de funding se houver |
| `borrow_cost_bps` | REAL | nao | custo de borrow se houver |
| `other_cost_bps` | REAL | sim | outros custos |
| `total_cost_bps` | REAL | sim | soma total dos custos |
| `net_pnl_pct` | REAL | sim | pnl liquido |
| `net_pnl_usd` | REAL | sim | pnl liquido em USD |
| `market_regime` | TEXT | sim | label final de regime |
| `adx_1h` | REAL | nao | snapshot do regime |
| `bb_width_1h_pct` | REAL | nao | snapshot do regime |
| `atr_1h_pct` | REAL | nao | snapshot do regime |
| `htf_trend` | TEXT | nao | contexto higher timeframe |
| `session_bucket` | TEXT | sim | `asia`, `europe`, `us`, `dead`, etc |
| `hour_bucket` | INTEGER | sim | hora UTC/local padronizada |
| `weekday_bucket` | INTEGER | sim | 0-6 |
| `event_bucket` | TEXT | sim | `none`, `macro_block`, `event_window`, etc |
| `asset_bucket` | TEXT | sim | `btc`, `eth`, `majors`, `alts`, etc |
| `signal_score` | REAL | nao | score principal |
| `signal_score_continuous` | REAL | nao | score continuo |
| `signal_strength` | TEXT | nao | `fraco`, `moderado`, `forte` |
| `opportunity_type` | TEXT | nao | `sinal`, `pre_sinal`, `observacao`, etc |
| `primary_source` | TEXT | nao | motor principal |
| `secondary_sources` | TEXT | nao | lista compacta de outros motores |
| `signal_subtype` | TEXT | nao | subtipo do sinal |
| `ai_gate_used` | INTEGER | sim | 0/1 |
| `ai_gate_approved` | INTEGER | sim | 0/1 |
| `risk_approved` | INTEGER | sim | 0/1 |
| `forced_entry` | INTEGER | sim | 0/1 |
| `notes` | TEXT | nao | observacao curta |
| `extra_json` | TEXT | nao | payload livre por sistema |

## Template 2 - signal_decision_log

Uma linha por oportunidade avaliada, mesmo que o trade nao seja aberto:

| Coluna | Tipo | Obrigatoria | Uso |
|---|---|---:|---|
| `decision_id` | TEXT | sim | ID unico da decisao |
| `cycle_id` | TEXT | sim | ID do ciclo |
| `timestamp` | TEXT | sim | quando a oportunidade foi avaliada |
| `system` | TEXT | sim | sistema |
| `strategy_variant` | TEXT | sim | variante da estrategia |
| `bot_id` | TEXT | sim | instancia runtime |
| `git_sha` | TEXT | sim | versao do codigo |
| `param_version` | TEXT | sim | versao de parametros |
| `symbol` | TEXT | sim | ativo |
| `side_candidate` | TEXT | sim | direcao candidata |
| `market_regime` | TEXT | sim | regime |
| `adx_1h` | REAL | nao | snapshot |
| `bb_width_1h_pct` | REAL | nao | snapshot |
| `atr_1h_pct` | REAL | nao | snapshot |
| `htf_trend` | TEXT | nao | contexto HTF |
| `signal_score` | REAL | nao | score principal |
| `signal_score_continuous` | REAL | nao | score continuo |
| `primary_source` | TEXT | nao | fonte principal |
| `all_sources` | TEXT | nao | fontes envolvidas |
| `signal_subtype` | TEXT | nao | subtipo |
| `opportunity_detected` | INTEGER | sim | 0/1 |
| `confluence_score` | REAL | nao | para sistemas com confluencia |
| `ai_used` | INTEGER | sim | 0/1 |
| `ai_approved` | INTEGER | sim | 0/1 |
| `risk_approved` | INTEGER | sim | 0/1 |
| `final_outcome` | TEXT | sim | `opened`, `ai_rejected`, `risk_blocked`, `confluence_block`, etc |
| `blocked_by` | TEXT | sim | `none`, `ai`, `risk`, `regime`, `cooldown`, `capital`, etc |
| `reason` | TEXT | sim | motivo resumido |
| `expected_entry_price` | REAL | nao | preco teorico |
| `sl_price_init` | REAL | nao | stop planejado |
| `tp1_price_init` | REAL | nao | tp1 planejado |
| `tp2_price_init` | REAL | nao | tp2 planejado |
| `rr_ratio_planned` | REAL | nao | RR planejado |
| `funding_rate` | REAL | nao | microestrutura |
| `ls_ratio_top` | REAL | nao | microestrutura |
| `ls_ratio_global` | REAL | nao | microestrutura |
| `liq_vol_long_usd` | REAL | nao | microestrutura |
| `liq_vol_short_usd` | REAL | nao | microestrutura |
| `oi_change_1h_pct` | REAL | nao | microestrutura |
| `oi_change_4h_pct` | REAL | nao | microestrutura |
| `basis_spread_pct` | REAL | nao | microestrutura |
| `ablation_without_ai` | INTEGER | sim | 0/1 |
| `ablation_without_funding` | INTEGER | sim | 0/1 |
| `ablation_without_basis` | INTEGER | sim | 0/1 |
| `ablation_without_liquidation` | INTEGER | sim | 0/1 |
| `ablation_primary_only` | INTEGER | sim | 0/1 |
| `notes` | TEXT | nao | observacao curta |
| `extra_json` | TEXT | nao | payload livre |

## Os 5 relatorios e as colunas minimas

### 1. Expectancy por sistema

Usa de `trade_audit_log`:

- `system`
- `strategy_variant`
- `net_pnl_pct`
- `gross_pnl_pct`
- `net_pnl_usd`
- `gross_pnl_usd`
- `total_cost_bps`
- `exit_reason`

### 2. Resultado por regime

Usa de `trade_audit_log`:

- `system`
- `market_regime`
- `adx_1h`
- `bb_width_1h_pct`
- `atr_1h_pct`
- `session_bucket`
- `hour_bucket`
- `weekday_bucket`
- `asset_bucket`
- `event_bucket`
- `net_pnl_pct`

### 3. Executabilidade real

Usa de `trade_audit_log`:

- `system`
- `symbol`
- `signal_price`
- `expected_entry_price`
- `realized_entry_price`
- `entry_slippage_bps`
- `expected_exit_price`
- `realized_exit_price`
- `exit_slippage_bps`
- `spread_bps_est`
- `signal_to_order_ms`
- `fill_model`

### 4. Robustez / sensibilidade

Precisa de `param_version` em ambos os datasets.

Usa de `trade_audit_log`:

- `param_version`
- `system`
- `strategy_variant`
- `net_pnl_pct`
- `rr_ratio_planned`
- `sl_distance_pct`

Usa de `signal_decision_log`:

- `param_version`
- `final_outcome`
- `blocked_by`

### 5. Contribuicao marginal / ablacao

Usa de `signal_decision_log`:

- `system`
- `strategy_variant`
- `final_outcome`
- `blocked_by`
- `ablation_without_ai`
- `ablation_without_funding`
- `ablation_without_basis`
- `ablation_without_liquidation`
- `ablation_primary_only`
- `primary_source`
- `all_sources`

## O que o banco atual ja grava

Ja existe boa base em:

- `paper_trades`
- `agent_trades`
- `pump_trades`
- `scalping_trades`
- `scalping_decisions`
- `scalping_audit_log`
- `scalping_outcome_labels`
- `market_microstructure`
- `ai_decisions`

Isso significa que voce ja consegue fazer parte do relatorio 1 e parte do 2
para scalping.

## O que ainda falta medir de forma consistente

Campos que hoje ainda sao incompletos ou ausentes para todos os sistemas:

- `param_version`
- `capital_before`
- `signal_price`
- `expected_entry_price`
- `realized_entry_price`
- `entry_slippage_bps`
- `expected_exit_price`
- `realized_exit_price`
- `exit_slippage_bps`
- `spread_bps_est`
- `signal_to_order_ms`
- `session_bucket`
- `hour_bucket`
- `weekday_bucket`
- `event_bucket`
- `asset_bucket`
- `gross_pnl_pct`
- `gross_pnl_usd`
- `total_cost_bps`
- `market_regime` padronizado em todos os sistemas
- flags de ablacao por motor/filtro

## Instrumentacao minima recomendada

Prioridade alta:

1. Adicionar `param_version`, `capital_before`, `signal_price` em todos os trades.
2. Persistir `expected_entry_price` e `expected_exit_price`.
3. Persistir `realized_entry_price` e `realized_exit_price` no paper/live.
4. Persistir `entry_slippage_bps`, `exit_slippage_bps`, `spread_bps_est`.
5. Padronizar `market_regime`, `session_bucket`, `hour_bucket`, `event_bucket`.

Prioridade media:

1. Persistir `gross_pnl_pct/usd` separado do liquido.
2. Persistir `total_cost_bps`.
3. Persistir flags de ablacao no `signal_decision_log`.

## Regra de corte operacional

Se um sistema nao conseguir preencher os campos minimos acima, ele ainda pode
rodar em paper, mas nao deve ser promovido como candidato principal.

Sem esses campos, o projeto continua forte em narrativa e fraco em decisao.
