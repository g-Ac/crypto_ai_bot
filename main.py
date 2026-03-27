import time
import database as db
from config import SYMBOLS, INTERVAL, LIMIT, ALERT_PRIORITY_MIN
from telegram_commands import start_command_listener, is_paused
from market import get_candles
from indicators import add_indicators
from strategy import generate_signal
from htf import get_htf_trend
from logger import save_log
from alert_logger import save_alert
from exporter import export_analysis
from opportunity_exporter import export_relevant_opportunities
from telegram_notifier import send_telegram_message
from alert_control import should_send_alert
from context_agent import interpret_signal
from paper_trader import process_signals, get_status
from trade_agents import orchestrate, get_agent_status
from daily_report import check_daily_report, is_circuit_broken

def run_bot():
    results = []

    for symbol in SYMBOLS:
        try:
            df = get_candles(symbol, INTERVAL, LIMIT)
            df = add_indicators(df)
            htf_trend = get_htf_trend(symbol)
            result = generate_signal(df, htf_trend=htf_trend)
            result["symbol"] = symbol
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

        if (
            top_opportunity["opportunity_type"] == "sinal"
            or top_opportunity["priority_score"] >= ALERT_PRIORITY_MIN
        ):
            if should_send_alert(top_opportunity):
                interpretation = interpret_signal(top_opportunity)

                header = (
                    f"Oportunidade detectada - {top_opportunity['symbol']}\n\n"
                )
                data_block = (
                    f"Decisao: {top_opportunity['decision']}\n"
                    f"Tipo: {top_opportunity['opportunity_type']}\n"
                    f"Lado: {top_opportunity['dominant_side']}\n"
                    f"Confianca: {top_opportunity['confidence_score']}/100\n"
                    f"Priority: {top_opportunity['priority_score']}"
                )

                if interpretation:
                    message = f"{header}{interpretation}\n\n{data_block}"
                else:
                    message = f"{header}{top_opportunity['reason']}\n\n{data_block}"

                send_telegram_message(message)
    else:
        print("Nenhuma oportunidade relevante neste ciclo.")

    # Paper Trading
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

    # Multi-Agent Trading
    print("\n========================================")
    print("MULTI-AGENT TRADING\n")

    if is_circuit_broken("agent") or is_paused():
        print("  Circuit breaker ativo ou bot pausado - agent trading suspenso")
    else:
        agent_msgs = orchestrate(results)
        for msg in agent_msgs:
            print(f"  {msg}")
            send_telegram_message(msg)

    print(f"\n  {get_agent_status()}")

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