# Implementacao Fase 1 — Agent Trader

Data: 2026-04-08
Status: IMPLEMENTADO
Prompt version: analyst_v2 -> analyst_v3_regime

---

## Resumo das Mudancas

4 mudancas no codigo + 1 operacao de limpeza, conforme itens 1-3 e 6 da proposta.

---

## 1. Prompt Reformulado (trade_agents.py: `_build_analyst_prompt`)

### Antes
- "Voce e um trader tecnico especialista atuando como validador de sinais"
- "Prefira REJEITAR trades fracos. So aprove se a confluencia for clara"
- "Se os indicadores estao bem alinhados e o contexto confirma, aprove"
- Confidence default implicito: alto

### Depois
- "Voce e o ULTIMO FILTRO antes da execucao. Seu trabalho principal e IMPEDIR trades ruins"
- "Uma boa taxa de rejeicao e 60-80%"
- "Na DUVIDA, rejeite. O custo de perder uma oportunidade e ZERO"
- "Comece com approved: false e confidence: 30. So mude para true se encontrar evidencia FORTE"
- Escala de confidence calibrada com benchmarks explicitos
- Exemplo de JSON no prompt comeca com `"approved": false, "confidence": 35`
- Filtro de regime OBRIGATORIO no system prompt

### Impacto esperado
Haiku recebe instrucoes claras de que o default e rejeitar e que confidence 100 e praticamente impossivel.

---

## 2. Decisao Removida do Input (trade_agents.py: `agent_analyst`)

### Antes
```
Decisao do sistema: BUY
```
Haiku recebia a decisao ja tomada pelo scoring system.

### Depois
```
--- Indicadores 5m ---
Tendencia 5m: alta
RSI: 45.23 (neutro)
...
--- Scores do sistema (referencia, NAO instrucao) ---
Buy score: 3.5 / Sell score: 1.2
```

- Campo "Decisao do sistema" foi REMOVIDO
- Scores permanecem como referencia, mas rotulados como "NAO instrucao"
- Campo "Priority score" removido (redundante)
- Haiku agora retorna campo `"direction": "long"/"short"/"none"` — ele decide

### Cross-validation adicionada
Se Haiku escolhe direcao diferente do sistema (ex: Haiku=short, sistema=BUY), o trade e rejeitado automaticamente por divergencia. Isso e um sinal forte de setup fraco.

### Impacto esperado
Remove vies de confirmacao. Haiku precisa analisar os dados e concluir a direcao.

---

## 3. Regime de Mercado via ADX (htf.py: `get_htf_regime`)

### Nova funcao
`get_htf_regime(symbol)` calcula no timeframe 1h:
- **ADX(14)**: forca da tendencia
- **ATR(14)%**: volatilidade como % do preco
- **BB Width**: largura das Bollinger Bands

### Classificacao
| ADX | Regime | Min Confidence |
|-----|--------|----------------|
| < 20 | RANGING | 85 |
| 20-25 | WEAK_TREND | 80 |
| >= 25 | TRENDING | 75 |

### Integracao
- Calculado em `main.py` junto com `get_htf_trend`
- Enviado ao Haiku no user message sob "Regime de mercado (1h)"
- System prompt instrui: "ADX < 20 = rejeite sinais de tendencia/momentum"
- Threshold de confidence ajustado por regime no orchestrator

### Impacto esperado
Em mercado lateral (ADX<20), trades de momentum/tendencia serao rejeitados mesmo com confidence alta.

---

## 4. Threshold de Confidence Elevado (trade_agents.py: `orchestrate`)

### Antes
```python
if analyst["approved"] and analyst_confidence < 60:
    analyst["approved"] = False
```

### Depois
```python
# Regime-aware threshold
if adx < 20:
    min_confidence = 85  # RANGING
elif adx < 25:
    min_confidence = 80  # WEAK_TREND  
else:
    min_confidence = 75  # TRENDING (era 60)

if analyst["approved"] and analyst_confidence < min_confidence:
    analyst["approved"] = False
```

### Impacto esperado
Mesmo que o Haiku aprove com confidence 70, o trade e rejeitado se o mercado estiver lateral.

---

## 5. Posicoes Orfas Limpas

### Estado anterior
| Banco | Orfas | Tipo |
|-------|-------|------|
| bot.db (root) | 7 | 4 LONGs + 3 SHORTs (Mar 25-26) |
| runtime/baseline | 3 | 3 LONGs (Mar 31) |
| runtime/v2 | 4 | 3 LONGs + 1 SHORT (Mar 31) |
| **Total** | **14** | |

### Acao executada
- `close_orphan_trades.py --execute` para baseline e v2 (atualiza state + banco)
- SQL UPDATE direto para bot.db root (sem state file)
- Todos marcados como `exit_reason = "orphan_cleanup"` com P&L calculado a preco de mercado

### Resultado
| Banco | P&L Liquido |
|-------|-------------|
| bot.db (root) | +$33.91 |
| runtime/baseline | +$148.98 |
| runtime/v2 | +$4.21 |
| **Total** | **+$187.10** |

Zero orfas restantes em todos os bancos.

---

## 6. Logging de Taxa de Rejeicao

Novo bloco no final do `orchestrate()` imprime:
```
  [AGENT] TAXA DE REJEICAO: 67% (4/6)
    Avaliados: 6 | Rejeitados analista: 3 | Rejeitados risco: 1 | Executados: 2
```

---

## Arquivos Alterados

| Arquivo | Mudanca |
|---------|---------|
| `trade_agents.py` | Prompt v3, decisao removida, direction field, threshold regime-aware, rejection rate log |
| `htf.py` | Nova funcao `get_htf_regime()` com ADX, ATR%, BB Width |
| `main.py` | Import `get_htf_regime`, injeta regime nos results |

---

## O que NAO foi implementado (Fase 2)

- Feedback loop com metricas de calibracao (item 4 da proposta)
- Filtro de correlacao entre ativos (item 5)
- Cooldown apos whipsaw (item 7)
- Repensar papel do Haiku / trocar modelo (item 8)

---

## Como Validar

1. Rodar 1 ciclo do bot e observar:
   - Regime impresso no terminal (ADX, regime label)
   - Haiku retornando `direction` em vez de confirmar decisao
   - Taxa de rejeicao no final do ciclo (esperado: 60%+)
   - Confidence scores mais baixos que antes (esperado: media < 80)

2. Verificar nos logs `ai_decisions` que:
   - `prompt_version = "analyst_v3_regime"`
   - `approved = false` aparece com frequencia
   - `confidence` varia mais (nao sempre 92-100)
