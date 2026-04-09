# Proposta de Melhorias no Agent Trader

Data: 2026-04-08
Status: PROPOSTA (nao implementar sem aprovacao)

---

## Diagnostico em 1 Frase

O Haiku recebe dados ja filtrados para parecer bons e nao tem informacao suficiente para discordar do sistema — funciona como carimbo, nao como validador.

---

## Melhoria 1: Adicionar Regime de Mercado ao Prompt

### O que mudar
Calcular ADX (Average Directional Index) no timeframe de 1h e enviar ao Haiku.

### Dados a adicionar no user message
```
Regime de mercado (1h):
  ADX: 18.5 (fraco -> mercado lateral/sem tendencia)
  ATR: 1.2% (volatilidade moderada)
  BB Width: 3.5% (Bollinger apertado)
```

### Regras a adicionar no system prompt
```
## Filtro de regime (OBRIGATORIO)
- ADX < 20 = mercado SEM TENDENCIA -> rejeite sinais de tendencia (BUY/SELL baseados em SMA cross)
- ADX 20-25 = tendencia FRACA -> exija confluencia excepcional (confidence minima 80)
- ADX > 25 = tendencia PRESENTE -> analise normal
- BB Width < 2% = mercado comprimido -> sinais de breakout podem ser validos, outros nao
```

### Impacto esperado
Eliminaria trades em mercado lateral (como os 3 LONGs + 3 SHORTs do dia 25/Mar que eram whipsaw em range).

---

## Melhoria 2: Reformular o Prompt para Incentivar Rejeicao

### Problema atual
O prompt diz "Prefira REJEITAR" mas depois diz "Se os indicadores estao bem alinhados, aprove".
O Haiku segue a segunda instrucao porque os dados ja vem filtrados para alinhar.

### Novo approach no system prompt
```
## Seu papel

Voce e o ULTIMO FILTRO antes da execucao. Seu trabalho principal e IMPEDIR trades ruins.
Uma boa taxa de rejeicao e 60-80% dos sinais.

## Regra de ouro
Na DUVIDA, rejeite. O custo de perder uma oportunidade e ZERO.
O custo de aprovar um trade ruim e real (dinheiro perdido).

## Escala de confidence CALIBRADA
- 90-100: Setup perfeito, todos os indicadores alinhados, tendencia forte confirmada. RARO (< 10% dos sinais)
- 70-89: Setup bom com pequenas ressalvas. Aprovavel se ADX > 25
- 50-69: Setup mediocre. REJEITE a menos que haja razao excepcional
- 0-49: Setup fraco. REJEITE sempre

## Benchmarks de calibracao
- Se voce esta aprovando mais de 40% dos sinais, esta sendo permissivo demais
- Se sua confidence media e > 80, esta sendo overconfident
- Um analista conservador real rejeitaria 7 de cada 10 sinais
```

### Impacto esperado
Forca o Haiku a usar confidence baixa por padrao e so subir com evidencia forte.

---

## Melhoria 3: Remover Ancoragem da Decisao do Sistema

### Problema atual
O Haiku recebe `Decisao do sistema: BUY` — isso ancora sua avaliacao.

### Proposta
Substituir:
```
Decisao do sistema: BUY
```
Por:
```
Direcao proposta: LONG
NOTA: esta e uma PROPOSTA do sistema de scoring, NAO uma instrucao.
Voce deve avaliar independentemente se esta direcao faz sentido.
```

Ou melhor ainda, **remover a decisao** e deixar o Haiku decidir a direcao:
```
Os indicadores sugerem que o sistema de scoring gerou um sinal.
Avalie os dados abaixo e decida: APROVAR (long/short) ou REJEITAR.
```

### Impacto esperado
Remove o vies de confirmacao. O Haiku precisa "descobrir" a direcao em vez de confirmar.

---

## Melhoria 4: Feedback Loop com Metricas de Calibracao

### Problema atual
O historico de trades e insuficiente para mudar comportamento (so 4 trades, win rate 50%).

### Proposta: adicionar metricas de calibracao ao prompt
```
## Suas metricas de calibracao (ultimos 30 dias)
- Sinais avaliados: 47
- Aprovados: 39 (83%) <- ALERTA: taxa de aprovacao acima de 40%
- Win rate dos aprovados: 15% <- ALERTA: seus trades aprovados estao perdendo
- Confidence media: 96.2 <- ALERTA: overconfident (esperado < 80)
- Trades com conf >= 90 que perderam: 8 de 10

REFLEXAO: Sua confidence nao corresponde a realidade.
Reduza drasticamente seus scores de confidence.
```

### Implementacao necessaria
1. Salvar TODAS as decisoes do Haiku (aprovadas E rejeitadas) em `ai_decisions`
2. Calcular metricas de calibracao periodicamente
3. Injetar essas metricas no prompt

### Impacto esperado
O Haiku recebe evidencia objetiva de que esta errado, forcando recalibracao.

---

## Melhoria 5: Veto por Correlacao

### Proposta: pre-filtro Python (sem Haiku)
```python
# Antes de enviar ao Haiku, verificar correlacao
if symbol in CORRELATED_GROUPS["btc_basket"]:
    # BTC, ETH, SOL sao do mesmo grupo
    existing = [s for s in state["positions"] if s in CORRELATED_GROUPS["btc_basket"]]
    if existing:
        # Ja tem posicao no grupo -> bloquear automaticamente
        return reject("Posicao correlacionada ja aberta: " + existing[0])
```

### Grupos sugeridos
```python
CORRELATED_GROUPS = {
    "btc_basket": {"BTCUSDT", "ETHUSDT", "SOLUSDT"},
    "altcoin_basket": {"BNBUSDT", "XRPUSDT", "DOGEUSDT"},
}
```

### Impacto esperado
Impede 3 posicoes identicas (como BTC+ETH+DOGE LONG do dia 25/Mar).

---

## Melhoria 6: Threshold Minimo de Confidence

### Proposta: subir threshold de auto-rejeicao
Atual (linha 794):
```python
if analyst["approved"] and analyst_confidence < 60:
    analyst["approved"] = False
```

Proposto:
```python
if analyst["approved"] and analyst_confidence < 75:
    analyst["approved"] = False
```

E adicionar threshold por regime:
```python
adx = signal_data.get("adx_1h", 0)
min_confidence = 85 if adx < 20 else 75 if adx < 25 else 70
if analyst["approved"] and analyst_confidence < min_confidence:
    analyst["approved"] = False
```

---

## Melhoria 7: Cooldown apos Whipsaw

### Proposta
Se o sistema fechou uma posicao por `opposite_signal` e abre imediatamente na direcao oposta,
aplicar cooldown de 2h no ativo.

```python
# Em check_agent_positions, apos fechar por opposite_signal:
if hit == "opposite_signal":
    state["cooldowns"][symbol] = datetime.now().isoformat()
    # Usar COOLDOWN_MINUTES existente (30min) ou criar WHIPSAW_COOLDOWN = 120min
```

### Impacto esperado
Evita o padrao LONG->opposite_signal->SHORT->loss que aconteceu 3 vezes.

---

## Melhoria 8: Considerar Trocar o Modelo ou Remover o Haiku

### Opcao A: Usar Sonnet em vez de Haiku
- Pro: Modelo mais capaz, melhor raciocinio
- Contra: 5-10x mais caro por chamada, mais lento
- Viavel se: limitar chamadas a ~20/dia

### Opcao B: Remover o Haiku e usar regras Python
- Pro: Deterministic, zero custo de API, sem "overconfidence"
- Contra: Perde flexibilidade da IA
- Viavel se: as regras forem bem calibradas

### Opcao C: Haiku como tiebreaker, nao como validador
- Pro: Usa IA so quando o scoring system esta indeciso (score 2.5-3.5)
- Contra: Menos chamadas = menos dados para calibrar
- Viavel se: scoring system for confiavel para extremos

### Recomendacao
**Opcao C** parece a mais equilibrada:
- Sinais fortes (score >= 4.0): aprovar automaticamente
- Sinais fracos (score < 2.5): rejeitar automaticamente
- Sinais borderline (2.5-4.0): enviar ao Haiku para desempate
- Isso reduz custo de API e limita o dano da overconfidence do Haiku

---

## Prioridade de Implementacao

| # | Melhoria | Impacto | Esforco | Prioridade |
|---|----------|---------|---------|------------|
| 1 | Regime de mercado (ADX) | ALTO | MEDIO | P0 |
| 2 | Reformular prompt | ALTO | BAIXO | P0 |
| 3 | Remover ancoragem | MEDIO | BAIXO | P0 |
| 6 | Subir threshold confidence | MEDIO | BAIXO | P0 |
| 7 | Cooldown apos whipsaw | MEDIO | BAIXO | P1 |
| 5 | Filtro de correlacao | MEDIO | MEDIO | P1 |
| 4 | Feedback loop calibrado | ALTO | ALTO | P1 |
| 8 | Repensar papel do Haiku | ALTO | ALTO | P2 |

### Sequencia recomendada
1. **Primeiro** (P0, ~1 sessao): Melhorias 2, 3 e 6 — mudancas no prompt e threshold, zero risco
2. **Segundo** (P0, ~1 sessao): Melhoria 1 — adicionar ADX ao pipeline de dados
3. **Terceiro** (P1, ~1 sessao): Melhorias 5 e 7 — filtros Python pre-Haiku
4. **Quarto** (P1-P2, ~2 sessoes): Melhorias 4 e 8 — feedback loop e repensar arquitetura

---

## Bug Critico Encontrado: Posicoes Orfas

### Problema
O bot.db principal tem 3 posicoes SHORT abertas desde 25-26/Mar que nunca fecharam.
O runtime/v2 tem 3 LONGs + 1 SHORT abertos desde 31/Mar que nunca fecharam.
O runtime/baseline tem 3 LONGs abertos desde 31/Mar que nunca fecharam.

**Total: 10 posicoes orfas em 3 bancos diferentes.**

### Causa provavel
Quando o bot foi migrado para a estrutura runtime/v2 e baseline, as posicoes do banco anterior ficaram "presas" no agent_state.json antigo. O novo bot criou novas posicoes sem fechar as antigas.

### Impacto
- Capital reportado esta ERRADO (mostra $10,021 mas deveria contabilizar SL das orfas)
- Win rate reportado esta ERRADO (mostra 50% mas deveria ser ~17% com as orfas)
- O bot acha que tem 3 posicoes abertas e nao abre novas (max 3)

### Acao recomendada
1. Executar `close_orphan_trades.py` (ja existe) para fechar posicoes orfas
2. Recalcular capital real considerando as perdas das orfas
3. Resetar agent_state.json para estado limpo antes de rodar novamente
