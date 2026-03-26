import time
import database as db
from config import SYMBOLS, INTERVAL, LIMIT, ALERT_PRIORITY_MIN, SMA_SHORT, SMA_LONG, BREAKOUT_WINDOW
from telegram_commands import start_command_listener, is_paused
from market import get_candles
from indicators import add_indicators
from strategy import generate_signal
from htf import get_htf_data
from logger import save_log
from alert_logger import save_alert
from exporter import export_analysis
from opportunity_exporter import export_relevant_opportunities
from telegram_notifier import send_telegram_message
from alert_control import should_send_alert
from paper_trader import process_signals, get_status
from agent_brain import analyze_market
from agent_executor import load_agent_state, execute_decisions, check_stops, save_agent_state
from daily_report import check_daily_report, is_circuit_broken


def run_bot():
    results = []
    market_data = {}  # dados brutos para o Agent V2

    for symbol in SYMBOLS:
        try:
            df = get_candles(symbol, INTERVAL, LIMIT)
            df = add_indicators(df)
            htf_data = get_htf_data(symbol)
            htf_trend = htf_data["trend"]

            result = generate_signal(df, htf_trend=htf_trend)
            result["symbol"] = symbol
            results.append(result)

            # Dados brutos para o Agent V2
            last = df.iloc[-2]
            price = float(last["close"])
            atr14 = float(last["atr14"])
            market_data[symbol] = {
                "price": price,
                "sma9":  round(float(last[f"sma_{SMA_SHORT}"]), 6),
                "sma21": round(float(last[f"sma_{SMA_LONG}"]),  6),
                "rsi":   round(float(last["rsi"]), 2),
                "atr14": round(atr14, 6),
                "atr_pct": round(atr14 / price * 100, 4) if price > 0 else 0,
                "body_ratio": round(float(last["body_ratio"]), 4),
                "volume_above_avg": float(last["volume"]) > float(last["volume_avg"]),
                "recent_high": round(float(last[f"recent_high_{BREAKOUT_WINDOW}"]), 6),
                "recent_low":  round(float(last[f"recent_low_{BREAKOUT_WINDOW}"]),  6),
                "htf": htf_data,
            }

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
            print(f"ATR14 (1h): {htf_data['atr14']:.4f}")
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

    best_buy  = sorted(results, key=lambda x: x["buy_score"],  reverse=True)
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
        top = relevant[0]

        print(
            f"{top['symbol']} | "
            f"Tipo: {top['opportunity_type']} | "
            f"Lado dominante: {top['dominant_side']} | "
            f"Decisão: {top['decision']} | "
            f"Priority Score: {top['priority_score']} | "
            f"Confiança: {top['confidence_score']}/100 | "
            f"Motivo: {top['reason']}"
        )

        if (
            top["opportunity_type"] == "sinal"
            or top["priority_score"] >= ALERT_PRIORITY_MIN
        ):
            if should_send_alert(top):
                header = f"Oportunidade detectada - {top['symbol']}\n\n"
                data_block = (
                    f"Decisao: {top['decision']}\n"
                    f"Tipo: {top['opportunity_type']}\n"
                    f"Lado: {top['dominant_side']}\n"
                    f"Confianca: {top['confidence_score']}/100\n"
                    f"Priority: {top['priority_score']}"
                )
                send_telegram_message(f"{header}{top['reason']}\n\n{data_block}")
    else:
        print("Nenhuma oportunidade relevante neste ciclo.")

    # Paper Trading (benchmark — nao usa Claude)
    print("\n========================================")
    print("PAPER TRADING\n")

    if is_circuit_broken("paper") or is_paused():
        print("  Circuit breaker ativo ou bot pausado - paper trading suspenso")
    else:
        paper_msgs = process_signals(results)
        for msg in paper_msgs:
            print(f"  {msg}")
            send_telegram_message(f"[PAPER] {msg}")

    print(f"\n  {get_status()}")

    # Agent V2 Trading (Claude como decisor principal)
    print("\n========================================")
    print("AGENT V2 TRADING\n")

    if not market_data:
        print("  Sem dados de mercado - agent trading suspenso")
    elif is_circuit_broken("agent") or is_paused():
        print("  Circuit breaker ativo ou bot pausado - agent trading suspenso")
        # Safety net ainda roda para proteger posicoes abertas
        agent_state = load_agent_state()
        if agent_state.get("positions"):
            check_stops(agent_state, market_data)
            save_agent_state(agent_state)
    else:
        agent_state = load_agent_state()
        trade_history = db.get_trade_stats("agent_trades", 20)
        decisions = analyze_market(market_data, agent_state, trade_history)
        execute_decisions(decisions, agent_state, market_data)

    # Daily Report (envia 1x por dia apos meia-noite)
    check_daily_report()


if __name__ == "__main__":
    db.init_db()
    start_command_listener()
    while True:
        try:
            run_bot()
            print("\nAguardando 300 segundos para a próxima análise...\n")
            time.sleep(300)
        except Exception as e:
            print(f"Erro: {e}")
            print("Tentando novamente em 300 segundos...\n")
            time.sleep(300)
