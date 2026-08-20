# Autópsia visual dos trades Momentum Pullback

Fonte: `momentum_trades` + candles 15m cacheados (`data/candles/BTCUSDT_15m.csv`, `ETHUSDT_15m.csv`).

**Importante:** análise descritiva, não mudança operacional. Não vira filtro sem mini-spec e forward validation.

## Como ler

- `range_pos24`: posição da entrada no range das 24h anteriores. 0% = fundo anterior, 100% = topo anterior. Abaixo de 0% = rompendo fundo; acima de 100% = rompendo topo.
- `pavio superior`: tentou subir e foi vendido. `pavio inferior`: tentou cair e foi comprado.
- `chase`: entrou tarde na perna, depois do movimento já andar bastante.

## Resumo bruto

- Trades analisados: 156 de 156.
- PnL bruto analisado: +12.37%. WR: 60.3%.

- BTCUSDT LONG: n=45, WR=51.1%, avg=-0.146%, soma=-6.57%
- BTCUSDT SHORT: n=42, WR=64.3%, avg=+0.211%, soma=+8.85%
- ETHUSDT LONG: n=30, WR=63.3%, avg=+0.115%, soma=+3.46%
- ETHUSDT SHORT: n=39, WR=64.1%, avg=+0.170%, soma=+6.63%

## Padrões encontrados — do pior para o melhor

| padrao | n | wins | wr | avg_pnl | sum_pnl | avg_mae | avg_mfe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LONG chase após subida rápida | 55 | 27 | 49.1% | -0.143% | -7.86% | -0.488% | +0.321% |
| LONG rompendo topo 24h | 55 | 27 | 49.1% | -0.143% | -7.86% | -0.488% | +0.321% |
| SHORT contra alta/squeeze | 43 | 26 | 60.5% | -0.019% | -0.83% | -0.444% | +0.409% |
| SHORT rompendo topo 24h | 43 | 26 | 60.5% | -0.019% | -0.83% | -0.444% | +0.409% |
| LONG rompendo fundo 24h | 19 | 14 | 73.7% | +0.225% | +4.27% | -0.466% | +0.805% |
| LONG contra queda/faca caindo | 20 | 15 | 75.0% | +0.237% | +4.75% | -0.448% | +0.790% |
| SHORT perto do fundo/suporte 24h | 3 | 2 | 66.7% | +0.414% | +1.24% | -0.186% | +0.560% |
| SHORT chase após queda rápida | 35 | 23 | 65.7% | +0.429% | +15.01% | -0.523% | +0.760% |
| SHORT rompendo fundo 24h | 32 | 21 | 65.6% | +0.430% | +13.77% | -0.555% | +0.778% |
| setup limpo/sem anomalia visual óbvia | 3 | 3 | 100.0% | +0.435% | +1.31% | -0.325% | +0.589% |
| LONG perto do fundo/suporte 24h | 1 | 1 | 100.0% | +0.476% | +0.48% | -0.100% | +0.506% |

## Resultado por posição no range de 24h

| direction | bucket_pos24 | n | wr | avg | soma |
| --- | --- | --- | --- | --- | --- |
| LONG | abaixo fundo | 19 | 73.7% | +0.225% | +4.27% |
| LONG | fundo 0-25% | 1 | 100.0% | +0.476% | +0.48% |
| LONG | acima topo | 55 | 49.1% | -0.143% | -7.86% |
| SHORT | abaixo fundo | 32 | 65.6% | +0.430% | +13.77% |
| SHORT | fundo 0-25% | 3 | 66.7% | +0.414% | +1.24% |
| SHORT | baixo 25-50% | 1 | 100.0% | +0.571% | +0.57% |
| SHORT | alto 50-75% | 2 | 100.0% | +0.367% | +0.73% |
| SHORT | acima topo | 43 | 60.5% | -0.019% | -0.83% |

## Leitura principal em português simples

1. O problema visual mais perigoso aparece quando a entrada depende de **continuação imediata**. Exemplo: LONG acima/perto do topo depois de alta, ou SHORT abaixo/perto do fundo depois de queda. Se continua, dá gain rápido; se não continua, vira repique/estouro de SL.
2. O robô ainda não parece “enxergar” bem **onde a entrada está no range recente**. Ele vê gatilho de momentum/pullback, mas não necessariamente se está entrando no pior lugar do range.
3. Pavio contra a posição importa visualmente: LONG com pavio superior perto do topo significa que o preço tentou subir e foi vendido; SHORT com pavio inferior perto do fundo significa que a queda foi comprada.
4. Volume alto sozinho não decide nada. Volume alto no meio de rompimento pode confirmar; volume alto no extremo do range pode ser exaustão.
5. Alguns padrões “feios” ainda deram dinheiro nesta amostra. Então não dá para cortar por intuição. O valor desta autópsia é levantar hipóteses, não decidir filtro agora.

## 15 piores trades

- #52 BTCUSDT SHORT 2026-05-04 14:51 pnl=-1.52% sl_hit: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=393%, ret4h=+9.37%, MAE=-2.06%, MFE=+0.30%.
- #156 BTCUSDT LONG 2026-06-10 21:52 pnl=-1.51% timeout: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-399%, ret4h=-13.66%, MAE=-1.52%, MFE=+0.06%.
- #51 ETHUSDT LONG 2026-05-04 10:06 pnl=-1.48% timeout: LONG rompendo topo 24h; LONG chase após subida rápida. Interpretação: comprou já acima do topo anterior; depende de continuação imediata; entrou depois de alta forte; risco de comprar extensão. range24=292%, ret4h=+6.55%, MAE=-1.48%, MFE=+0.09%.
- #68 BTCUSDT LONG 2026-05-11 04:21 pnl=-1.38% timeout: LONG rompendo topo 24h; LONG chase após subida rápida. Interpretação: comprou já acima do topo anterior; depende de continuação imediata; entrou depois de alta forte; risco de comprar extensão. range24=539%, ret4h=+13.63%, MAE=-1.56%, MFE=+0.05%.
- #10 BTCUSDT LONG 2026-04-19 17:51 pnl=-1.19% sl_hit: LONG rompendo topo 24h; LONG chase após subida rápida. Interpretação: comprou já acima do topo anterior; depende de continuação imediata; entrou depois de alta forte; risco de comprar extensão. range24=254%, ret4h=+5.32%, MAE=-1.42%, MFE=+0.44%.
- #117 ETHUSDT SHORT 2026-06-01 17:49 pnl=-1.17% sl_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-304%, ret4h=-11.43%, MAE=-1.26%, MFE=+0.56%.
- #53 ETHUSDT SHORT 2026-05-04 17:52 pnl=-1.07% sl_hit: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=253%, ret4h=+5.40%, MAE=-1.39%, MFE=+0.42%.
- #57 BTCUSDT LONG 2026-05-06 14:07 pnl=-1.03% sl_hit: LONG rompendo topo 24h; LONG chase após subida rápida. Interpretação: comprou já acima do topo anterior; depende de continuação imediata; entrou depois de alta forte; risco de comprar extensão. range24=556%, ret4h=+14.12%, MAE=-1.24%, MFE=+0.02%.
- #16 BTCUSDT LONG 2026-04-21 14:06 pnl=-1.02% sl_hit: LONG rompendo topo 24h; LONG chase após subida rápida. Interpretação: comprou já acima do topo anterior; depende de continuação imediata; entrou depois de alta forte; risco de comprar extensão. range24=286%, ret4h=+6.25%, MAE=-1.03%, MFE=+0.06%.
- #148 ETHUSDT LONG 2026-06-09 00:29 pnl=-1.02% sl_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-713%, ret4h=-23.78%, MAE=-1.41%, MFE=+1.05%.
- #140 BTCUSDT LONG 2026-06-07 13:52 pnl=-1.02% timeout: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-386%, ret4h=-13.30%, MAE=-1.24%, MFE=+0.54%.
- #23 BTCUSDT SHORT 2026-04-23 15:22 pnl=-0.89% sl_hit: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=341%, ret4h=+7.86%, MAE=-1.07%, MFE=+0.30%.
- #146 ETHUSDT LONG 2026-06-08 17:07 pnl=-0.88% sl_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-720%, ret4h=-24.01%, MAE=-0.93%, MFE=+0.37%.
- #33 ETHUSDT SHORT 2026-04-28 17:36 pnl=-0.82% sl_hit: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=145%, ret4h=+2.12%, MAE=-0.88%, MFE=+0.53%.
- #72 ETHUSDT SHORT 2026-05-12 22:07 pnl=-0.78% timeout: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=143%, ret4h=+2.06%, MAE=-0.87%, MFE=+0.05%.

## 15 melhores trades

- #123 ETHUSDT SHORT 2026-06-02 19:33 pnl=+2.03% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-367%, ret4h=-13.33%, MAE=-0.12%, MFE=+2.49%.
- #131 BTCUSDT SHORT 2026-06-05 18:44 pnl=+1.86% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-458%, ret4h=-15.38%, MAE=-0.38%, MFE=+2.05%.
- #124 BTCUSDT SHORT 2026-06-02 22:56 pnl=+1.33% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-152%, ret4h=-6.48%, MAE=-0.88%, MFE=+1.43%.
- #120 BTCUSDT SHORT 2026-06-02 06:50 pnl=+1.32% tp2_hit: SHORT perto do fundo/suporte 24h; SHORT chase após queda rápida. Interpretação: vendeu baixo no range; risco de repique; entrou depois de queda forte; risco de vender o fundo. range24=22%, ret4h=-1.43%, MAE=-0.13%, MFE=+1.34%.
- #147 ETHUSDT LONG 2026-06-08 21:12 pnl=+1.32% tp2_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-720%, ret4h=-24.01%, MAE=-0.75%, MFE=+1.34%.
- #125 BTCUSDT SHORT 2026-06-03 03:30 pnl=+1.24% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-166%, ret4h=-6.90%, MAE=-0.27%, MFE=+1.31%.
- #132 BTCUSDT SHORT 2026-06-06 04:09 pnl=+0.98% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-448%, ret4h=-15.11%, MAE=-0.31%, MFE=+1.19%.
- #7 ETHUSDT SHORT 2026-04-19 04:44 pnl=+0.97% tp2_hit: SHORT rompendo topo 24h; SHORT contra alta/squeeze. Interpretação: vendeu com preço acima do topo anterior; contra rompimento/squeeze; vendeu contra pressão compradora recente. range24=251%, ret4h=+5.33%, MAE=-0.04%, MFE=+0.97%.
- #116 ETHUSDT SHORT 2026-06-01 13:58 pnl=+0.96% tp2_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-295%, ret4h=-11.16%, MAE=-0.30%, MFE=+1.09%.
- #155 BTCUSDT LONG 2026-06-10 15:48 pnl=+0.93% tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-412%, ret4h=-14.05%, MAE=-0.03%, MFE=+1.13%.
- #145 ETHUSDT LONG 2026-06-08 15:04 pnl=+0.93% tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. Interpretação: comprou com preço abaixo do fundo anterior; tentativa perigosa de reversão; comprou contra pressão vendedora recente. range24=-732%, ret4h=-24.37%, MAE=-0.15%, MFE=+0.99%.
- #133 ETHUSDT SHORT 2026-06-06 10:55 pnl=+0.92% timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-916%, ret4h=-29.91%, MAE=-2.11%, MFE=+1.57%.
- #115 ETHUSDT SHORT 2026-06-01 12:13 pnl=+0.90% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-280%, ret4h=-10.70%, MAE=-0.06%, MFE=+1.02%.
- #128 ETHUSDT SHORT 2026-06-05 01:02 pnl=+0.88% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-607%, ret4h=-20.57%, MAE=-0.40%, MFE=+0.90%.
- #129 BTCUSDT SHORT 2026-06-05 05:59 pnl=+0.85% tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. Interpretação: vendeu já abaixo do fundo anterior; depende de continuação imediata; entrou depois de queda forte; risco de vender o fundo. range24=-365%, ret4h=-12.66%, MAE=-1.30%, MFE=+0.95%.

## Últimos 30 trades

- #156 BTCUSDT LONG exit=06-10 21:52 pnl=-1.51% dur=16c timeout: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-399%, ret4h=-13.66%, pavio_sup=35%, pavio_inf=0%.
- #155 BTCUSDT LONG exit=06-10 15:48 pnl=+0.93% dur=2c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-412%, ret4h=-14.05%, pavio_sup=35%, pavio_inf=0%.
- #154 BTCUSDT SHORT exit=06-10 12:36 pnl=-0.76% dur=8c sl_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-437%, ret4h=-14.78%, pavio_sup=35%, pavio_inf=0%.
- #153 BTCUSDT SHORT exit=06-10 09:19 pnl=+0.44% dur=11c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-437%, ret4h=-14.78%, pavio_sup=35%, pavio_inf=0%.
- #152 BTCUSDT SHORT exit=06-10 04:40 pnl=+0.51% dur=3c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-428%, ret4h=-14.50%, pavio_sup=35%, pavio_inf=0%.
- #151 BTCUSDT SHORT exit=06-10 02:17 pnl=+0.48% dur=1c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-419%, ret4h=-14.24%, pavio_sup=35%, pavio_inf=0%.
- #150 BTCUSDT SHORT exit=06-09 21:54 pnl=-0.11% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-423%, ret4h=-14.37%, pavio_sup=35%, pavio_inf=0%.
- #149 ETHUSDT SHORT exit=06-09 09:38 pnl=+0.59% dur=2c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-740%, ret4h=-24.61%, pavio_sup=22%, pavio_inf=0%.
- #148 ETHUSDT LONG exit=06-09 00:29 pnl=-1.02% dur=7c sl_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-713%, ret4h=-23.78%, pavio_sup=22%, pavio_inf=0%.
- #147 ETHUSDT LONG exit=06-08 21:12 pnl=+1.32% dur=13c tp2_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-720%, ret4h=-24.01%, pavio_sup=22%, pavio_inf=0%.
- #146 ETHUSDT LONG exit=06-08 17:07 pnl=-0.88% dur=3c sl_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-720%, ret4h=-24.01%, pavio_sup=22%, pavio_inf=0%.
- #145 ETHUSDT LONG exit=06-08 15:04 pnl=+0.93% dur=3c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-732%, ret4h=-24.37%, pavio_sup=22%, pavio_inf=0%.
- #144 ETHUSDT LONG exit=06-08 11:19 pnl=+0.82% dur=5c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-753%, ret4h=-24.98%, pavio_sup=22%, pavio_inf=0%.
- #143 BTCUSDT LONG exit=06-08 09:18 pnl=+0.62% dur=11c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-355%, ret4h=-12.39%, pavio_sup=35%, pavio_inf=0%.
- #142 ETHUSDT LONG exit=06-08 03:21 pnl=+0.19% dur=16c timeout: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-733%, ret4h=-24.39%, pavio_sup=22%, pavio_inf=0%.
- #141 BTCUSDT LONG exit=06-07 17:15 pnl=+0.44% dur=6c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-404%, ret4h=-13.82%, pavio_sup=35%, pavio_inf=0%.
- #140 BTCUSDT LONG exit=06-07 13:52 pnl=-1.02% dur=16c timeout: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-386%, ret4h=-13.30%, pavio_sup=35%, pavio_inf=0%.
- #139 ETHUSDT LONG exit=06-07 08:50 pnl=+0.82% dur=3c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-841%, ret4h=-27.66%, pavio_sup=22%, pavio_inf=0%.
- #138 ETHUSDT LONG exit=06-07 05:21 pnl=+0.75% dur=4c tp2_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-874%, ret4h=-28.63%, pavio_sup=22%, pavio_inf=0%.
- #137 BTCUSDT LONG exit=06-07 03:20 pnl=+0.69% dur=3c tp1_hit: LONG rompendo fundo 24h; LONG contra queda/faca caindo. range24=-442%, ret4h=-14.93%, pavio_sup=35%, pavio_inf=0%.
- #136 ETHUSDT SHORT exit=06-06 23:45 pnl=-0.69% dur=12c sl_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-922%, ret4h=-30.10%, pavio_sup=22%, pavio_inf=0%.
- #135 ETHUSDT SHORT exit=06-06 20:21 pnl=+0.21% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-922%, ret4h=-30.11%, pavio_sup=22%, pavio_inf=0%.
- #134 BTCUSDT SHORT exit=06-06 15:51 pnl=-0.02% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-462%, ret4h=-15.50%, pavio_sup=35%, pavio_inf=0%.
- #133 ETHUSDT SHORT exit=06-06 10:55 pnl=+0.92% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-916%, ret4h=-29.91%, pavio_sup=22%, pavio_inf=0%.
- #132 BTCUSDT SHORT exit=06-06 04:09 pnl=+0.98% dur=12c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-448%, ret4h=-15.11%, pavio_sup=35%, pavio_inf=0%.
- #131 BTCUSDT SHORT exit=06-05 18:44 pnl=+1.86% dur=6c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-458%, ret4h=-15.38%, pavio_sup=35%, pavio_inf=0%.
- #130 BTCUSDT SHORT exit=06-05 11:24 pnl=-0.16% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-386%, ret4h=-13.30%, pavio_sup=35%, pavio_inf=0%.
- #129 BTCUSDT SHORT exit=06-05 05:59 pnl=+0.85% dur=7c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-365%, ret4h=-12.66%, pavio_sup=35%, pavio_inf=0%.
- #128 ETHUSDT SHORT exit=06-05 01:02 pnl=+0.88% dur=5c tp1_hit: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-607%, ret4h=-20.57%, pavio_sup=22%, pavio_inf=0%.
- #127 BTCUSDT SHORT exit=06-04 08:55 pnl=+0.69% dur=16c timeout: SHORT rompendo fundo 24h; SHORT chase após queda rápida. range24=-308%, ret4h=-11.02%, pavio_sup=35%, pavio_inf=0%.

## Tabela completa — uma linha por trade

| id | symbol | direction | exit_time | pnl | exit_reason | duration | mfe | mae | ret4h | ret24h | range_pos24 | upper_wick | lower_wick | vol_rel | tags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | BTCUSDT | LONG | 2026-04-16 07:53 | -0.15 | timeout | 16 | +0.38 | -0.23 | +3.99 | +5.26 | 208% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 2 | BTCUSDT | LONG | 2026-04-17 21:26 | +0.18 | timeout | 16 | +0.43 | -0.41 | +7.40 | +8.72 | 325% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 3 | BTCUSDT | LONG | 2026-04-17 23:21 | -0.52 | sl_hit | 8 | +0.13 | -0.64 | +7.52 | +8.84 | 329% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 4 | BTCUSDT | LONG | 2026-04-18 08:19 | -0.50 | sl_hit | 12 | +0.01 | -0.75 | +7.26 | +8.57 | 320% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 5 | BTCUSDT | SHORT | 2026-04-18 16:22 | +0.60 | tp1_hit | 15 | +0.70 | -0.18 | +5.88 | +7.18 | 273% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 6 | BTCUSDT | SHORT | 2026-04-19 00:09 | -0.12 | timeout | 16 | +0.18 | -0.20 | +5.21 | +6.50 | 250% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 7 | ETHUSDT | SHORT | 2026-04-19 04:44 | +0.97 | tp2_hit | 2 | +0.97 | -0.04 | +5.33 | +6.42 | 251% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 8 | BTCUSDT | SHORT | 2026-04-19 06:18 | +0.26 | tp1_hit | 4 | +0.36 | -0.15 | +4.95 | +6.23 | 241% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 9 | BTCUSDT | SHORT | 2026-04-19 12:38 | -0.39 | timeout | 16 | +0.40 | -0.64 | +4.49 | +5.76 | 225% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 10 | BTCUSDT | LONG | 2026-04-19 17:51 | -1.19 | sl_hit | 14 | +0.44 | -1.42 | +5.32 | +6.61 | 254% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 11 | BTCUSDT | SHORT | 2026-04-20 04:07 | -0.51 | timeout | 16 | +0.15 | -0.79 | +3.01 | +4.27 | 174% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 12 | ETHUSDT | LONG | 2026-04-20 13:06 | +0.61 | timeout | 16 | +0.83 | -0.17 | +3.51 | +4.59 | 191% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 13 | ETHUSDT | LONG | 2026-04-20 14:56 | -0.50 | sl_hit | 2 | +0.21 | -0.96 | +3.76 | +4.84 | 199% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 14 | ETHUSDT | LONG | 2026-04-20 18:03 | +0.75 | tp2_hit | 10 | +0.94 | -0.49 | +3.75 | +4.83 | 199% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 15 | BTCUSDT | LONG | 2026-04-21 01:50 | -0.06 | timeout | 16 | +0.26 | -0.56 | +5.66 | +6.95 | 265% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 16 | BTCUSDT | LONG | 2026-04-21 14:06 | -1.02 | sl_hit | 9 | +0.06 | -1.03 | +6.25 | +7.54 | 286% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 17 | BTCUSDT | LONG | 2026-04-22 11:54 | +0.24 | timeout | 16 | +0.40 | -0.19 | +8.47 | +9.80 | 362% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 18 | ETHUSDT | LONG | 2026-04-22 19:36 | -0.69 | timeout | 16 | +0.11 | -1.12 | +8.33 | +9.45 | 350% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 19 | BTCUSDT | LONG | 2026-04-22 20:26 | -0.50 | sl_hit | 2 | +0.02 | -0.52 | +9.60 | +10.94 | 401% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 20 | ETHUSDT | LONG | 2026-04-22 23:27 | -0.50 | sl_hit | 8 | +0.30 | -0.75 | +7.78 | +8.90 | 332% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 21 | BTCUSDT | SHORT | 2026-04-23 03:40 | +0.66 | tp1_hit | 9 | +0.83 | -0.42 | +8.49 | +9.82 | 363% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 22 | BTCUSDT | SHORT | 2026-04-23 08:36 | +0.04 | timeout | 16 | +0.15 | -0.60 | +8.17 | +9.49 | 352% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 23 | BTCUSDT | SHORT | 2026-04-23 15:22 | -0.89 | sl_hit | 13 | +0.30 | -1.07 | +7.86 | +9.18 | 341% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 24 | ETHUSDT | SHORT | 2026-04-23 23:08 | -0.74 | timeout | 16 | +0.21 | -1.13 | +3.90 | +4.98 | 204% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 25 | ETHUSDT | SHORT | 2026-04-24 11:06 | -0.58 | sl_hit | 4 | +0.05 | -0.81 | +3.76 | +4.84 | 199% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 26 | ETHUSDT | LONG | 2026-04-26 22:16 | +0.46 | tp1_hit | 5 | +0.62 | -0.72 | +6.27 | +7.37 | 282% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 27 | ETHUSDT | LONG | 2026-04-26 23:50 | +0.55 | tp1_hit | 5 | +0.65 | -0.41 | +6.17 | +7.28 | 279% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 28 | ETHUSDT | LONG | 2026-04-27 00:56 | +0.53 | tp1_hit | 3 | +0.87 | -0.34 | +6.36 | +7.47 | 285% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 29 | ETHUSDT | SHORT | 2026-04-27 15:06 | +0.75 | tp2_hit | 1 | +0.89 | -0.04 | +3.97 | +5.05 | 206% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 30 | ETHUSDT | SHORT | 2026-04-27 21:24 | +0.12 | timeout | 16 | +0.72 | -0.21 | +2.95 | +4.02 | 172% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 31 | ETHUSDT | SHORT | 2026-04-28 06:38 | +0.41 | tp1_hit | 8 | +0.49 | -0.19 | +2.90 | +3.97 | 171% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 32 | ETHUSDT | SHORT | 2026-04-28 11:50 | +0.67 | tp1_hit | 12 | +0.67 | -0.12 | +2.69 | +3.76 | 164% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 33 | ETHUSDT | SHORT | 2026-04-28 17:36 | -0.82 | sl_hit | 14 | +0.53 | -0.88 | +2.12 | +3.18 | 145% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 34 | BTCUSDT | SHORT | 2026-04-28 21:10 | -0.50 | sl_hit | 8 | +0.04 | -0.50 | +5.71 | +7.00 | 267% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 35 | ETHUSDT | LONG | 2026-04-29 01:06 | -0.12 | timeout | 16 | +0.10 | -0.35 | +2.98 | +4.05 | 173% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 36 | BTCUSDT | LONG | 2026-04-29 09:52 | +0.54 | tp1_hit | 14 | +0.99 | -0.12 | +7.01 | +8.32 | 312% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 37 | ETHUSDT | LONG | 2026-04-29 12:21 | -0.50 | sl_hit | 4 | +0.27 | -0.64 | +4.67 | +5.76 | 229% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 38 | BTCUSDT | SHORT | 2026-04-29 23:08 | -0.46 | timeout | 16 | +0.34 | -0.70 | +4.96 | +6.24 | 241% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 39 | BTCUSDT | SHORT | 2026-04-30 04:38 | +0.54 | tp1_hit | 4 | +0.65 | -0.11 | +5.44 | +6.73 | 258% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 40 | BTCUSDT | LONG | 2026-05-01 11:23 | +0.32 | tp1_hit | 6 | +0.45 | -0.14 | +7.31 | +8.62 | 322% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 41 | BTCUSDT | LONG | 2026-05-01 18:53 | +0.21 | timeout | 16 | +0.61 | -0.16 | +8.71 | +10.04 | 370% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 42 | ETHUSDT | LONG | 2026-05-01 20:43 | -0.50 | sl_hit | 6 | +0.08 | -0.62 | +3.59 | +4.67 | 194% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 43 | BTCUSDT | LONG | 2026-05-02 09:41 | +0.12 | tp1_hit | 6 | +0.16 | -0.06 | +8.72 | +10.05 | 371% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 44 | BTCUSDT | LONG | 2026-05-02 21:39 | +0.75 | tp2_hit | 16 | +1.00 | -0.13 | +8.92 | +10.26 | 378% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 45 | BTCUSDT | LONG | 2026-05-03 01:07 | -0.50 | sl_hit | 10 | +0.27 | -0.51 | +9.27 | +10.60 | 389% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 46 | ETHUSDT | LONG | 2026-05-03 11:48 | +0.41 | tp1_hit | 4 | +0.62 | -0.10 | +3.91 | +4.99 | 204% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 47 | ETHUSDT | LONG | 2026-05-03 15:33 | +0.42 | tp1_hit | 7 | +0.48 | -0.07 | +4.36 | +5.44 | 219% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 48 | BTCUSDT | LONG | 2026-05-03 17:39 | +0.14 | tp1_hit | 5 | +0.15 | -0.18 | +9.32 | +10.66 | 391% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 49 | BTCUSDT | LONG | 2026-05-03 19:34 | +0.13 | tp1_hit | 6 | +0.18 | -0.11 | +9.34 | +10.68 | 392% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 50 | BTCUSDT | LONG | 2026-05-03 22:19 | +0.32 | tp1_hit | 1 | +0.55 | -0.23 | +9.76 | +11.10 | 406% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 51 | ETHUSDT | LONG | 2026-05-04 10:06 | -1.48 | timeout | 16 | +0.09 | -1.48 | +6.55 | +7.66 | 292% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 52 | BTCUSDT | SHORT | 2026-05-04 14:51 | -1.52 | sl_hit | 13 | +0.30 | -2.06 | +9.37 | +10.71 | 393% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 53 | ETHUSDT | SHORT | 2026-05-04 17:52 | -1.07 | sl_hit | 10 | +0.42 | -1.39 | +5.40 | +6.49 | 253% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 54 | BTCUSDT | LONG | 2026-05-04 22:54 | +0.06 | timeout | 16 | +0.42 | -0.20 | +11.21 | +12.57 | 456% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 55 | ETHUSDT | LONG | 2026-05-05 16:39 | -0.71 | sl_hit | 9 | +0.16 | -0.95 | +7.09 | +8.20 | 309% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 56 | BTCUSDT | LONG | 2026-05-05 20:03 | +0.39 | tp1_hit | 11 | +0.39 | -0.15 | +13.03 | +14.41 | 519% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 57 | BTCUSDT | LONG | 2026-05-06 14:07 | -1.03 | sl_hit | 4 | +0.02 | -1.24 | +14.12 | +15.51 | 556% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 58 | ETHUSDT | SHORT | 2026-05-07 13:42 | +0.46 | tp1_hit | 9 | +0.57 | -0.39 | +4.59 | +5.68 | 227% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 59 | BTCUSDT | SHORT | 2026-05-08 02:03 | +0.40 | tp1_hit | 11 | +0.44 | -0.29 | +10.99 | +12.35 | 449% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 60 | ETHUSDT | SHORT | 2026-05-08 08:05 | +0.10 | timeout | 16 | +0.68 | -0.09 | +2.55 | +3.61 | 159% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 61 | BTCUSDT | LONG | 2026-05-08 13:29 | -0.50 | sl_hit | 3 | +0.19 | -0.58 | +11.23 | +12.59 | 457% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 62 | BTCUSDT | LONG | 2026-05-08 15:24 | -0.50 | sl_hit | 4 | +0.21 | -0.54 | +11.31 | +12.67 | 460% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 63 | BTCUSDT | LONG | 2026-05-08 19:53 | +0.13 | timeout | 16 | +0.36 | -0.34 | +11.15 | +12.51 | 454% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 64 | BTCUSDT | LONG | 2026-05-08 22:05 | +0.16 | tp1_hit | 2 | +0.25 | +0.00 | +11.36 | +12.73 | 462% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 65 | BTCUSDT | LONG | 2026-05-10 11:03 | +0.12 | tp1_hit | 2 | +0.20 | -0.03 | +12.26 | +13.63 | 492% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 66 | BTCUSDT | LONG | 2026-05-10 13:26 | +0.15 | tp1_hit | 5 | +0.16 | +0.00 | +12.31 | +13.69 | 494% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 67 | BTCUSDT | LONG | 2026-05-10 20:49 | -0.57 | sl_hit | 8 | +0.25 | -1.22 | +12.91 | +14.29 | 514% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 68 | BTCUSDT | LONG | 2026-05-11 04:21 | -1.38 | timeout | 16 | +0.05 | -1.56 | +13.63 | +15.02 | 539% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 69 | ETHUSDT | SHORT | 2026-05-12 06:52 | +0.35 | tp1_hit | 6 | +0.48 | -0.01 | +3.95 | +5.03 | 205% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 70 | ETHUSDT | SHORT | 2026-05-12 11:10 | +0.47 | tp1_hit | 6 | +0.53 | -0.20 | +2.92 | +3.99 | 171% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 71 | ETHUSDT | SHORT | 2026-05-12 13:38 | +0.45 | tp1_hit | 6 | +0.60 | -0.23 | +2.83 | +3.90 | 168% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 72 | ETHUSDT | SHORT | 2026-05-12 22:07 | -0.78 | timeout | 16 | +0.05 | -0.87 | +2.06 | +3.12 | 143% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 73 | ETHUSDT | LONG | 2026-05-13 08:37 | +0.13 | tp1_hit | 2 | +0.13 | -0.06 | +3.43 | +4.50 | 188% | 22% | 0% | 1.1x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 74 | ETHUSDT | SHORT | 2026-05-13 22:37 | +0.36 | timeout | 16 | +0.52 | -0.10 | +1.64 | +2.69 | 129% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 75 | ETHUSDT | SHORT | 2026-05-14 00:49 | -0.50 | sl_hit | 5 | +0.12 | -0.53 | +1.42 | +2.48 | 122% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 76 | BTCUSDT | SHORT | 2026-05-14 02:56 | +0.32 | tp1_hit | 6 | +0.33 | -0.24 | +10.41 | +11.76 | 429% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 77 | ETHUSDT | SHORT | 2026-05-14 14:05 | +0.43 | tp1_hit | 2 | +0.44 | -0.19 | +1.43 | +2.48 | 122% | 22% | 0% | 1.1x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 78 | BTCUSDT | LONG | 2026-05-15 00:34 | +0.19 | tp1_hit | 1 | +0.32 | -0.05 | +13.07 | +14.46 | 520% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 79 | BTCUSDT | LONG | 2026-05-15 00:51 | +0.20 | tp1_hit | 1 | +0.22 | -0.07 | +13.07 | +14.46 | 520% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 80 | BTCUSDT | LONG | 2026-05-15 04:36 | -0.50 | sl_hit | 7 | +0.06 | -0.50 | +12.92 | +14.31 | 515% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 81 | ETHUSDT | SHORT | 2026-05-15 20:07 | +0.02 | timeout | 16 | +0.21 | -0.42 | -0.11 | +0.93 | 71% | 22% | 0% | 1.1x | setup limpo/sem anomalia visual óbvia |
| 82 | BTCUSDT | SHORT | 2026-05-16 02:52 | +0.04 | timeout | 16 | +0.15 | -0.12 | +9.92 | +11.26 | 412% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 83 | BTCUSDT | SHORT | 2026-05-16 06:21 | +0.20 | tp1_hit | 3 | +0.25 | -0.04 | +9.76 | +11.11 | 406% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 84 | BTCUSDT | SHORT | 2026-05-16 09:22 | +0.55 | tp1_hit | 4 | +0.75 | -0.05 | +9.04 | +10.37 | 382% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 85 | BTCUSDT | SHORT | 2026-05-16 15:23 | +0.02 | timeout | 16 | +0.37 | -0.29 | +8.52 | +9.85 | 364% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 86 | ETHUSDT | SHORT | 2026-05-16 22:09 | -0.14 | timeout | 16 | +0.03 | -0.37 | -2.19 | -1.17 | 2% | 22% | 0% | 1.1x | SHORT perto do fundo/suporte 24h; SHORT chase após queda rápida |
| 87 | BTCUSDT | SHORT | 2026-05-16 22:47 | +0.05 | tp1_hit | 2 | +0.06 | -0.04 | +8.68 | +10.01 | 369% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 88 | ETHUSDT | SHORT | 2026-05-17 00:59 | +0.07 | tp1_hit | 1 | +0.31 | -0.06 | -2.02 | -1.01 | 8% | 22% | 0% | 1.1x | SHORT perto do fundo/suporte 24h; SHORT chase após queda rápida |
| 89 | BTCUSDT | SHORT | 2026-05-17 05:11 | -0.52 | sl_hit | 10 | +0.08 | -0.52 | +8.23 | +9.56 | 354% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 90 | ETHUSDT | LONG | 2026-05-17 10:07 | +0.48 | tp1_hit | 15 | +0.51 | -0.10 | -1.85 | -0.83 | 13% | 22% | 0% | 1.1x | LONG perto do fundo/suporte 24h; LONG contra queda/faca caindo |
| 91 | BTCUSDT | LONG | 2026-05-17 14:19 | -0.50 | sl_hit | 11 | +0.20 | -0.69 | +8.89 | +10.23 | 377% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 92 | BTCUSDT | SHORT | 2026-05-17 20:10 | -0.33 | timeout | 16 | +0.29 | -0.49 | +8.46 | +9.79 | 362% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 93 | ETHUSDT | SHORT | 2026-05-18 06:08 | +0.27 | tp1_hit | 2 | +0.31 | -0.06 | -4.76 | -3.77 | -83% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 94 | BTCUSDT | SHORT | 2026-05-18 11:09 | +0.13 | timeout | 16 | +0.21 | -0.42 | +6.77 | +8.07 | 303% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 95 | BTCUSDT | SHORT | 2026-05-18 14:21 | +0.38 | tp1_hit | 3 | +0.69 | -0.24 | +6.90 | +8.21 | 308% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 96 | BTCUSDT | SHORT | 2026-05-18 21:06 | -0.31 | timeout | 16 | +0.61 | -0.75 | +6.42 | +7.72 | 292% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 97 | ETHUSDT | LONG | 2026-05-19 00:24 | +0.42 | tp1_hit | 5 | +0.62 | -0.28 | -4.14 | -3.14 | -62% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 98 | ETHUSDT | LONG | 2026-05-19 05:42 | +0.28 | tp1_hit | 2 | +0.29 | -0.33 | -4.27 | -3.28 | -67% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 99 | ETHUSDT | SHORT | 2026-05-23 05:38 | -0.01 | timeout | 16 | +0.15 | -0.34 | -7.22 | -6.26 | -165% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 100 | ETHUSDT | SHORT | 2026-05-23 12:53 | -0.02 | timeout | 16 | +0.15 | -0.29 | -8.80 | -7.85 | -217% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 101 | BTCUSDT | LONG | 2026-05-24 02:09 | +0.27 | timeout | 16 | +0.31 | -0.38 | +6.53 | +7.83 | 295% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 102 | ETHUSDT | LONG | 2026-05-24 03:05 | +0.24 | tp1_hit | 2 | +0.32 | -0.02 | -4.74 | -3.75 | -82% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 103 | ETHUSDT | LONG | 2026-05-24 06:56 | +0.31 | tp1_hit | 13 | +0.52 | -0.25 | -4.80 | -3.81 | -84% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 104 | ETHUSDT | LONG | 2026-05-24 12:20 | -0.06 | timeout | 16 | +0.32 | -0.09 | -4.71 | -3.72 | -81% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 105 | BTCUSDT | LONG | 2026-05-24 13:59 | -0.50 | sl_hit | 6 | +0.05 | -0.52 | +7.08 | +8.39 | 314% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 106 | ETHUSDT | SHORT | 2026-05-24 19:24 | -0.07 | timeout | 16 | +0.16 | -0.55 | -5.77 | -4.79 | -116% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 107 | ETHUSDT | SHORT | 2026-05-25 03:34 | +0.30 | tp1_hit | 2 | +0.34 | -0.02 | -5.67 | -4.69 | -113% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 108 | BTCUSDT | LONG | 2026-05-25 20:08 | -0.10 | timeout | 16 | +0.36 | -0.23 | +7.69 | +9.01 | 335% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 109 | ETHUSDT | SHORT | 2026-05-28 11:07 | -0.03 | timeout | 16 | +0.24 | -0.44 | -10.62 | -9.69 | -277% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 110 | ETHUSDT | SHORT | 2026-05-28 16:25 | -0.58 | sl_hit | 5 | +0.16 | -0.90 | -10.73 | -9.81 | -281% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 111 | BTCUSDT | LONG | 2026-05-29 02:56 | -0.50 | sl_hit | 15 | +0.36 | -0.53 | +2.24 | +3.49 | 148% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 112 | BTCUSDT | LONG | 2026-05-29 12:06 | -0.45 | timeout | 16 | +0.27 | -0.49 | +2.38 | +3.63 | 153% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 113 | BTCUSDT | LONG | 2026-05-29 22:25 | -0.42 | timeout | 16 | +0.03 | -0.88 | +2.56 | +3.82 | 159% | 35% | 0% | 1.6x | LONG rompendo topo 24h; LONG chase após subida rápida |
| 114 | BTCUSDT | SHORT | 2026-05-31 23:04 | -0.50 | sl_hit | 6 | +0.02 | -0.74 | +2.31 | +3.56 | 150% | 35% | 0% | 1.6x | SHORT rompendo topo 24h; SHORT contra alta/squeeze |
| 115 | ETHUSDT | SHORT | 2026-06-01 12:13 | +0.90 | tp1_hit | 9 | +1.02 | -0.06 | -10.70 | -9.77 | -280% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 116 | ETHUSDT | SHORT | 2026-06-01 13:58 | +0.96 | tp2_hit | 3 | +1.09 | -0.30 | -11.16 | -10.23 | -295% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 117 | ETHUSDT | SHORT | 2026-06-01 17:49 | -1.17 | sl_hit | 11 | +0.56 | -1.26 | -11.43 | -10.51 | -304% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 118 | BTCUSDT | SHORT | 2026-06-01 21:51 | +0.72 | timeout | 16 | +0.92 | -0.08 | -0.50 | +0.72 | 54% | 35% | 0% | 1.6x | setup limpo/sem anomalia visual óbvia |
| 119 | BTCUSDT | SHORT | 2026-06-02 01:42 | +0.57 | tp1_hit | 9 | +0.65 | -0.47 | -1.03 | +0.18 | 35% | 35% | 0% | 1.6x | setup limpo/sem anomalia visual óbvia |
| 120 | BTCUSDT | SHORT | 2026-06-02 06:50 | +1.32 | tp2_hit | 14 | +1.34 | -0.13 | -1.43 | -0.23 | 22% | 35% | 0% | 1.6x | SHORT perto do fundo/suporte 24h; SHORT chase após queda rápida |
| 121 | ETHUSDT | SHORT | 2026-06-02 09:07 | +0.50 | tp1_hit | 4 | +0.54 | -0.27 | -10.88 | -9.95 | -286% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 122 | ETHUSDT | SHORT | 2026-06-02 14:09 | +0.68 | tp1_hit | 15 | +0.68 | -0.18 | -11.04 | -10.12 | -291% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 123 | ETHUSDT | SHORT | 2026-06-02 19:33 | +2.03 | tp1_hit | 11 | +2.49 | -0.12 | -13.33 | -12.43 | -367% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 124 | BTCUSDT | SHORT | 2026-06-02 22:56 | +1.33 | tp1_hit | 9 | +1.43 | -0.88 | -6.48 | -5.33 | -152% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 125 | BTCUSDT | SHORT | 2026-06-03 03:30 | +1.24 | tp1_hit | 12 | +1.31 | -0.27 | -6.90 | -5.76 | -166% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 126 | BTCUSDT | SHORT | 2026-06-03 19:55 | +0.77 | tp1_hit | 5 | +1.12 | -0.15 | -8.23 | -7.11 | -212% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 127 | BTCUSDT | SHORT | 2026-06-04 08:55 | +0.69 | timeout | 16 | +1.26 | -0.67 | -11.02 | -9.93 | -308% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 128 | ETHUSDT | SHORT | 2026-06-05 01:02 | +0.88 | tp1_hit | 5 | +0.90 | -0.40 | -20.57 | -19.74 | -607% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 129 | BTCUSDT | SHORT | 2026-06-05 05:59 | +0.85 | tp1_hit | 7 | +0.95 | -1.30 | -12.66 | -11.60 | -365% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 130 | BTCUSDT | SHORT | 2026-06-05 11:24 | -0.16 | timeout | 16 | +0.36 | -1.36 | -13.30 | -12.24 | -386% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 131 | BTCUSDT | SHORT | 2026-06-05 18:44 | +1.86 | tp1_hit | 6 | +2.05 | -0.38 | -15.38 | -14.34 | -458% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 132 | BTCUSDT | SHORT | 2026-06-06 04:09 | +0.98 | tp1_hit | 12 | +1.19 | -0.31 | -15.11 | -14.07 | -448% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 133 | ETHUSDT | SHORT | 2026-06-06 10:55 | +0.92 | timeout | 16 | +1.57 | -2.11 | -29.91 | -29.18 | -916% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 134 | BTCUSDT | SHORT | 2026-06-06 15:51 | -0.02 | timeout | 16 | +0.72 | -0.58 | -15.50 | -14.46 | -462% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 135 | ETHUSDT | SHORT | 2026-06-06 20:21 | +0.21 | timeout | 16 | +0.56 | -0.70 | -30.11 | -29.38 | -922% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 136 | ETHUSDT | SHORT | 2026-06-06 23:45 | -0.69 | sl_hit | 12 | +0.27 | -0.82 | -30.10 | -29.38 | -922% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 137 | BTCUSDT | LONG | 2026-06-07 03:20 | +0.69 | tp1_hit | 3 | +0.88 | -0.07 | -14.93 | -13.89 | -442% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 138 | ETHUSDT | LONG | 2026-06-07 05:21 | +0.75 | tp2_hit | 4 | +1.35 | -0.14 | -28.63 | -27.89 | -874% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 139 | ETHUSDT | LONG | 2026-06-07 08:50 | +0.82 | tp1_hit | 3 | +1.52 | -0.01 | -27.66 | -26.90 | -841% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 140 | BTCUSDT | LONG | 2026-06-07 13:52 | -1.02 | timeout | 16 | +0.54 | -1.24 | -13.30 | -12.24 | -386% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 141 | BTCUSDT | LONG | 2026-06-07 17:15 | +0.44 | tp1_hit | 6 | +0.46 | -0.12 | -13.82 | -12.77 | -404% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 142 | ETHUSDT | LONG | 2026-06-08 03:21 | +0.19 | timeout | 16 | +1.71 | -0.71 | -24.39 | -23.61 | -733% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 143 | BTCUSDT | LONG | 2026-06-08 09:18 | +0.62 | tp1_hit | 11 | +0.81 | -0.41 | -12.39 | -11.32 | -355% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 144 | ETHUSDT | LONG | 2026-06-08 11:19 | +0.82 | tp1_hit | 5 | +1.01 | -0.39 | -24.98 | -24.20 | -753% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 145 | ETHUSDT | LONG | 2026-06-08 15:04 | +0.93 | tp1_hit | 3 | +0.99 | -0.15 | -24.37 | -23.59 | -732% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 146 | ETHUSDT | LONG | 2026-06-08 17:07 | -0.88 | sl_hit | 3 | +0.37 | -0.93 | -24.01 | -23.22 | -720% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 147 | ETHUSDT | LONG | 2026-06-08 21:12 | +1.32 | tp2_hit | 13 | +1.34 | -0.75 | -24.01 | -23.22 | -720% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 148 | ETHUSDT | LONG | 2026-06-09 00:29 | -1.02 | sl_hit | 7 | +1.05 | -1.41 | -23.78 | -22.99 | -713% | 22% | 0% | 1.1x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 149 | ETHUSDT | SHORT | 2026-06-09 09:38 | +0.59 | tp1_hit | 2 | +0.78 | -0.13 | -24.61 | -23.83 | -740% | 22% | 0% | 1.1x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 150 | BTCUSDT | SHORT | 2026-06-09 21:54 | -0.11 | timeout | 16 | +0.07 | -1.02 | -14.37 | -13.32 | -423% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 151 | BTCUSDT | SHORT | 2026-06-10 02:17 | +0.48 | tp1_hit | 1 | +0.62 | -0.16 | -14.24 | -13.19 | -419% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 152 | BTCUSDT | SHORT | 2026-06-10 04:40 | +0.51 | tp1_hit | 3 | +0.60 | -0.02 | -14.50 | -13.45 | -428% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 153 | BTCUSDT | SHORT | 2026-06-10 09:19 | +0.44 | tp1_hit | 11 | +0.49 | -0.75 | -14.78 | -13.73 | -437% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 154 | BTCUSDT | SHORT | 2026-06-10 12:36 | -0.76 | sl_hit | 8 | +0.78 | -0.98 | -14.78 | -13.74 | -437% | 35% | 0% | 1.6x | SHORT rompendo fundo 24h; SHORT chase após queda rápida |
| 155 | BTCUSDT | LONG | 2026-06-10 15:48 | +0.93 | tp1_hit | 2 | +1.13 | -0.03 | -14.05 | -13.00 | -412% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
| 156 | BTCUSDT | LONG | 2026-06-10 21:52 | -1.51 | timeout | 16 | +0.06 | -1.52 | -13.66 | -12.60 | -399% | 35% | 0% | 1.6x | LONG rompendo fundo 24h; LONG contra queda/faca caindo |
