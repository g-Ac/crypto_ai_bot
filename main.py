import time
import shutil
import threading
from datetime import datetime
import database as db
import config as cfg
from config import SYMBOLS, INTERVAL, LIMIT
from telegram_commands import start_command_listener, is_paused
from market import get_candles
from indicators import add_indicators
from strategy import generate_signal
from htf import get_htf_trend
from logger import save_log
from exporter import export_analysis
from opportunity_exporter import export_relevant_opportunities
from telegram_notifier import send_telegram_message
from htf import get_htf_regime
from market_data import collect_microstructure
from daily_report import check_daily_report, enforce_circuit_breaker
from momentum.paper_executor import process_momentum_cycle, get_momentum_status
from runtime_config import BOT_ID, ENABLE_TELEGRAM_COMMANDS, runtime_metadata

# ── Disk space check ────────────────────────────────────────────────────────
DISK_MIN_FREE_MB = 500
_DISK_ALERT_INTERVAL = 3600  # maximo 1 alerta por hora
_last_disk_alert_time = 0.0


def check_disk_space():
    """Verifica espaco livre em disco. Alerta via Telegram se < 500MB (max 1x/hora)."""
    global _last_disk_alert_time
    try:
        usage = shutil.disk_usage(".")
        free_mb = usage.free / (1024 * 1024)
        if free_mb < DISK_MIN_FREE_MB:
            print(f"  [AVISO] Espaco em disco baixo: {free_mb:.0f}MB livres (minimo: {DISK_MIN_FREE_MB}MB)")
            now = time.time()
            if now - _last_disk_alert_time >= _DISK_ALERT_INTERVAL:
                _last_disk_alert_time = now
                try:
                    from telegram_notifier import send_system_alert
                    send_system_alert(
                        "Disco quase cheio",
                        f"Espaco livre: <b>{free_mb:.0f}MB</b> (minimo: {DISK_MIN_FREE_MB}MB).\n"
                        f"Limpe logs ou dados antigos para evitar crash.",
                        critical=True,
                    )
                except Exception as e:
                    print(f"  [ERRO] Falha ao enviar alerta de disco: {e}")
        else:
            print(f"  Espaco em disco: {free_mb:.0f}MB livres - OK")
    except Exception as e:
        print(f"  [ERRO] Falha ao verificar espaco em disco: {e}")

_last_prune_day = None


def run_bot():
    global _last_prune_day
    # Verificar espaco em disco antes de tudo
    check_disk_space()

    # Pruning diario de microestrutura (manter 60 dias de granularidade)
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _last_prune_day != today_str:
        try:
            removed = db.prune_microstructure(keep_days=60)
            if removed:
                print(f"  [PRUNING] Removidos {removed} registos de microestrutura (>60 dias)")
            _last_prune_day = today_str
        except Exception as e:
            print(f"  [AVISO] Erro no pruning de microestrutura: {e}")

    results = []

    for symbol in SYMBOLS:
        try:
            df = get_candles(symbol, INTERVAL, LIMIT)
            df = add_indicators(df)
            htf_trend = get_htf_trend(symbol)
            regime = get_htf_regime(symbol)
            result = generate_signal(df, htf_trend=htf_trend)
            result["symbol"] = symbol
            result.update(regime)  # adx_1h, atr_1h_pct, bb_width_1h, regime_label

            # Coleta de microestrutura (funding, OI, liquidacoes, basis)
            try:
                micro = collect_microstructure(symbol)
                db.insert_market_microstructure(micro)
                result["_microstructure"] = micro
                print(f"  Microstructure data collected for {symbol}")
            except Exception as e:
                print(f"  [AVISO] Falha na coleta de microestrutura para {symbol}: {e}")

            results.append(result)

            print("\n==============================")
            print(f"Análise de {symbol} ({INTERVAL})\n")
            print(f"Horário da vela analisada: {result['candle_time']}")
            print(f"Preço atual: {result['price']:.2f}")
            print(f"SMA 9: {result['sma_9']:.2f}")
            print(f"SMA 21: {result['sma_21']:.2f}")
            print(f"Tendência: {result['trend']}")
            print(f"RSI: {result['rsi']:.2f}")
            print(f"Status do RSI: {result['rsi_status']}")
            print(f"Posição do preço: {result['price_position']}")
            print(f"Direção SMA 9: {result['sma_9_direction']}")
            print(f"Direção SMA 21: {result['sma_21_direction']}")
            print(f"Breakout: {result['breakout_status']}")
            print(f"Volume acima da média: {result['volume_above_avg']}")
            print(f"Body ratio: {result['body_ratio']}")
            print(f"Tendência 1h: {result['htf_trend']}")
            print(f"Alinhado com 1h: {result['htf_aligned']}")
            print(f"Regime: {result.get('regime_label', '?')} (ADX={result.get('adx_1h', 0):.1f})")
            print(f"Score BUY: {result['buy_score']}")
            print(f"Score SELL: {result['sell_score']}")
            print(f"Força do sinal: {result['signal_strength']}")
            print(f"Confiança do sinal: {result['confidence_score']}/100")
            print(f"Priority Score: {result['priority_score']}")
            print(f"Sinal: {result['decision']}")
            print(f"Motivo: {result['reason']}")

            save_log(result)

        except Exception as e:
            print(f"\n[ERRO] Falha ao processar {symbol}: {e}")
            print(f"Continuando com os próximos ativos...")

    export_analysis(results)
    export_relevant_opportunities(results)

    print("\n========================================")
    print("RESUMO DAS MELHORES OPORTUNIDADES\n")

    best_buy = sorted(results, key=lambda x: x["buy_score"], reverse=True)
    best_sell = sorted(results, key=lambda x: x["sell_score"], reverse=True)

    print("Top 3 compra:")
    for item in best_buy[:3]:
        print(
            f"{item['symbol']} | BUY Score: {item['buy_score']} | "
            f"Força: {item['signal_strength']} | Decisão: {item['decision']}"
        )

    print("\nTop 3 venda:")
    for item in best_sell[:3]:
        print(
            f"{item['symbol']} | SELL Score: {item['sell_score']} | "
            f"Força: {item['signal_strength']} | Decisão: {item['decision']}"
        )

    print("\n========================================")
    print("OPORTUNIDADES RELEVANTES\n")

    relevant = sorted(
        [item for item in results if item["opportunity_type"] in ["pre_sinal", "sinal"]],
        key=lambda x: x["priority_score"],
        reverse=True
    )

    if relevant:
        for item in relevant:
            print(
                f"{item['symbol']} | "
                f"Tipo: {item['opportunity_type']} | "
                f"Decisão: {item['decision']} | "
                f"Priority Score: {item['priority_score']} | "
                f"BUY Score: {item['buy_score']} | "
                f"SELL Score: {item['sell_score']} | "
                f"Diferença: {item['score_difference']} | "
                f"Força: {item['signal_strength']} | "
                f"Motivo: {item['reason']}"
            )
    else:
        print("Nenhuma oportunidade relevante neste ciclo.")

    print("\n========================================")
    print("TOP 1 DO CICLO\n")

    if relevant:
        top_opportunity = relevant[0]

        print(
            f"{top_opportunity['symbol']} | "
            f"Tipo: {top_opportunity['opportunity_type']} | "
            f"Lado dominante: {top_opportunity['dominant_side']} | "
            f"Decisão: {top_opportunity['decision']} | "
            f"Priority Score: {top_opportunity['priority_score']} | "
            f"Confiança: {top_opportunity['confidence_score']}/100 | "
            f"Motivo: {top_opportunity['reason']}"
        )
    else:
        print("Nenhuma oportunidade relevante neste ciclo.")

    # ── Gerenciamento de posicoes ────────────────────────────────────
    # C4: Cada bloco de trader e isolado para que falha em um nao
    # impeca o gerenciamento de posicoes nos demais.  Se o check de
    # circuit breaker falhar, assumimos suspended=True (fallback seguro:
    # gerencia posicoes abertas, nao abre novas).

    # Momentum Pullback Strategy
    if cfg.MOMENTUM_TRADER_ENABLED:
        print("\n========================================")
        print("MOMENTUM PULLBACK STRATEGY\n")

        try:
            try:
                momentum_suspended = enforce_circuit_breaker("momentum") or is_paused()
            except Exception as e:
                print(f"  [ERRO] Falha ao verificar circuit breaker momentum: {e}")
                momentum_suspended = True
            if momentum_suspended:
                print("  Circuit breaker ativo ou bot pausado - gerenciando posicoes")
            momentum_msgs = process_momentum_cycle(
                cfg.MOMENTUM_SYMBOLS,
                open_new=not momentum_suspended,
            )
            for msg in momentum_msgs:
                print(f"  {msg}")
                send_telegram_message(f"\U0001f4c8 <b>[MOMENTUM]</b> {msg}")
            print(f"\n  {get_momentum_status()}")
        except Exception as e:
            print(f"  [ERRO] Falha no momentum pullback: {e}")
    else:
        print("\n========================================")
        print("MOMENTUM PULLBACK: DESABILITADO (MOMENTUM_TRADER_ENABLED=false)\n")

    # Daily Report (envia 1x por dia apos meia-noite)
    try:
        check_daily_report()
    except Exception:
        import traceback
        print(f"  [ERRO] Falha no daily report:\n{traceback.format_exc()}")

    # Alertas proativos (drawdown, zero trades, erros repetidos)
    try:
        from proactive_alerts import check_proactive_alerts
        check_proactive_alerts()
    except Exception:
        import traceback
        print(f"  [ERRO] Falha nos alertas proativos:\n{traceback.format_exc()}")


_cycle_lock = threading.Lock()

if __name__ == "__main__":
    db.init_db()
    print(f"[BOOT] Instancia: {BOT_ID}")
    print(f"[BOOT] Runtime: {runtime_metadata()['runtime_dir']}")
    print(f"[BOOT] Analysis symbols: {SYMBOLS}")
    if ENABLE_TELEGRAM_COMMANDS:
        start_command_listener()
    else:
        print("[BOOT] Listener de comandos Telegram desabilitado para esta instancia.")
    while True:
        try:
            if _cycle_lock.acquire(blocking=False):
                try:
                    run_bot()
                finally:
                    _cycle_lock.release()
            else:
                print("\n[AVISO] Ciclo anterior ainda em execucao, pulando...\n")
            print("\nAguardando 300 segundos para a próxima análise...\n")
            time.sleep(300)
        except Exception as e:
            print(f"Erro: {e}")
            print("Tentando novamente em 300 segundos...\n")
            time.sleep(300)
