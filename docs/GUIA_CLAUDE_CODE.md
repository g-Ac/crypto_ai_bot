# Guia do Claude Code no Raspberry Pi

> Referencia rapida para usar o Claude Code como segundo cerebro do crypto_ai_bot.

---

## Como abrir

```bash
cd ~/crypto_ai_bot
claude
```

**Sempre entre no diretorio do projeto antes.** Assim o Claude carrega o CLAUDE.md e os commands automaticamente.

---

## Skills (Slash Commands)

Digite dentro do Claude:

| Comando | O que faz |
|---|---|
| `/monitor` | Check rapido: servico, temp, RAM, disco, ultima decision, erros |
| `/audit` | Auditoria completa com 4 agentes paralelos (performance, erros, saude, estrategia) |
| `/evolve` | Analisa estado atual e propoe a PROXIMA melhoria concreta |
| `/fix` | Diagnostica e corrige problemas automaticamente |
| `/backtest-check` | Roda backtests e compara com versao anterior |
| `/report` | Relatorio diario quantitativo (edge, Sharpe, funil) |
| `/security` | Auditoria de seguranca (secrets, rede, SQL, deps) |
| `/simplify` | Review de codigo por qualidade e reuso |
| `/loop 5m /monitor` | Roda /monitor a cada 5 min (qualquer intervalo) |

---

## Agents Customizados

Agents sao "especialistas" que o Claude lanca em paralelo para tarefas complexas.

| Agent | Modelo | Especialidade |
|---|---|---|
| `bug-hunter` | Sonnet | Encontra bugs, vulnerabilidades, problemas |
| `performance-analyst` | Sonnet | Analise quantitativa de performance e edge |
| `architect` | Opus | Planeja evolucoes com visao de sistema |
| `security-auditor` | Sonnet | Seguranca: secrets, rede, SQL injection |

Os agents sao usados automaticamente pelos slash commands, ou voce pode pedir: "lanca o bug-hunter no scalping_trader.py".

---

## Fluxo de trabalho recomendado

```
/monitor          → "ta tudo ok?"
/audit            → "como ta a performance?"
/evolve           → "qual a proxima melhoria?"
                  → Claude implementa
/backtest-check   → "melhorou ou piorou?"
/report           → "me da o resumo do dia"
```

### Ciclo de evolucao

```
1. /audit → identifica gap
2. /evolve → propoe melhoria
3. Claude implementa (testes rodam automaticamente)
4. /backtest-check → valida
5. sudo systemctl restart cryptobot → deploy
6. /monitor → confirma que ta rodando
7. Repete
```

---

## Monitoramento continuo

Dentro de uma sessao:

```
/loop 5m /monitor     # monitora a cada 5 min
/loop 10m /monitor    # a cada 10 min
/loop 30m /audit      # auditoria a cada 30 min
```

Dura enquanto a sessao estiver aberta.

---

## Hooks automaticos

| Evento | Acao |
|---|---|
| Qualquer `.py` editado ou criado | Roda pytest automaticamente |

---

## Permissoes automaticas

Estes comandos rodam sem pedir confirmacao:
- Python, pip, pytest
- git (todos)
- systemctl status/restart/stop
- journalctl
- sqlite3
- vcgencmd, free, df, du, ss, uptime
- ls, cat, head, tail, mkdir, cp, mv, chmod
- npm, node, claude

---

## Dicas

- **Fale naturalmente**: "corrige o bug do ATR", "roda o monitor", "o que ta errado?"
- **Agentes paralelos**: o Claude pode lançar 4-5 agentes ao mesmo tempo
- **Duas sessoes**: abre outro terminal + `claude` para sessoes simultaneas
- **Memoria**: o Claude lembra decisoes e preferencias entre sessoes
- **Autonomia**: o Claude e socio — pode propor, questionar, implementar
- **Seguranca**: nunca commita .env ou secrets. O Claude sabe disso

---

## Comandos uteis do sistema

```bash
# Status do bot
sudo systemctl status cryptobot

# Logs ao vivo
journalctl -u cryptobot -f

# Reiniciar bot
sudo systemctl restart cryptobot

# Temperatura
vcgencmd measure_temp

# RAM
free -h

# Disco
df -h /

# Banco de dados
sqlite3 runtime/baseline/bot.db ".tables"
```

---

## Estrutura de arquivos do Claude

```
~/.claude/
  settings.json          # config global (modelo, permissoes, hooks)
  agents/                # agents customizados
    bug-hunter.md
    performance-analyst.md
    architect.md
    security-auditor.md
  commands/              # skills globais
    audit.md, evolve.md, monitor.md, fix.md, backtest-check.md

~/crypto_ai_bot/.claude/
  commands/              # skills do projeto (versionaveis no git)
    audit.md, evolve.md, monitor.md, fix.md
    backtest-check.md, report.md, security.md
```
