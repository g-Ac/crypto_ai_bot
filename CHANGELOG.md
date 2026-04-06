# CHANGELOG — Crypto AI Bot

Registro de alteracoes por sessao. Mais recente no topo.

---

## 2026-04-06 — Dashboard AI Brain + Roadmap

### O que foi feito

**Nova tab "AI Brain" no dashboard** (dashboard_server.py + templates/index.html)

Backend — 5 funcoes novas:
- `_get_raw_ai_decisions(limit)` — query direta na tabela ai_decisions
- `_collect_trade_reviews(limit)` — escaneia runtime/{BOT_ID}/trade_reviews/ por JSONs de review
- `_read_pattern_memory()` — le pattern_memory_report.json, normaliza tuples do Counter em dicts
- `_read_validation_audit()` — le validation_audit_report.json, extrai metricas flat por sistema
- `_build_ai_brain_payload()` — orquestra tudo numa unica resposta

Rota nova: GET /api/ai-brain
Integrado ao _build_status() — atualiza automaticamente via AJAX polling

Frontend — Tab 5 "AI Brain" com 4 secoes:
1. KPI Bar: Total Decisions, Approval Rate, Avg Confidence, Avg Latency
2. Decision Log: tabela com time, symbol, system, model, approved (verde/vermelho), confidence, latency, reasoning
3. Grid 2 colunas:
   - Trade Reviews: cards com classificacao colorida, root causes, licao
   - Pattern Memory: barras de frequencia para mistakes, lessons, root causes
4. Validation Audit: tabela com metricas por sistema (win rate, PF, expectancy, drawdown)

CSS: ~100 linhas novas (.review-item, .classification-badge, .pattern-bar, .ai-approved/.ai-rejected, .sys-indicator)
JS: ~170 linhas novas (renderAiBrainKpis, renderAiDecisionsTable, renderTradeReviews, renderPatternMemory, renderValidationAudit)

### Arquivos alterados
- dashboard_server.py — novas funcoes + rota + integracao no _build_status
- templates/index.html — nova tab + CSS + JS

### Correcoes de compatibilidade
- Campo `lesson` do trade_review_lab.py (nao `lesson_learned`) — tratado com fallback
- Campo `trade_identity.symbol` e `trade_identity.system` — extraidos corretamente
- Tuples do Counter.most_common() normalizados para dicts {label, count}
- Dados do validation_audit_report.json normalizados (metrics + expectancy flat)

### Status
- Syntax check: OK
- Pronto para commit + push + pull na Pi

---

## 2026-04-06 — Roadmap documentado

### Melhorias futuras priorizadas (nao implementadas ainda)

**P1 — Feedback Loop (pattern_memory -> parametros ao vivo)**
- Quando padrao "SL apertado" aparece frequentemente, sugerir aumentar ATR multiplier
- Requer: 50+ trades fechados no pattern_memory
- Impacto: auto-ajuste de parametros sem intervencao manual

**P2 — ML Scorer Local (scikit-learn no Pi)**
- Treinar Random Forest com outcome_labels do scalping
- Input: RSI, BB, EMA, volume, confluencia, hora, volatilidade
- Output: probabilidade de sucesso (0-100%)
- Roda em milissegundos, zero custo de API
- Requer: 100+ outcome_labels rotulados

**P3 — Auto-review de trades**
- Quando trade fecha, rodar trade_review_lab.py automaticamente
- Disparar via hook no insert_*_trade() ou via supervisor
- Reduz dependencia de execucao manual

**P4 — WebSocket no dashboard**
- Substituir AJAX polling por WebSocket (flask-socketio)
- Notificacao instantanea de trades novos
- Menor carga no Pi (sem requests a cada 25s)

**P5 — .env automatico nos desks offline**
- Adicionar load_dotenv() no topo de validation_auditor.py, trade_review_lab.py, pattern_memory_desk.py
- Eliminar necessidade de `source .env` manual no shell

---

## 2026-04-05 — Deploy Pi (commit 9d83a2a)

### O que foi feito
- feat: harden agent desk and offline learning loop
- Novos arquivos: validation_auditor.py, trade_review_lab.py, pattern_memory_desk.py
- Deploy na Pi, servico cryptobot restart
- Validacao: dashboard healthy, processos vivos, banco OK
- Ciclo offline rodou ok (validation + review + pattern memory)

### Estado pos-deploy
- AGENT_REAL_EXECUTION_ENABLED = False (paper mode)
- 2 agent_trades open (antigos, pre-mudanca)
- Soak test em andamento
