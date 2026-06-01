# test_h1.py — pytest opcional; roda standalone com `python test_h1.py`
import pandas as pd
from h1_funding_conditioning import funding_feature, SLOT_SEC, CONFIG

def _mk_funding():
    # fundings liquidados às 00:00, 08:00, 16:00 UTC — tudo em epoch SEGUNDOS
    base = 1_700_000_000            # epoch segundos qualquer
    base = (base // SLOT_SEC) * SLOT_SEC  # alinha à fronteira de 8h (00/08/16 UTC)
    times = [base + i * SLOT_SEC for i in range(CONFIG["z_periods"] + 5)]
    rates = [0.0001 * (i + 1) for i in range(len(times))]  # crescentes, distinguíveis
    return pd.DataFrame({"funding_time": times, "funding_rate": rates}), base

def test_0801_usa_slot_anterior():
    fdf, base = _mk_funding()
    last_boundary = fdf["funding_time"].iloc[-1]  # uma fronteira de 8h
    signal_0801 = last_boundary + 60              # +60s => "08:01" em relação ao slot
    z, raw = funding_feature(signal_0801, fdf)
    # slot_open = last_boundary; deve usar o funding ANTERIOR a last_boundary
    raw_esperado = fdf[fdf["funding_time"] < last_boundary]["funding_rate"].iloc[-1]
    assert raw == raw_esperado, f"08:01 deveria usar funding do slot anterior, usou {raw}"
    print("OK: sinal +1min após fronteira usa o funding do slot anterior (00:00, não 08:00)")

def test_fronteira_exata_usa_anterior():
    fdf, base = _mk_funding()
    boundary = fdf["funding_time"].iloc[-1]
    z, raw = funding_feature(boundary, fdf)  # 08:00:00 exato
    raw_esperado = fdf[fdf["funding_time"] < boundary]["funding_rate"].iloc[-1]
    assert raw == raw_esperado
    print("OK: fronteira exata exclui o funding que liquida nela")

if __name__ == "__main__":
    test_0801_usa_slot_anterior()
    test_fronteira_exata_usa_anterior()
    print("todos os testes de anti-lookahead passaram")
