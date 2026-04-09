# Resultados da Noite — 08/04/2026

## Tarefas executadas

1. Backtest exit comparison — **FALHOU** (Pi ficou sem resposta aos ~40 min de processamento, provavel OOM)
2. Fee audit — **COMPLETO**
3. Funnel diagnosis — **COMPLETO**
4. DB metrics — **COMPLETO**
5. High priority audit — **COMPLETO**

## Resumo executivo

- **Fee audit:** Todos os 6 subsistemas (paper, agent, scalping, pump, backtest, backtest_scalping) aplicam 0.08% round-trip (0.04% por lado). Unica inconsistencia: scalping_trader.py usa valores hardcoded (0.04) em vez de constante centralizada, mas o valor esta correto.

- **Funil do scalping:** TODOS os motores estao 100% bloqueados no momento da analise. Mercado em fase lateral/baixa volatilidade: volume insuficiente para Volume Breakout, RSI neutro (39-57, precisa <=32 ou >=68) para RSI/BB, EMAs entrelacadas para EMA Crossover. Nenhum sinal possivel — resultado esperado neste regime.

- **DB metrics pos-reset (06/04):** Zero trades em todos os sistemas desde o reset de capital. Tabelas de decisoes (ai_decisions, scalping_decisions) tambem vazias. Sistema saudavel mas sem oportunidades no mercado atual.

- **Auditoria A1-A11:** Todos os 11 itens de prioridade ALTO do melhorias.md estao CORRIGIDOS no codigo atual. Destaques: API Futures configurada (A1), auth no dashboard (A2), deploy.sh robusto (A3), backtest usando strategy.py (A4), 180 dias (A5), ATR-based SL (A6), pump max positions (A7), dump detection funcional (A8), supervisor com backoff (A9), try/except no log_trade (A10), scalping no /capital (A11).

## Backtest — FALHOU (Pi sem resposta)

O backtest `--compare-exits` (PID 10579) rodou por ~40 minutos coletando sinais de BTCUSDT
(53,244 candles de 5m x 3 engines). Aos ~40 min, o Pi ficou completamente sem resposta
(SSH + ping falham). Provavel causa: OOM — os 3 DataFrames (88K + 53K + 17K candles) + 
processamento dos engines esgotaram a RAM do Pi 4.

### Recuperacao

1. Fazer reboot fisico do Pi (ou aguardar auto-recovery se houver watchdog)
2. Verificar se o bot principal (cryptobot) reiniciou: `sudo systemctl status cryptobot`
3. Para re-rodar o backtest com menor consumo de RAM, considerar:
   - Rodar 1 simbolo por vez: `--symbols BTCUSDT` depois `--symbols ETHUSDT`
   - Reduzir periodo: usar 90 dias em vez de 180
   - Ou rodar no PC local em vez do Pi

## Proximos passos sugeridos

1. **Reboot do Pi** e re-rodar backtest com menor footprint de memoria (1 simbolo por vez ou 90 dias)
2. **Relaxar filtros do scalping** — RSI zones de 32/68 para 35/65, ATR minimo de 0.15% para 0.10%, para destravar sinais em mercado lateral
3. **Centralizar fee do scalping** — extrair 0.04 hardcoded em scalping_trader.py para constante `FEE_PER_SIDE`
4. **Verificar itens CRITICOS (C1-C7)** — mesmo padrao da auditoria A1-A11 para confirmar correcoes
5. **Implementar metricas do funil** (Metrica 1 do melhorias.md) — registrar em `scalping_decisions` por que cada ciclo foi bloqueado
