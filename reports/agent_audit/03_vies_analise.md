# Analise de Vies do Agent Trader (Claude Haiku)

Data da auditoria: 2026-04-08

---

## 1. Taxa de Aprovacao vs Rejeicao

### Dados observados

A tabela `ai_decisions` nao existia no banco principal (bot.db) e esta vazia no runtime/baseline. Portanto, nao temos log direto das decisoes do Haiku (aprovadas + rejeitadas).

**O que podemos inferir:**
- bot.db: 7 posicoes abertas em ~25 horas (25/mar 02:08 a 26/mar 03:26)
- Dos 6 simbolos monitorados (BTC, ETH, SOL, BNB, XRP, DOGE), 4 tiveram posicoes abertas
- Nenhum sinal foi rejeitado que esteja registrado no banco

**Estimativa de taxa de aprovacao: provavelmente 80-100%.**

O Haiku nao parece estar rejeitando sinais — quando o sistema de scoring gera BUY/SELL, o Haiku quase sempre aprova.

### Evidencia: Confidence scores

| Trade | Confidence | Significado |
|-------|------------|-------------|
| BTCUSDT LONG #1 | 100 | Maximo possivel |
| DOGEUSDT LONG | 100 | Maximo possivel |
| ETHUSDT LONG | 100 | Maximo possivel |
| DOGEUSDT SHORT | 92 | Quase maximo |
| BTCUSDT SHORT | 92 | Quase maximo |
| ETHUSDT SHORT | 100 | Maximo possivel |
| XRPUSDT SHORT | 100 | Maximo possivel |

**Media: 97.7/100 — o Haiku da confidence proxima a 100 em TODOS os trades.**

---

## 2. Vies #1: "Rubber Stamp" (Carimbo Automatico)

### O problema central

O Haiku esta funcionando como um **carimbo de aprovacao**, nao como um validador critico. Evidencias:

1. **Confidence 100 em 5 de 7 trades** — nenhum analista real daria confidence 100 em trades de 5min
2. **Confidence 92 nos outros 2** — mesmo o "pior" score e muito alto
3. **Nenhuma rejeicao registrada** no banco de dados

### Por que isso acontece

O prompt diz "Prefira REJEITAR trades fracos", mas:
- Os dados que o Haiku recebe ja vem **pre-filtrados** pelo scoring system (so chegam BUY/SELL com score >= 3.0/5.5)
- O prompt mostra "Decisao do sistema: BUY" — isso **ancora** a resposta do Haiku na direcao proposta
- O Haiku recebe buy_score/sell_score e confidence_score que ja sao altos (so passaram o filtro se eram bons)
- O prompt pede "Se os indicadores estao bem alinhados e o contexto confirma, aprove" — os indicadores ja foram selecionados para alinhar

**Em resumo: o Haiku recebe dados ja filtrados para parecer bons, e confirma que parecem bons.**

---

## 3. Vies #2: Whipsaw por Opposite Signal

### O problema

3 de 4 trades fechados sairam por `opposite_signal`, nao por SL ou TP:
- DOGE LONG: saiu por opposite -> imediatamente abriu SHORT
- BTC LONG: saiu por opposite -> imediatamente abriu SHORT
- ETH LONG: saiu por opposite -> imediatamente abriu SHORT

**Sequencia tipica:**
1. Sistema gera BUY -> Haiku aprova (conf 100) -> abre LONG
2. ~20h depois, sistema gera SELL -> fecha LONG com prejuizo -> abre SHORT
3. SHORT fica orfao (bot parou de rodar)

### Impacto

- Perde nas duas pontas: compra no topo, vende no fundo
- Gera 2x trades (e 2x fees) sem ganho
- Haiku aprova AMBAS as direcoes com confidence alta — nao percebe a contradicao

---

## 4. Vies #3: Sem Nocao de Regime de Mercado

### O problema

O Haiku nao recebe informacao sobre regime de mercado:
- Nao sabe se o mercado esta em range (sideways)
- Nao sabe se a volatilidade esta alta ou baixa
- Nao sabe o ADX (forca da tendencia)

### Consequencia

Em mercado lateral, o scoring system gera sinais de BUY e SELL alternados (whipsaw).
O Haiku nao tem como distinguir "tendencia real" de "ruido em range" porque nao recebe ADX.

Periodo dos trades (25-26 Mar): BTC oscilou entre ~70K-71K (range de ~1.5%). Isso e mercado lateral por qualquer metrica, mas o Haiku aprovou LONGs e SHORTs com confidence 100.

---

## 5. Vies #4: Overconfidence Sistematica

### O que significa confidence 100

No contexto do prompt, confidence 100 deveria significar "absolutamente certo, confluencia perfeita, zero red flags". Na pratica:

- Trade de DOGE com RSI neutro e sem breakout -> confidence 100
- Trade de ETH que perdeu -> confidence 100
- Nenhum trade com confidence abaixo de 92

### Comparacao com realidade

| O que o Haiku diz | O que aconteceu |
|-------------------|-----------------|
| Confidence 100 | 2 de 5 trades com conf 100 perderam |
| Setup "A" (provavel) | Nenhum trade atingiu TP (exceto 1) |
| "Confluencia clara" | Sinais inverteram em 20h |

### Causa raiz

O Haiku e um modelo pequeno e rapido otimizado para seguir instrucoes, nao para analise critica.
Quando recebe dados numericos que "parecem bons" (score 3+, htf_aligned=True), ele simplesmente concorda.
O modelo nao tem capacidade real de avaliar se um setup de 5m e de fato forte.

---

## 6. Vies #5: Posicoes Correlacionadas

### O problema

No dia 25/Mar, o Haiku aprovou simultaneamente:
- BTCUSDT LONG (conf 100)
- ETHUSDT LONG (conf 100)  
- DOGEUSDT LONG (conf 100)

BTC, ETH e DOGE sao altamente correlacionados. Isso e essencialmente 3x a mesma aposta.
Quando o mercado caiu, TODAS as 3 posicoes perderam juntas.

O Haiku nao tem informacao sobre correlacao entre ativos e nao alerta sobre concentracao de risco.

---

## 7. Vies #6: Feedback Loop Ineficaz

### O que existe

O prompt inclui historico dos ultimos 5 trades (adicionado em `agent_analyst()`, linha 322):
```
Ultimos N trades:
  SYMBOL TYPE -> +/-X.XX%
```

### Por que nao funciona

1. Com apenas 4 trades no historico (2W/2L = 50%), nenhum trigger de cautela e ativado
2. O trigger de cautela so ativa com >= 3 perdas CONSECUTIVAS
3. As perdas estao intercaladas com wins, entao o sistema nunca fica "cauteloso"
4. Mesmo quando ativado, o Haiku so precisa dar confidence > 75 para aprovar (ele da 92-100)

---

## 8. Resumo dos Vieses

| Vies | Severidade | Descricao |
|------|-----------|-----------|
| Rubber Stamp | CRITICA | Haiku aprova quase tudo com confidence 92-100 |
| Whipsaw | ALTA | Aprova LONGs e SHORTs alternados sem perceber range |
| Sem Regime | ALTA | Nao distingue trending de ranging/choppy |
| Overconfidence | ALTA | Confidence sempre perto de 100 independente da qualidade real |
| Correlacao | MEDIA | Aprova posicoes correlacionadas sem alertar |
| Feedback ineficaz | MEDIA | Historico de trades nao muda comportamento do Haiku |
