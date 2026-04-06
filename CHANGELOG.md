# CHANGELOG — Crypto AI Bot

Registro de alteracoes por sessao. Mais recente no topo.

---

## 2026-04-06 — Sessao completa: AI Brain + Capital Reset + Scalping Ativado

### Resumo da sessao
Sessao longa com 3 frentes: nova tab dashboard, ajuste de capital, ativacao do scalping.

### 1. Dashboard — Nova tab "AI Brain"
- **5 funcoes backend** novas em dashboard_server.py
- **Rota GET /api/ai-brain** + integrado ao AJAX polling
- **Tab com 4 secoes**: KPI bar, Decision Log, Trade Reviews + Pattern Memory, Validation Audit
- **Fix 1**: nome do arquivo validation → strategy_validation_report.json
- **Fix 2**: campo expectancy_pct (nao per_trade)
- **Fix 3**: campo lesson (nao lesson_learned) + trade_identity.symbol/system

### 2. Capital ajustado de $35k para $1k
- Variavel: `BOT_PORTFOLIO_TARGET_CAPITAL=1000` no .env
- States resetados manualmente na Pi:
  - paper_state.json → $285.71
  - agent_state.json → $285.71
  - scalping_state.json → $285.71
  - pump_positions.json → $142.86 (criado do zero, nome correto)
- Proporcao original mantida (paper/agent/scalping iguais, pump = metade)

### 3. Scalping ativado em modo experimental
- `SCALPING_EXPERIMENTAL_FORCE_ENTRIES=true` no .env
- Isso liga tambem: IGNORE_RISK_FILTERS, DISABLE_AI_GATE, DISABLE_COOLDOWN
- Scalping Mode mostra "Experimental" no dashboard

### 4. Agent — trades orfaos limpos
- Script close_orphan_trades.py criado (dry run + execute)
- 3 posicoes fechadas: DOGE (-1.54%), XRP (-1.65%), BTC (-0.08%)
- Total: -$65.22 (agent capital → $9933.34, depois resetado para $285.71)

### 5. CHANGELOG.md criado
- Tracking de alteracoes por sessao

### Arquivos alterados
- dashboard_server.py (AI Brain backend + fixes)
- templates/index.html (AI Brain tab + CSS + JS)
- CHANGELOG.md (novo)
- close_orphan_trades.py (novo)
- .env na Pi (capital + scalping flags)
- runtime/baseline/*.json na Pi (capital reset)

### Commits
- 97a03a3 — feat: add AI Brain dashboard tab + changelog
- 2cdff27 — fix: correct validation report filename
- d28e26d — fix: read correct expectancy field
- 096a745 — feat: add orphan trade closer utility

### Estado atual da Pi
- Bot healthy, 3 posicoes abertas (paper)
- Portfolio: $999.99 (4 sistemas)
- Scalping: experimental, 0 trades ainda (recem ativado)
- Agent: limpo, 0 posicoes, pronto pra novos trades
- Pump: ativo, 2 trades historicos

### Pendente — Reset visual do dashboard
O -97.14% mostrado no return e porque os trades antigos foram feitos com capital de $10k.
Opcoes para proxima sessao:
- **Opcao A**: Limpar historico de trades antigos do banco (perder dados visuais, manter backup)
- **Opcao B**: Criar um "marco zero" — ignorar trades antes de 06/04 no calculo de return
- **Opcao C**: Backup do banco atual + criar banco novo zerado

---

## 2026-04-06 — Dashboard AI Brain + Roadmap (detalhes tecnicos)

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
