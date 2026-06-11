# Pré-registro — Medição Maker-Fill do v1.1 (forward + replay retroativo)

**Status:** SELADO 2026-06-10 (OK do Gabriel; emendas textuais incorporadas antes do commit, nenhum parâmetro alterado).
**Versão:** 1.1 (2026-06-10 — emendas: fee profile congelado, convergência BTC/ETH mecânica, nota spot/futures post-only, semântica do PF corrigida).
**Tipo:** medição de política de execução (instrumentação + contabilidade). **Não é experimento de edge novo, não é tuning do v1.1** (params congelados, estratégia intocada). Análogo metodológico do estudo fee-net (35fc717).
**Posição na fila:** não compete com a fila pós-pausa (sinal BTC funding segue 1º para experimentos de descoberta). Instrumentação não espera amostra.

> Contexto que motiva: 156 trades, PF bruto 1.35 → PF líquido taker 0.92 (-$44.50). Sensibilidade já conhecida: com maker 0.02 em *todos* os fills, net +$40.88 / PF 1.13 — mas esse número assume 100% de fill, ignorando seleção adversa (limit em sinal de confirmação de momentum preenche nos trades que voltam e perde os que disparam). Esta medição fecha exatamente essa lacuna.

---

## 1. Pergunta única (pré-registrada)

> O PnL líquido do v1.1 sobrevive quando entrada e take-profits tentam executar como maker, **contando como zero os trades cuja limit não preenche**?

Duas sub-perguntas derivadas, ambas respondidas pelo mesmo dataset:
a) Qual o fill rate real da entrada limit? b) Os trades não-preenchidos são sistematicamente os melhores (seleção adversa)?

## 2. Hipótese

- **H0:** a política maker perde os melhores trades; PnL líquido maker ≤ PnL líquido taker (a fee economizada não compensa os winners perdidos).
- **H1:** fração suficiente das entradas preenche; PnL líquido maker > taker e PF líquido maker ≥ 1.15.

Sem direção pré-comprometida de "salvação": qualquer resultado fecha a dúvida com honestidade. Resultado entre 1.0 e 1.15 = "curioso, não operável" — **arquiva sem rodada extra** (anti-relitígio).

## 3. População e pareamento (anti-confounder)

- Universo = **trades realmente abertos pelo paper executor** (não `momentum_decisions`, não sinais bloqueados — lição EXP-006/selection bias). Pareamento 1:1: cada trade taker real ganha uma sombra maker no mesmo sinal.
- **Limitação declarada:** não simula a dinâmica alternativa de slots (um não-fill liberaria `max_positions=1` para outro sinal). Medimos "maker nos mesmos trades", a comparação limpa e conservadora.

## 4. Regra de execução maker (travada — zero parâmetro livre)

| Item | Regra |
|---|---|
| Ordem | Limit post-only ao **preço de entrada real** (close do candle de confirmação `C`) |
| Validade | 2 candles 15m (`C+1`, `C+2`); sem fill → cancelada, trade perdido, PnL da política = 0 |
| Fill (LONG) | `low(C+i) < limit` **estrito** (tocar exato ≠ fill; proxy de fila). SHORT: `high(C+i) > limit` |
| Preço de fill | sempre o `limit` (sem melhora de preço em gap) |
| Níveis SL/TP | os mesmos do trade real (derivam do setup e a entry é a mesma) |
| Candle de fill | avalia **só SL** (worst-case: preço veio contra para preencher); TPs só a partir do candle seguinte |
| Candles seguintes | prioridade padrão do runner: SL > TP2 > TP1 |
| Timeout | mesma âncora do trade real (16 candles desde `C`) — fill tardio tem menos tempo, deliberado |
| Fees | entrada maker **0.02%**; TP1/TP2 limit maker **0.02%**; SL e timeout taker **0.05%** (canônica) |
| Fill de TP | mesma heurística do baseline (`high ≥ TP` p/ LONG) — só muda a fee; viés otimista declarado |

**Fee profile congelado no selo:** Binance USDⓈ-M Futures (paper), maker **0.02%/lado**, taker **0.05%/lado**, sem desconto BNB — espelha a fee canônica do lab (CONSTITUTION). Tiers maker/taker da Binance variam por VIP level e desconto BNB; qualquer mudança futura de tier/desconto/tabela ⇒ **novo estudo**, não alteração deste.

**Nota simulação vs implementação real:** o fill por candle usa *strict-through* como proxy conservador de fila — é regra de simulação, não de execução. Se um dia houver paper maker real, usar o tipo post-only do mercado operado: spot = `LIMIT_MAKER` (rejeitada se executaria imediatamente como taker); USDⓈ-M Futures = `LIMIT` com `timeInForce=GTX` (Good Till Crossing / Post Only). Não muda este teste.

Sensibilidades **reportadas mas não decisórias**: fill só em `C+1`; maker 0.01/0.03. Se a conclusão flipar entre sensibilidades → reportar como frágil.

## 5. Fases

- **Fase R (replay retroativo, kill barato):** aplicar a regra §4 aos 156 trades existentes via klines 15m históricos (REST). Roda assim que coletor passar nos testes. **Só pode matar, nunca aprovar**: o fill por low/high de candle é otimista (sem book/fila), então se *mesmo assim* o **PF líquido dos PnLs executados pela política** < 1.0 → encerra tudo, sela "v1.1 inviável também como maker".
- **Fase F (forward, julgamento):** sombra maker registrada em cada trade novo aberto pelo executor. Tabela própria (`momentum_maker_shadow`), zero mudança na estratégia/execução. Leitura única quando **N ≥ 80** trades pareados ou em **2026-07-31** (o que vier primeiro); N < 50 nessa data → inconclusivo por amostra.

## 6. Critérios (travados antes de qualquer dado)

GO (= "segunda conversa": candidato a paper maker real, **atrás da fila pós-pausa**; nunca = produção) exige **todos**, na Fase F:

1. **Fill rate de entrada ≥ 50%.**
2. **PF líquido dos PnLs executados pela política maker ≥ 1.15** (agregado). *Semântica:* não-fills valem 0 para PnL total, expectancy e Δ maker−taker (critério 3), mas são **neutros para PF por definição** (zeros não entram em ganhos nem perdas) — PF sozinho NÃO pune seleção adversa; ela é julgada pelos critérios 3–4 e pelas métricas de MFE dos não-preenchidos. Piso alto porque o fill simulado é otimista.
3. **ΔPnL líquido total maker − taker > 0**, calculado sobre **todos os sinais pareados**, com não-fills da política maker valendo 0; mesma janela, mesmos sinais.
4. **Captura de winners:** dos 10 maiores winners brutos do baseline na janela, a política preenche ≥ 5.
5. **Convergência de símbolo (mecânica):** BTC e ETH, avaliados separadamente na Fase F, precisam ambos de **PnL líquido da política ≥ 0 E PF líquido dos executados ≥ 1.00**. PF indefinido (sem perdas ou amostra insuficiente no símbolo) **não aprova** → inconclusivo/NO-GO. O piso 1.15 segue valendo só no agregado; este critério fecha a brecha "um símbolo esconde o prejuízo do outro".

Qualquer falha → NO-GO. Splits mensais: **só descritivos** (janela curta demais para critério). Métricas de seleção adversa sempre reportadas: PnL bruto médio preenchidos vs não-preenchidos, MFE dos perdidos.

## 7. Modos de falha esperados

1. **Seleção adversa (mais provável):** preenche os que voltam, perde os runners — detectada pelos critérios 3–4.
2. **Fill otimista mascarando NO-GO fino:** PF 1.0–1.15 real seria ≤1.0 vivo — coberto pelo piso 1.15 + kill da Fase R.
3. **Regime carregando a janela forward (junho-like):** mitigação parcial pelo critério 5 e splits descritivos; janela curta é limitação aceita e declarada.

## 8. Não-objetivos

Não tunar v1.1; não mexer em executor/estratégia; não reabrir Versões B (seletivo/score — respondida por EXP-006) e C (TF maior — respondida por EXP-014); não prometer renda (âncora 80/20); não furar fila pós-pausa.

## 9. Implementação (após selo, TDD, 1 módulo)

`momentum/maker_shadow.py` + tabela `momentum_maker_shadow` (trade_id, symbol, side, signal_ts, limit_price, filled, fill_candle, fill_ts, maker_net_pnl_pct, maker_exit_reason, taker_net_pnl_pct, mfe_pct, mae_pct, fee_model). Resolução de fills nos ciclos seguintes com a mesma `candle_fn` 15m. Replay retroativo como script offline (`scripts/replay_maker_shadow.py`) usando a MESMA função de simulação (sem duplicar lógica).
