# Briefing — EXP Event Mining (garimpo disciplinado de eventos exógenos)

**Data do desenho:** 2026-06-12 · **Autores:** Gabriel + Claude (sessão home, brainstorm conjunto)
**Revisão:** v1.1, 2026-06-12 — passada adversarial multi-agent (lentes: temporal/lookahead,
estatística, dados reais do banco) ANTES da execução; todos os achados MATA/ENVIESA incorporados.
**Status:** aguardando execução · **Validação final:** forward 13/06 → 13/07, julgada junto com o re-teste R2

---

## 1. Sua missão

Você é a sessão Claude Code executora deste experimento no `~/crypto_ai_bot`. A missão: rodar um
garimpo combinatório **disciplinado** sobre os dados exógenos coletados (funding, basis,
long/short ratio, open interest — liquidações e taker ficam para 13/07, ver Seção 5), procurando
**estados discretos após os quais o retorno das próximas horas tem expectancy líquida positiva e
robusta** — "estrutura pagante: engatilhou, P(lucro) > P(perda)".

A moldura da Seção 5 foi desenhada, aprovada por Gabriel e revisada adversarialmente ANTES de
qualquer retorno ser olhado. Ela está **travada**: você não a relaxa em hipótese alguma, nem se
um resultado "quase passar". Pode apertá-la (registrando o porquê). "Quase passou" morre
registrado como quase. Torcemos por resposta limpa — GO ou NO-GO — nunca por GO.

## 2. Como trabalhar

- **Interativo com checkpoints.** Ao fim de cada fase, PARE e apresente o checkpoint. Não siga
  sem OK explícito do Gabriel.
- **Formato fixo de checkpoint:** resumo em linguagem acessível (≤ 15 linhas, sem jargão
  não-explicado) + "decisão a tomar" em 1 frase. Gabriel pode pedir "explica mais simples" —
  reformule sem reclamar. Cheque entendimento em decisões grandes.
- **Poder de fogo:** use o agent `performance-analyst` para SQL/análise; `Explore` para achar
  código existente; e a Workflow tool (multi-agent, Gabriel autoriza orquestração ultracode por
  este briefing) nos fan-outs da F2 (1 agent por família de evento) e F3 (1 agent por ataque de
  robustez). Fora dos fan-outs, sessão normal — não desperdice tokens.
- **Hook pytest roda sozinho** ao editar `.py` — não rode a suíte manualmente.
- **Commits:** código e docs separados; mostre o diff e aguarde OK antes de commitar.
- Scripts e artefatos em `research/event_mining/`. Leia `docs/EXPERIMENT_REGISTRY.md` e use o
  próximo número EXP livre a partir do registro deste briefing.

## 3. Contexto do lab (para não reinventar erros)

- **Momentum v1.1** (paper, única ativa): edge bruto não sobrevive ao custo — 144 trades,
  +95.83 USD gross (PF 1.32) → −41.54 net (PF 0.88) com taker 0.05%/lado. Três NO-GOs de tuning
  (BE50, PB25, hourly sizing) selaram: **não tunar v1.1**. Este EXP não é resgate do v1.1.
- **Pré-EXP R2 (OI/LSR contínuo vs preço):** 🟡 NO-GO em 07/06 por dois métodos independentes;
  re-teste marcado ~13/07 com dados frescos. Regra da casa: **não repetir procurando GO.** Por
  isso a grade contínua feature→retorno NÃO entra aqui, e a validação deste garimpo é
  forward-only no mês que ainda não existe.
- **Reorientação do lab (01/06):** capturar estrutura que paga, não prever preço.
- **EXP-011 (funding H1):** NO-GO de margem (46.1 vs 50 bps), mas o sinal de BTC sobreviveu à
  correção de multiplicidade — por isso BTC tem agregação separada na grade (com aritmética de
  viabilidade honesta: várias células BTC morrem por N; isso é esperado, não falha).
- Fee de referência da casa: taker 0.05%/lado. `SINGLE_SIDE_FEE_PCT=0.04` global está
  desatualizado — não o use como verdade.

## 4. Armadilhas de medição (obrigatórias — itens 5–10 CONFIRMADOS no banco em 12/06)

1. **`k_liquidations.side`:** `BUY` = long liquidado (cascata para baixo); `SELL` = short
   liquidado (squeeze para cima). Confirmado 3×. Não inverta.
2. **`momentum_decisions.outcome='trade'` NÃO é execução real.** Trades reais =
   `momentum_trades`. Shadow = `momentum_shadow_outcomes` — e comparação blocked vs executed
   carrega selection bias (confounder de estado prévio); trate como descritivo, nunca causal.
3. **Movimento de preço vem de `k_prices`** — mas veja o item 8: o close gravado é parcial.
4. **v1.1 decide em candle 15m parcial** — entry não é o close do candle do sinal.
5. **Janelas reais medidas (declarar sempre):** `k_prices`/`k_ratios` desde 09/04 (1h exata,
   14 símbolos, sem gaps); `k_open_interest` desde 15/04; `k_basis` desde 11/05 (31 dias);
   `k_funding_rates` nativo de 8h desde 01/03, janela efetiva pós-join com preços = 09/04
   (~209 obs/símbolo); `k_liquidations` REAL só desde 08/06 12:36 (~3,7 dias);
   `k_prices.taker_buy_base` real só desde 01/06 — antes disso são **zeros literais** (83,7%
   das linhas), não NULL: filtrar `> 0`.
6. **Granularidade mínima de evento = 1 hora** (exceto FUND: grade nativa de 8h).
   `market_microstructure` grava a cada ~5–13 min → deduplicar se usada.
7. **`market_microstructure`: 96,5% das linhas têm `liquidation_is_proxy=1`** (dado real só
   13–15/04, ~52h) e a tabela cobre só **6 dos 14 símbolos**. NÃO é fonte da grade — só
   cross-check. Fonte de liquidação = exclusivamente `k_liquidations`.
8. **`k_prices.close_price` é PARCIAL:** o coletor usa INSERT OR IGNORE e grava o bucket da
   hora corrente no minuto :05 com ~5 min de vela, sem nunca atualizar (~66% das linhas com
   lag < 400 s). `close_price` NÃO é o close da hora. Preço de referência correto = `open_price`
   do bucket seguinte (invariante iv da F1).
9. **`k_liquidations.event_ts` está em MILISSEGUNDOS**; as demais k_* em segundos Unix. Join
   direto retorna zero linhas silenciosamente. Dividir por 1000, com teste automatizado de
   unidade. (Relevante na re-entrada de LIQ em 13/07.)
10. **`k_ratios` tem 2 linhas por bucket** (`source` = `top_position` e `global_account`).
    GROUP BY sem filtro de source dobra médias e somas. Pivotar por source no ETL.

## 5. Moldura fria (PRÉ-REGISTRO — imutável após CP0)

**Pergunta registrada:** existe estado discreto nos dados exógenos após o qual o retorno
forward (1h/4h/24h) tem expectancy líquida positiva e robusta?

### Grade de eventos (fechada)

| Família | Gatilho (por símbolo) | Fonte |
|---|---|---|
| FUND+ / FUND− | funding ≥ p95 / ≤ p5 do símbolo, na **grade nativa de 8h** (1 funding period extremo = 1 evento) | `k_funding_rates` |
| BASIS+ / BASIS− | basis ≥ p95 / ≤ p5 (grade horária) | `k_basis` |
| LSR-TOP-SQZ | \|Δ1h\| do ratio ≥ p95, série `top_position` | `k_ratios` |
| LSR-GLB-SQZ | \|Δ1h\| do ratio ≥ p95, série `global_account` | `k_ratios` |
| OI-SHOCK | \|ΔOI 1h\| ≥ p95 | `k_open_interest` |

**Diferidas para o re-teste de 13/07** — morte declarada por aritmética de dados, não por
resultado: **LIQ-LONG / LIQ-SHORT** (`k_liquidations` real tem ~3,7 dias hoje; em 13/07 terá
~5 semanas) e **TAKER-IMB** (taker real só desde 01/06). Re-entram com esta mesma moldura.

- **Horizontes:** +1h, +4h, +24h, medidos a partir do preço de referência (invariante iv:
  `open_price` do bucket T+1).
- **Um teste BICAUDAL por célula** (não long/short separados — lados espelhados são
  estruturalmente redundantes e só inflam a multiplicidade). A direção da descoberta = sinal da
  média observada, registrada na mini-spec e **travada** para a validação forward.
- **Agregações:** pooled (14 símbolos) primário; BTC isolado secundário. Por-símbolo só como
  robustez, nunca célula promovível.
- **EPISÓDIO (unidade de inferência do pooled):** cluster temporal de eventos da mesma família
  com gap < max(24h, horizonte), via single-linkage. Eventos macro disparam em bloco nos 14
  símbolos correlacionados — 30 eventos podem ser 3 episódios disfarçados; toda inferência
  estatística reamostra EPISÓDIOS, nunca eventos individuais.
- **Cooldown anti-pseudo-replicação:** rolante, first-event-then-skip, 24h por símbolo+família.
- **Multiplicidade:** 7 famílias × 3 horizontes × 2 agregações × 1 teste bicaudal = **42
  células** a priori. Reportar a contagem EXATA de testes rodados, o nº esperado de falsos
  positivos a 5%, e os **q-values de Benjamini-Hochberg (FDR 10%) como CONTEXTO obrigatório no
  CP2 — não como gate**: com N~30–50 e vol cripto, BH-gate teria poder ≈ 0 e mataria o
  experimento à nascença por design. A proteção dura contra falso positivo é a validação
  forward de 13/07, que é o juiz declarado deste desenho.

### Régua "pagante" (todas simultâneas, por célula)

a. **econômica:** \|média\| ≥ **25 / 35 / 50 bps brutos** em +1h / +4h / +24h (escalonada pela
   vol do horizonte — régua única seria decorativa em 24h e impossível em 1h) E retorno líquido
   **> 0** após custo de 20 bps (taker 10 round-trip + 10 slippage);
b. **estatística:** \|t\| ≥ 2.0 com inferência cluster-robusta por EPISÓDIO — p-value por
   bootstrap percentil de episódios (10.000 reamostragens, estatística = média líquida da
   célula, bicaudal). **Teste congelado aqui** — a sessão executora não escolhe método depois
   de ver dados;
c. **amostra:** N ≥ 30 eventos pós-cooldown **E** N_episódios ≥ 10;
d. **concentração:** top-3 EPISÓDIOS respondem por < 50% do retorno agregado;
e. **estabilidade:** mesmo sinal de média em ≥ 2 dos 3 terços temporais; se a densidade de
   eventos diferir > 2× entre terços (p95 global em série não-estacionária concentra eventos no
   fim — confirmado: a média do LSR de BTC saltou de 0,83 para 1,15 em meados de maio), exigir
   **3/3**. Régua (e) só se aplica a fontes com ≥ 45 dias; BASIS (31d) carrega flag
   "terço-fraco" em qualquer relatório.

### Regras de regime do experimento

- Critério só aperta, nunca afrouxa, após CP0.
- Células LSR-* e OI-SHOCK tangenciam o território do R2: registram hipótese normalmente, mas
  (como todas) só validam em 13/07 — nenhum GO antecipado.
- Exceção de lookahead declarada: o threshold p95 é calculado uma vez sobre a janela de
  descoberta inteira. Em compensação o valor numérico congela na mini-spec e a validação de
  13/07 roda com ele fixo — zero lookahead na prova. O CP2 reporta, por célula, a fração de
  eventos pertencente ao episódio dominante (detecta "evento" degenerado em "estar no episódio X").
- Nenhum resultado deste garimpo vira operação, sizing ou mudança no bot. O produto final é
  **hipótese selada aguardando validação forward**.

### Anexo A — decisões de implementação congeladas (zero graus de liberdade pós-dados)

1. p95 = percentil empírico com interpolação linear, por símbolo, sobre a janela inteira
   disponível da fonte.
2. FUND opera na grade nativa de 8h: um funding period extremo = 1 evento, nunca 8 horas-evento.
3. Borda: evento sem retorno forward completo no horizonte → descartado daquele horizonte
   (não truncar, não imputar).
4. Pooled: equal-weight por evento nas médias; inferência sempre por episódio (régua b).
5. Métrica primária = média simples (sem winsorizar); winsorização a 1% é ataque da F3.
6. Universo = os 14 símbolos de `k_prices`, listados nominalmente no CP0.
7. Fonte da grade = exclusivamente tabelas `k_*`; `market_microstructure` só cross-check.
8. LSR: as duas séries (`top_position`, `global_account`) são famílias separadas pré-registradas
   — não uma escolha a fazer depois.
9. Cooldown rolante first-event-then-skip (não janela de calendário).
10. `taker_buy_base`: filtrar `> 0` (zeros literais pré-01/06) — relevante na re-entrada de 13/07.

## 6. Fases e checkpoints

Formato de TODO checkpoint: resumo acessível ≤ 15 linhas + "decisão a tomar" em 1 frase +
aguardar OK explícito do Gabriel.

### F0 — Inventário (sem olhar retornos!)
Confirmar as janelas da Seção 4 item 5; listar os 14 símbolos nominalmente; contagem de eventos
candidatos por família/símbolo com p95 (pós-cooldown) **e por episódio no pooled**; contagem de
eventos por terço temporal por família (dispara a regra 2×→3/3 da régua e); aritmética de
viabilidade das células BTC. Células com N < 30 ou N_episódios < 10 morrem aqui — antes de
qualquer resultado.
**CP0:** grade final viável apresentada → Gabriel ratifica → **grade congela**.
⚠ Proibido calcular qualquer retorno forward nesta fase — inventário é contagem, não preview.

### F1 — Dataset de eventos (ETL)
Script em `research/event_mining/` que extrai eventos da grade congelada e anexa retornos
forward. **Invariantes com teste automatizado:**
(i) evento em t usa apenas dados ≤ t; (ii) retorno usa apenas dados > t; (iii) cooldown sem
duplicatas; **(iv) preço de referência = `open_price` do bucket T+1 de `k_prices` — proibido
usar `close_price` como close real (é parcial, Seção 4 item 8)**; (v) clusterização de
episódios reprodutível (mesma entrada → mesmos clusters).
**CP1:** relatório de sanidade — N por célula E por episódio, janelas declaradas, distribuição
temporal dos eventos (episódio dominante visível a olho), 3 eventos spot-checked manualmente
contra dados crus (mostrar as linhas).

### F2 — Varredura (descoberta)
Por célula: média bruta/líquida, t cluster-robusto por episódio (régua b), q-value BH
(contexto), N e N_episódios, fração do episódio dominante, terços temporais. Fan-out
multi-agent: 1 agent por família. Em paralelo, a **lente v1.1** (diagnóstica): anexar a cada
trade de `momentum_trades` (158) e `momentum_shadow_outcomes` (1004) o estado exógeno mais
recente DISPONÍVEL antes da entrada — join por disponibilidade (último bucket de `k_*` com
timestamp ≤ entry), lembrando que os valores k_* são snapshots de abertura de hora (staleness
de até ~55 min, declarar); fontes = tabelas `k_*` (14 símbolos; `market_microstructure` cobre
só 6/14, não usar). Reportar se winners/losers se separam por estado. É diagnóstico, NÃO vira
filtro do v1.1; se gritar, vira hipótese selada para 13/07 como as demais.
**CP2:** relatório de descoberta — top células com as 5 réguas + q-values, contagem total de
testes, falsos positivos esperados, fração de episódio dominante por célula, achado da lente v1.1.

### F3 — Robustez adversarial (top-K, K ≤ 3)
Só células que passaram TODAS as réguas entram. Fan-out: 1 agent por ataque, com a instrução
literal "tente derrubar esta hipótese":
threshold ±20% · excluir top-3 EPISÓDIOS · leave-one-symbol-out (pooled) · custo 2× (40 bps —
proxy de slippage condicional: spreads explodem exatamente quando o gatilho dispara) ·
winsorização a 1%. Leitura opcional (não gate): de-meaning pelo retorno do BTC, para separar
"efeito do evento" de "beta de mercado".
Sobrevive quem passa em todos os ataques-gate.
**CP3:** veredicto por hipótese — sobreviveu / morreu em qual ataque.

### F4 — Seladura
Por sobrevivente: mini-spec EXP-0XX com gatilho exato (threshold numérico congelado), direção
(sinal travado), horizonte, preço de referência (invariante iv), teste estatístico congelado,
custo assumido, critério GO/NO-GO **numérico** pré-registrado para 13/07, N mínimo esperado no
mês forward, e plano de re-entrada das famílias diferidas (LIQ, TAKER) com esta mesma moldura.
Entrada no `docs/EXPERIMENT_REGISTRY.md`, commit (código e docs separados, diff antes, OK do
Gabriel). Zero sobreviventes também é resultado: sela NO-GO da rodada no registry com a
contagem de multiplicidade — resposta limpa.
**CP4:** aprovação final do Gabriel.

## 7. O que este EXP NÃO é

- Não é tuning/resgate do momentum v1.1 (estrada com 3 NO-GOs).
- Não é re-teste antecipado do R2 (marcado para 13/07).
- Não promove nada a operação — nem paper novo antes da validação forward.
- Não é caça a q-value: BH é contexto; o juiz com dente é o forward de 13/07.
- Não relaxa critério diante de "quase". GO aqui = hipótese selada aguardando 13/07, só isso.
