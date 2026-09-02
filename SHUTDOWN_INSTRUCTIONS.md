# Instruções de Desligamento — 02/09/2026

**Status:** Projeto encerrado. Momentum parado, EXP-019 em coleta passiva.

---

## Checklist de Desligamento (executo quando Pi tiver conectividade)

### 1. Parar Momentum Pullback v1.1

```bash
ssh gac@192.168.0.208
cd ~/crypto-ai-bot  # ou caminho correto
export MOMENTUM_TRADER_ENABLED=false
sudo systemctl restart cryptobot
```

Validar:
```bash
curl http://localhost:5000/api/status | jq .momentum
# deve retornar: { "enabled": false, "positions": 0, "trades": 299 }
```

### 2. Deixar EXP-019 (VRP Collector) Rodando

```bash
# Verificar que está ativo
ps aux | grep collector  # ou ps aux | grep "exp_019"
# Deve haver um cron job rodando `/exp_019_collector.py` ou similar

# Se não estiver rodando:
crontab -e
# Adicionar (se não houver):
# * * * * * cd ~/crypto-ai-bot && python exp_019_collector.py >> /var/log/exp_019.log 2>&1
```

### 3. Verificar Coleta de Opções

```bash
ls -lah ~/crypto-ai-bot/exp_019/  # ou diretório de dados de opções
# Deve haver arquivo de estado com timestamp recente

# Query banco de dados:
sqlite3 ~/crypto-ai-bot/runtime/baseline/bot.db \
  "SELECT COUNT(*), MAX(timestamp) FROM option_prices;" 
# Esperar: n > 100.000, timestamp recente (< 1 dia)
```

### 4. Desativar Dashboard & Telegram (opcional)

Se quiser desligar completamente:

```bash
export DASHBOARD_ENABLED=false
# Ou simplesmente não rodar dashboard_server.py

# Telegram ficará silencioso naturalmente (sem trades pra reportar)
```

### 5. Arquivar Logs e Banco de Dados

```bash
# Backup do banco (299 trades, 51 campos cada):
cp ~/crypto-ai-bot/runtime/baseline/bot.db \
   ~/crypto-ai-bot/backups/bot_final_$(date +%Y%m%d).db

# Arquivar logs:
tar -czf ~/crypto-ai-bot/logs/logs_$(date +%Y%m%d).tar.gz \
  ~/crypto-ai-bot/logs/*.log
```

---

## Estado Esperado Pós-Desligamento

| Sistema | Status | Motivo |
|---|---|---|
| `cryptobot` (systemd) | Rodando | Mantém coletores e infraestrutura |
| Momentum Pullback | ❌ Parado | `MOMENTUM_TRADER_ENABLED=false` |
| VRP Collector (EXP-019) | ✅ Coleta ativa | Cron simples, rodando 24/7 |
| Dashboard web (/5000) | ✅ Ativo | Mostra status leitura, sem trades novos |
| Telegram bot | ✅ Rodando | Nenhuma notificação (sem operação) |
| Banco de dados | ✅ Arquivo | SQLite WAL com 299 trades históricos |

---

## Julgamento Final (01/09)

**Quando:** 01/09/2026 (ou 1 dia após coleta atingir 60+ dias)

```bash
# Query os dados coletados:
python exp_019_final_judgement.py

# Esperar output tipo:
# EXP-019 VRP: 60 dias coleta, mediana +X%, media -Y%, caudas [-0.39, -0.48]
# Veredito: GO / NO-GO
```

**Se GO:** Ressuscitar momentum (não recomendado)
**Se NO-GO:** Fim do projeto, arquivo tudo

---

## Arquivos Importantes Pra Preservar

Se por algum motivo o Pi falhar irrecuperavelmente:

```bash
# Banco de dados (51 campos × 299 trades):
~/crypto-ai-bot/runtime/baseline/bot.db

# Logs operacionais:
~/crypto-ai-bot/logs/

# Dados de opções (EXP-019):
~/crypto-ai-bot/exp_019/  (ou diretório equivalente)

# Post-mortem:
~/crypto-ai-bot/PROJECT_POSTMORTEM.md
~/crypto-ai-bot/docs/EXPERIMENT_REGISTRY.md
```

---

## Rollback (Se Precisar Rodar Novamente)

```bash
export MOMENTUM_TRADER_ENABLED=true
sudo systemctl restart cryptobot

# Validar:
curl http://localhost:5000/api/status | jq .momentum
# Deve estar operando novamente
```

(Não recomendado, mas está documentado para referência futura.)

---

**Escrito:** 02/09/2026
**Versão:** 1.0
**Próxima revisão:** 01/09/2026 (julgamento final EXP-019)
