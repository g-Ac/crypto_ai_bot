# Spec — Aba Mercado no Trade Desk (fase 2 do `/mercado`)

- **Data:** 2026-06-10
- **Status:** ✅ DESIGN aprovado no brainstorm (com 7 ajustes do Gabriel incorporados) — pronto pra plano TDD.
- **Escopo:** portar a leitura de mercado do Telegram (`/mercado` e `/mercado <SYM>`) pra uma aba web no Trade Desk (porta 5000). **Leitura, não sinal. Não toca momentum/v1.1, não coleta dado novo, não opera.**
- **Origem:** fase 2 prevista na spec `2026-06-08-leitura-mercado-spot.md` ("painel web só depois do Telegram validar o conteúdo" — validou, está em produção desde 08/06). Continuação da consolidação do copiloto na "casa" do Trade Desk (Fatias 1 Raio-X e 2 Mapa da Moeda).

## Decisões do brainstorm

| Eixo | Decisão |
|---|---|
| Escopo | **Port completo**: macro (regime + pressão + tradutor + frescor) E zoom por símbolo. Nada de conteúdo novo. |
| Atualização | **Sob demanda** (princípio da spec original): carrega ao abrir + botão atualizar (reload) + frescor visível. Sem auto-refresh, sem SSE, sem polling. |
| Integração | **Integrada**: aba "Mercado" na nav; moeda clicável no macro → zoom; zoom BTC/ETH → link pro Mapa da Moeda. |
| Forma | **Server-side Jinja sobre os dicts** (abordagem B): rota consome leitura + tradutores do `market_read.py` (motor intocado); template renderiza no servidor. Sem endpoint JSON novo, sem JS novo (exceto ~3 linhas de `?symbol=` no mapa.js). |

## Não-objetivos (YAGNI / guarda anti-drift)
- ❌ Score/veredito/recomendação — **componentes, não veredito** (mesma guarda do Telegram).
- ❌ Auto-refresh ou alertas — leitura sob demanda, não monitor.
- ❌ Expandir o Mapa da Moeda pros 14 símbolos — deep-link `?symbol=` só pré-seleciona BTC/ETH existentes.
- ❌ Sparklines/gráficos novos nesta fatia.
- ❌ Endpoint JSON `/api/mercado` — server-side puro basta; criar API se/quando houver consumidor real.

## Arquitetura

Molde das Fatias 1 e 2: **backend puro testável + rota fina**.

### `mercado_data.py` (novo módulo, fino)
Monta as views prontas pra template consumindo o motor validado do `market_read.py` **sem modificá-lo**:

- `SUPPORTED_MARKET_SYMBOLS` — tupla canônica dos 14 símbolos (cópia da `SYMBOLS` de `scripts/k_collector.py`; teste de paridade garante sync). **Validade de símbolo vem daqui, nunca de `all_symbols(conn)`** — em banco vazio a lista do banco é vazia e quebraria o requisito "banco vazio renderiza n/d". `all_symbols(conn)` segue sendo usado só pelo motor (breadth/realidade do banco).
- `normalize_symbol(raw) -> str | None` — `BTC` → `BTCUSDT`, `btcusdt` → `BTCUSDT`; retorna `None` se o resultado não está em `SUPPORTED_MARKET_SYMBOLS`. Borda conhecida: `PEPE` → `PEPEUSDT` → inválido (não normaliza pra `1000PEPEUSDT`); aceitável — links internos sempre carregam o símbolo completo.
- `macro_view(conn) -> dict` — regime formatado + pressão formatada (rótulo via `market_read._pressure_label`) + linhas do `translate_macro` + frescor (`read_freshness`) + timestamp da leitura.
- `symbol_view(conn, symbol) -> dict` — zoom formatado + `translate_symbol` + frescor + `tem_mapa` (True só pra BTCUSDT/ETHUSDT, espelhando `SYMBOLS` do mapa.js).

**Anti-divergência (ajuste 2):** o rótulo de pressão reutiliza **exatamente** `market_read._pressure_label(p)`. Importar helper privado é aceitável aqui porque a decisão é "não tocar no market_read" e o teste anti-divergência protege; promover a público fica pra refactor separado, se um dia incomodar.

### Rotas em `dashboard_server.py` (finas, padrão raiox)
```
GET /raiox/mercado            → render_template("mercado.html", view=mercado_data.macro_view(conn), active_page="mercado")
GET /raiox/mercado/<symbol>   → normaliza; inválido → redirect("/raiox/mercado"); válido → render mercado_symbol.html
                                (ambas com active_page="mercado" — nav destaca Mercado também no zoom)
```
- Conexão: `conn = db._get_conn()` + `try/finally conn.close()` (padrão das rotas raiox).
- Erro de banco/query: exceção propaga → 500 padrão do Flask, consistente com as rotas Raio-X atuais. Sem página de erro custom nesta fatia.

### Templates
- `templates/mercado.html` e `templates/mercado_symbol.html`, estendendo `base.html`.
- `base.html`: aba **Mercado** (`/raiox/mercado`, `active_page="mercado"`) nos **2 blocos** de nav (desktop e mobile).
- Barra de split longs/shorts em CSS puro (sem lib nova).

### `static/js/mapa.js` (incremento mínimo)
Ler `?symbol=` via `URLSearchParams`, normalizar (`ETH` ou `ETHUSDT` → `ETHUSDT`), pré-selecionar se estiver em `SYMBOLS`; inválido/ausente → BTC (comportamento atual). ~3 linhas.

## Conteúdo — página macro (`/raiox/mercado`)

Espelha `format_macro` em componentes web. **Componentes, nunca veredito.**

1. **Termômetro de regime** — retornos 24h/7d dos majors (BTC/ETH/SOL), breadth (X/Y verdes 24h; normalmente Y=14 quando o coletor populou todos os símbolos, `n/d` em banco vazio), vol BTC, taker BTC, LSR BTC, funding dos majors, basis BTC, ΔOI BTC. Cor verde/vermelho pelo sinal do número; nenhum agregado.
2. **Mapa de pressão** — tabela ordenada por notional 24h: moeda (**clicável → zoom**), total liquidado, split longs/shorts (barra CSS + rótulo idêntico ao Telegram: cascata ↓ / squeeze ↑ / equilibrado / pouco volume), nº eventos.
3. **Em palavras** — linhas do `translate_macro` (tradutor PT).
4. **Frescor** — idade de cada fonte (`read_freshness`), destacando dado velho.
5. **Sob demanda** — "leitura de HH:MM" (hora local do servidor, como o resto do dashboard) + botão atualizar (reload da página).

## Conteúdo — página zoom (`/raiox/mercado/<SYM>`)

Espelha `format_symbol`: ret 24h/7d, LSR (global + top), funding, basis, ΔOI 24h, vol 24h, taker 24h, liquidações da moeda (split + rótulo), tradutor (`translate_symbol`), frescor. Navegação: ← voltar ao macro; se `tem_mapa`, link **"ver no Mapa da Moeda"** → `/raiox/mapa?symbol=BTCUSDT` (símbolo interno sempre completo).

## Erros e bordas
- Dado ausente → `n/d` (herdado dos helpers do `market_read`).
- Banco vazio → páginas renderizam com `n/d` em tudo, sem quebrar (possível porque a validade de símbolo é canônica, não vem do banco).
- Símbolo inválido → redirect `/raiox/mercado`.
- Erro de banco → 500 padrão (rota fina não engole exceção).

## Testes (TDD red→green)

### `tests/test_mercado_data.py` (banco in-memory, fixtures no molde do `test_market_read.py`)
- Estrutura de `macro_view` / `symbol_view` (chaves, tipos, formatação).
- `normalize_symbol`: `BTC`→`BTCUSDT`, `btcusdt`→`BTCUSDT`, `FOO`→`None`, `PEPE`→`None`.
- **Paridade canônica:** `SUPPORTED_MARKET_SYMBOLS` == `SYMBOLS` de `scripts/k_collector.py`.
- **Anti-divergência:** mesmo banco → rótulo de pressão em `macro_view` == rótulo dentro de `format_macro` (web == Telegram).
- Banco vazio → views completas com `n/d`, sem exceção.
- `tem_mapa`: True só pra BTCUSDT/ETHUSDT.
- **Anti-sinal:** reaproveitar `FORBIDDEN_SIGNAL_WORDS` de `tests/test_market_read.py` sobre as linhas/strings das views.

### Rotas (molde do `test_raiox_endpoints.py`)
- `/raiox/mercado` → 200 + conteúdo-chave (termômetro, pressão, em palavras, frescor).
- `/raiox/mercado/BTC` e `/raiox/mercado/BTCUSDT` → 200 exibindo BTC.
- `/raiox/mercado/FOO` → redirect pra `/raiox/mercado` (nota: `DOGE` é **válido** — DOGEUSDT está nos 14).
- `base.html` renderizado contém `/raiox/mercado` nos 2 navs.
- **Anti-sinal no HTML:** `FORBIDDEN_SIGNAL_WORDS` sobre o HTML renderizado das 2 páginas.

### mapa.js (validação visual — JS não tem suite)
- `?symbol=ETH` e `?symbol=ETHUSDT` pré-selecionam ETH; inválido/ausente → BTC. Verificado no checklist visual (instância 5055, Claude in Chrome).

### Validação visual (rito das fatias 1-2)
Instância 5055 com checklist (nav, macro, clique moeda → zoom, zoom → mapa com símbolo certo, botão atualizar, console limpo) → depois Gabriel valida na 5000. **Commit só com OK explícito.**

## Riscos / guardas
- **Divergência web vs Telegram** — neutralizada pelo reuso do motor + teste anti-divergência do rótulo.
- **Drift pra sinal/monitor** — sem score, sem auto-refresh, vocabulário testado contra `FORBIDDEN_SIGNAL_WORDS`.
- **Pi (recursos)** — server-side sob demanda: zero polling, zero lib nova; queries são as mesmas do Telegram (leves, hourly).
- **`_pressure_label` privado** — acoplamento aceito conscientemente (ajuste 2); teste anti-divergência denuncia se mudar.

## Próximo passo
1. `writing-plans` a partir desta spec → plano TDD (red→green por módulo: `mercado_data.py` → rotas → templates → mapa.js).
2. Validação visual na 5055 → OK do Gabriel → commit seletivo → restart produção → validação na 5000.
