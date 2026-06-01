# PRÉ-REGISTRO — Funding Harvest (cash-and-carry delta-neutro)

- **ID:** EXP-FH-01
- **Selado em:** 2026-06-01
- **Status:** SELADO (critérios fixos antes do cálculo)
- **Classe:** captura de estrutura (NÃO preditivo) — delta-neutro
- **Apparatus:** cálculo contábil + walk-forward por símbolo (NÃO usa lab_harness/permutation — não é teste de predição)

## 1. Pergunta
Ficar delta-neutro (long spot + short perpétuo) e colher o funding rende **líquido de custos**? Em quais ativos, e só quando o funding passa de qual limiar?

## 2. Hipótese (falseável)
Existe ≥1 símbolo onde uma regra reativa — "ficar posicionado apenas quando o funding 8h ≥ T" — produz P&L líquido anualizado **positivo e consistente em sub-janelas temporais**, após custos realistas de transação.

## 3. Relação com o estado do lab (importante)
- **NÃO é continuação do EXP-011** (que testou funding como *preditor de direção* → NO-GO). Aqui o funding é *receita*, não sinal direcional. Paradigma diferente.
- **NÃO recarrega o gatilho de pausa de 90d**, que se aplica a estratégias preditivas estruturais. Esta é uma linha nova (arbitragem de taxa).
- Foi uma **escolha consciente de rumo do Gabriel** (2026-06-01), com expectativa calibrada ("sem pressa; 1 real/mês já é vitória; sem sorte"). Não é drift de retorno.

## 4. Dados
- `k_funding_rates` — núcleo (receita). ~92 dias, 14 símbolos, cadência 8h (3971 linhas). Janela: 2026-03-01 → 2026-06-01.
- `k_basis` (indexPrice, futuresPrice) — proxy de spot e análise de basis. **Só ~21 dias** → usado apenas na análise de sensibilidade, não no número principal.
- **Limitação cravada:** ~92d = um único regime de mercado (morno/lateral, funding seco). Resultado é **exploratório**, calibra o gatilho — não é veredito definitivo.

## 5. Mecânica e fórmula de P&L (cravada)
Posição: long 1 unidade spot + short 1 unidade perp, notional N (USD). Delta ≈ 0.
- **Receita de funding** (por episódio): `N × Σ funding_rate[t]`, somando os períodos 8h em que a posição esteve aberta (short perp recebe quando funding>0, paga quando <0).
- **Custo de transação:** `N × c`, com **c = 0,003 (0,30% round-trip)** = taker spot (0,10%) + taker perp (0,04%) na entrada e na saída. Taker é conservador; maker seria upside.
- **P&L líquido (principal):** `Receita_funding − Custo_transação`.
- **Componente de basis (sensibilidade, à parte):** `N × (basis_rate_entrada − basis_rate_saída)` nos 21d com dados — reportado separado, NÃO somado ao número principal.
- **Anualização:** `P&L_líquido / N / (dias_holding / 365)`. Aproximação linear (sem composição), anotada.

## 6. Regra reativa — limiar T cravado A PRIORI (anti-overfit)
- **T = break-even:** `T = c / H`, com **H = 90 períodos de 8h (30 dias)** de holding assumido. → `T = 0,003 / 90 = 0,0000333` = **0,00333% por 8h**.
- Interpretação: só entra quando o funding 8h corrente ≥ T, ou seja, quando o funding projetado em 30d paga o round-trip.
- **T é FIXO. Proibido varrer T e escolher o melhor in-sample** (forking-path). Sensibilidade a T, se feita, só via walk-forward (calibra no treino, testa no holdout).
- **Episódios:** períodos 8h contíguos com funding ≥ T formam um episódio. **1 round-trip de custo por episódio** (não por período).
- **Forward-only:** a decisão de abrir em t usa apenas funding observado até t; a receita é o funding de t em diante. Sem look-ahead.

## 7. Cenários
- **A — Passivo:** posicionado o período inteiro (piso/baseline).
- **B — Reativo:** posicionado só nos episódios com funding ≥ T.

## 8. Métricas de saída (por símbolo)
- P&L líquido total e anualizado (cenários A e B).
- Nº de episódios e duração média (cenário B).
- % do tempo com funding ≥ T (quão "ligável" é o harvester).
- Pior episódio (P&L mínimo) e fração de períodos com funding < 0.

## 9. Critérios GO/NO-GO (SELADOS antes de calcular)
- **GO-pesquisa** (existe captura real): ≥1 símbolo onde o cenário B dá P&L líquido anualizado **> 0 em CADA uma das 3 sub-janelas** temporais (consistência walk-forward) **E** com ≥3 episódios (não 1 sorte).
- **GO-econômico** (valeria capital real um dia): além do acima, líquido anualizado médio **> 8%** (benchmark = lending de stablecoin de baixo risco; abaixo disso não compensa o trabalho/risco). Número ajustável, mas fixo a partir daqui.
- **NO-GO-neste-regime** (cenário mais provável): nenhum símbolo passa → entregar (a) o limiar T, (b) a frequência com que o funding ficou ≥ T por símbolo. Conclusão: "infra fica pronta, dormindo, até o regime pagar". **NO-GO aqui NÃO mata a ideia** — calibra o gatilho.

## 10. Riscos da estratégia REAL (fora do escopo do estudo contábil)
Liquidação da perna short em disparada de preço; descasamento spot-perp (basis risk); custo de rolagem/rebalanceio; risco de corretora. Entram só na fase de execução, muito depois.

## 11. Próximos passos condicionais
- **GO** → definir regra operacional + paper trade delta-neutro (exige montar suporte a spot, que o bot não tem hoje).
- **NO-GO** → arquivar com o T calibrado; opcionalmente, um monitor que avisa quando o funding de algum símbolo cruza T (o "despertador do harvester").

## 12. RESULTADO (2026-06-01) — NO-GO neste regime

Rodado sobre ~90d (270 fundings 8h/símbolo, 14 símbolos). Veredito pelos critérios selados:
- **GO-pesquisa: NENHUM** — nenhum símbolo teve líquido > 0 nas 3 sub-janelas.
- **GO-econômico: NENHUM.**

Números-chave (cenário passivo = teto otimista, buy-and-hold cego):
- Melhor: LINK +2,4%/ano, AVAX +0,9%. Maioria entre −3% e +1%. BTC −1,3%, ETH −0,8%.
- Mesmo o teto (LINK +2,4%) fica abaixo de lending de stablecoin (~5-8%) — e nem era capturável sem prever qual símbolo lideraria.

Achado de design (bônus): o cenário REATIVO ficou MUITO pior (−35% a −70%/ano) que o passivo. Causa: T break-even baixo (0,0033%/8h) faz o funding cruzar o limiar dezenas de vezes → 30-60 micro-episódios → cada um paga 0,3% de custo cheio → custos destroem tudo. Lição: regra reativa útil precisaria de holding mínimo (não sair a cada cruzamento). Isso NÃO salvaria o veredito: o prêmio bruto em si está seco.

Conclusão: o regime atual (mar-jun/2026, funding seco) NÃO paga funding harvest líquido de custos. A lógica é sólida; falta o regime. Infra pronta (código testado em `scripts/funding_harvest_study.py` + `tests/test_funding_harvest_study.py`, 11 testes; T calibrado). Próximo passo natural = "despertador" (monitor que avisa quando o funding fica gordo), NÃO arriscar capital agora.

---
*Selado por Gabriel + Claude (sócio técnico) em 2026-06-01. Critérios fixos, veredito honesto registrado no mesmo dia.*
