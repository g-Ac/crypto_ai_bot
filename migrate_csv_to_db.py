"""
Migração única: importa dados históricos dos CSVs para o bot.db SQLite.
Execute uma vez antes de rodar o bot com a nova versão.

  python migrate_csv_to_db.py
"""
import csv
import os
import sqlite3
import database as db

# Paths relativos ao diretório do script
BASE = os.path.dirname(os.path.abspath(__file__))


def _get_conn():
    conn = sqlite3.connect(db.DB_FILE, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrate_log():
    """log.csv ->analysis_log"""
    path = os.path.join(BASE, "log.csv")
    if not os.path.isfile(path):
        print("  log.csv não encontrado, pulando.")
        return 0

    conn = _get_conn()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                conn.execute("""
                    INSERT INTO analysis_log (
                        timestamp, symbol, candle_time, price,
                        sma_9, sma_21, trend, rsi, rsi_status,
                        price_position, sma_9_direction, sma_21_direction,
                        breakout_status, buy_score, sell_score,
                        signal_strength, decision, confidence_score, reason
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    row.get("timestamp", ""),
                    row.get("symbol", ""),
                    None,  # candle_time não existia no CSV
                    _f(row.get("price")),
                    _f(row.get("sma_9")),
                    _f(row.get("sma_21")),
                    row.get("trend", ""),
                    _f(row.get("rsi")),
                    row.get("rsi_status", ""),
                    row.get("price_position", ""),
                    row.get("sma_9_direction", ""),
                    row.get("sma_21_direction", ""),
                    row.get("breakout_status", ""),
                    _i(row.get("buy_score")),
                    _i(row.get("sell_score")),
                    row.get("signal_strength", ""),
                    row.get("decision", ""),
                    None,  # confidence_score não existia no CSV
                    row.get("reason", ""),
                ))
                count += 1
            except Exception as e:
                print(f"  [AVISO] Linha ignorada em log.csv: {e}")
    conn.commit()
    conn.close()
    return count


def migrate_alerts():
    """alerts.csv ->alerts (sem header no CSV)"""
    path = os.path.join(BASE, "alerts.csv")
    if not os.path.isfile(path):
        print("  alerts.csv não encontrado, pulando.")
        return 0

    # O arquivo foi gravado sem linha de header pelo alert_logger antigo
    ALERT_COLS = [
        "timestamp", "symbol", "alert_type", "price", "trend",
        "rsi", "rsi_status", "buy_score", "sell_score",
        "signal_strength", "decision", "reason",
    ]

    conn = _get_conn()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
        f.seek(0)

        # Detecta se tem header ou não
        has_header = first_line.startswith("timestamp")
        reader = csv.DictReader(f, fieldnames=None if has_header else ALERT_COLS)

        for row in reader:
            if has_header and row.get("timestamp") == "timestamp":
                continue  # pula a linha de header se DictReader a incluir
            try:
                conn.execute("""
                    INSERT INTO alerts (
                        timestamp, symbol, alert_type, price, trend,
                        rsi, rsi_status, buy_score, sell_score,
                        signal_strength, decision, reason
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    row.get("timestamp", ""),
                    row.get("symbol", ""),
                    row.get("alert_type", ""),
                    _f(row.get("price")),
                    row.get("trend", ""),
                    _f(row.get("rsi")),
                    row.get("rsi_status", ""),
                    _i(row.get("buy_score")),
                    _i(row.get("sell_score")),
                    row.get("signal_strength", ""),
                    row.get("decision", ""),
                    row.get("reason", ""),
                ))
                count += 1
            except Exception as e:
                print(f"  [AVISO] Linha ignorada em alerts.csv: {e}")
    conn.commit()
    conn.close()
    return count


def migrate_paper_trades():
    """paper_trades.csv ->paper_trades"""
    return _migrate_simple(
        "paper_trades.csv",
        "paper_trades",
        """INSERT INTO paper_trades
           (timestamp, symbol, type, entry_price, exit_price,
            pnl_pct, pnl_usd, exit_reason, capital_after)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        lambda r: (
            r.get("timestamp", ""), r.get("symbol", ""), r.get("type", ""),
            _f(r.get("entry_price")), _f(r.get("exit_price")),
            _f(r.get("pnl_pct")), _f(r.get("pnl_usd")),
            r.get("exit_reason", ""), _f(r.get("capital_after")),
        ),
    )


def migrate_agent_trades():
    """agent_trades.csv ->agent_trades"""
    return _migrate_simple(
        "agent_trades.csv",
        "agent_trades",
        """INSERT INTO agent_trades
           (timestamp, symbol, type, entry_price, sl_price, tp_price,
            position_size_usd, exit_price, pnl_pct, pnl_usd,
            exit_reason, analyst_confidence, capital_after)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        lambda r: (
            r.get("timestamp", ""), r.get("symbol", ""), r.get("type", ""),
            _f(r.get("entry_price")), _f(r.get("sl_price")), _f(r.get("tp_price")),
            _f(r.get("position_size_usd")), _f(r.get("exit_price")),
            _f(r.get("pnl_pct")), _f(r.get("pnl_usd")),
            r.get("exit_reason", ""), _i(r.get("analyst_confidence")),
            _f(r.get("capital_after")),
        ),
    )


def migrate_pump_trades():
    """pump_trades.csv ->pump_trades"""
    return _migrate_simple(
        "pump_trades.csv",
        "pump_trades",
        """INSERT INTO pump_trades
           (timestamp, symbol, type, entry_price, exit_price,
            pnl_pct, pnl_usd, exit_reason, duration_min,
            peak_price, capital_after)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        lambda r: (
            r.get("timestamp", ""), r.get("symbol", ""), r.get("type", ""),
            _f(r.get("entry_price")), _f(r.get("exit_price")),
            _f(r.get("pnl_pct")), _f(r.get("pnl_usd")),
            r.get("exit_reason", ""), _f(r.get("duration_min")),
            _f(r.get("peak_price")), _f(r.get("capital_after")),
        ),
    )


def _migrate_simple(filename, table, sql, row_fn):
    path = os.path.join(BASE, filename)
    if not os.path.isfile(path):
        print(f"  {filename} não encontrado, pulando.")
        return 0

    conn = _get_conn()
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                conn.execute(sql, row_fn(row))
                count += 1
            except Exception as e:
                print(f"  [AVISO] Linha ignorada em {filename}: {e}")
    conn.commit()
    conn.close()
    return count


def _f(val):
    """Converte para float, retorna None se vazio."""
    try:
        return float(val) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def _i(val):
    """Converte para int, retorna None se vazio."""
    try:
        return int(float(val)) if val not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    print("Inicializando banco de dados...")
    db.init_db()

    print("\nMigrando dados históricos dos CSVs:")

    n = migrate_log()
    print(f"  log.csv            ->{n} registros importados")

    n = migrate_alerts()
    print(f"  alerts.csv         ->{n} registros importados")

    n = migrate_paper_trades()
    print(f"  paper_trades.csv   ->{n} registros importados")

    n = migrate_agent_trades()
    print(f"  agent_trades.csv   ->{n} registros importados")

    n = migrate_pump_trades()
    print(f"  pump_trades.csv    ->{n} registros importados")

    print("\nMigração concluída. Verificando contagens no banco:")
    conn = _get_conn()
    for table in ["analysis_log", "alerts", "paper_trades", "agent_trades", "pump_trades"]:
        c = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:20s}: {c} registros")
    conn.close()
    print("\nPronto. O bot.db está pronto para uso.")
