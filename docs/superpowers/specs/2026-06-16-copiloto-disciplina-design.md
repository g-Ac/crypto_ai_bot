# Spec — Copiloto de Disciplina (Fatia 1 do Painel de Análise Pré-Trade)

**Data:** 2026-06-16
**Origem:** sessão de 16/06 em que se provou (com 9 anos de dado, 5 estudos) que timing/previsão de curto prazo não tem edge acessível, e que alavancagem na capitulação é ruína. A virada de chave: o bot deixa de **tentar prever** e passa a ser um **copiloto de disciplina** pro trading discricionário do Gabriel.
**Próxima etapa:** levar este spec pra uma instância nova do Claude e invocar `superpowers:writing-plans` a partir dele.

---

## Propósito (em uma frase)

Um copiloto que **não prevê e não opera** — ele protege o Gabriel dos **dois erros que mais lhe custam dinheiro**, que ele mesmo nomeou:
1. **Entrar cedo demais** ("fui pego pela faca").
2. **Sair tarde demais** ("o lucro virou imagem").

O Gabriel continua decidindo e executando **na mão**. O bot é o contador frio que segura a mão dele na entrada e grita na hora da saída.

## Não-objetivos (lê com atenção — é o que mantém o projeto honesto)

- **Não prevê direção.** Não existe "sinal de compra mágico". Isso foi testado e morreu.
- **Não executa ordens.** Sem chave de API com permissão de trade. Zero dinheiro real no bot.
- **Não usa alavancagem.** Vetada — é o que transforma erro em ruína.
- **Não é o painel completo.** O painel inteiro (contexto, risco) é a *visão*; esta Fatia 1 é só os dois módulos de disciplina.

## A visão completa (norte, NÃO escopo desta fatia)

Painel de análise pré-trade, a ser construído **fatia por fatia**:

| Bloco | O que mostra | Status |
|---|---|---|
| 🌡️ Contexto | BTC (termômetro), regime, Fear & Greed, funding/liquidação | quase pronto (`/mercado` + coletores) — fatia futura |
| 🎯 **Quando entrar** | confirmação anti-entrar-cedo | **Fatia 1, módulo A** |
| 🛡️ **Quando sair** | vigia anti-sair-tarde | **Fatia 1, módulo B** |
| 📐 Quanto arriscar | stop, alvo, R/R, tamanho | fatia futura |

> Por que começar pelos dois do meio: o contexto a gente quase já tem, e o risco vem depois. Os dois do meio **não existem** e são **o que mais sangra dinheiro**. Resolver a dor antes do enfeite.

---

## Fatia 1 — os dois módulos

### Módulo A — Guarda de Entrada (anti-entrar-cedo)

**Fluxo:** o Gabriel marca uma moeda que está de olho no Telegram (ex: `/vigiar LINKUSDT compra`). O bot passa a monitorar e **só dá o "verde" quando a confirmação acontecer** — até lá, responde *"ainda não, espera"*. Isso segura a mão dele pra não comprar a faca no meio da queda.

**Regra de confirmação (proposta inicial — refinar com o Gabriel):** o preço fez uma mínima local **e** voltou ≥ 2% dela (a faca parou de cair) **e** o RSI(14) está virando pra cima. Enquanto os três não baterem → "ainda não".

**Quando confirma:** mensagem no Telegram → *"LINK confirmou em [preço]. Se for entrar, stop sugerido em [mínima recente]. R/R até [resistência] = [X]."* (sugere, não obriga.)

### Módulo B — Vigia de Saída (anti-sair-tarde)

**Fluxo:** o Gabriel avisa que entrou (ex: `/entrei LINKUSDT 7.50 stop 7.20`). O bot acompanha o preço e a força do movimento e **alerta na hora de realizar**, antes do lucro evaporar.

**Regra de alerta (proposta inicial — refinar):** dispara quando **(a)** o preço recua ≥ 30% do pico de lucro já atingido (trailing), **ou (b)** a força morre (RSI/momentum caindo após esticar). Mensagem: *"LINK — realiza! lucro em +[Z]%, a força tá morrendo. Tá virando imagem."* Também alerta se o stop original for ameaçado.

---

## Arquitetura

- **Reusa o que existe:** preço dos coletores (`k_prices`) ou Binance REST; o Telegram do **pi-control**; os indicadores (RSI, MM — já no projeto).
- **Estado (SQLite):** uma `watchlist` (moedas vigiadas pra entrada) e uma tabela `trades_abertos` (vigia de saída) — com símbolo, preços, picos, status.
- **Loop:** roda no ciclo que já existe (a cada N minutos), checa cada item vigiado, e dispara mensagem quando a regra bate. Dedup de alertas (não repetir o mesmo aviso).
- **Casa do código:** decidir na implementação — provavelmente dentro do **pi-control** (onde o Telegram já vive), consumindo dados do crypto_ai_bot.

## Decisões a refinar na implementação (com o Gabriel)

1. **Qual módulo primeiro.** Sugestão: **B (vigia de saída)** — "o lucro virou imagem" é a dor mais aguda e a regra mais objetiva (trailing); o A depende de definir bem a "confirmação".
2. Os **parâmetros exatos** (os 2%/30%/RSI são chutes iniciais — calibrar com o olho do Gabriel, **sem** cair em otimização cega: escolher por lógica, não por resultado).
3. **Onde mora o código** (pi-control vs módulo novo no crypto_ai_bot).

## Disciplina herdada (não negociável)

Sem dinheiro real · sem alavancagem · não prevê, só vigia e alerta · a decisão é **sempre** do Gabriel · um módulo de cada vez (B antes de A), validando que ajuda de verdade antes de pendurar o resto do painel.

---

## Self-review (rodado ao escrever)

- **Placeholders:** as regras (2%/30%/RSI) são **propostas explícitas a refinar**, não TBDs vazios — marcadas como tal. ✅
- **Consistência:** os dois módulos não se sobrepõem (um é pré-entrada, outro é pós-entrada); o fluxo Telegram é coerente entre eles. ✅
- **Escopo:** focado — dois módulos, uma fatia. O painel completo está explicitamente **fora**. ✅
- **Ambiguidade:** "confirmação" e "força morrendo" estão definidas por regra concreta (não subjetivas). ✅
