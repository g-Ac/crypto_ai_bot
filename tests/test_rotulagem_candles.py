"""Testes do rotulagem_candles — busca CEGA de candles na Binance REST.

So traz candles que FECHARAM antes do instante de entrada (corte cego: nada do
futuro do trade vaza pro grafico de rotulagem). A chamada real ja foi validada
a mao; aqui a rede e mockada e o foco e o corte + a formatacao.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import rotulagem_candles


def test_parse_klines_descarta_candle_que_fecha_depois_do_entry():
    entry_ms = 10_000_000
    raw = [
        [8_200_000, "10", "12", "9", "11", "5", 9_099_999],
        [9_100_000, "11", "13", "10", "12", "6", 9_999_999],
        [10_000_000, "12", "14", "11", "13", "7", 10_899_999],  # fecha depois -> fora
    ]
    out = rotulagem_candles._parse_klines(raw, entry_ms)
    assert len(out) == 2
    assert out[-1] == {"time": 9100, "open": 11.0, "high": 13.0, "low": 10.0, "close": 12.0}


def test_blind_candles_monta_params_e_corta(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                [8_200_000, "10", "12", "9", "11", "5", 9_099_999],
                [9_100_000, "11", "13", "10", "12", "6", 9_999_999],
                [10_000_000, "12", "14", "11", "13", "7", 10_899_999],
            ]

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(rotulagem_candles.requests, "get", fake_get)
    out = rotulagem_candles.blind_candles("BTCUSDT", entry_time_s=10_000, interval="15m", n=50)

    assert captured["params"]["symbol"] == "BTCUSDT"
    assert captured["params"]["interval"] == "15m"
    assert captured["params"]["endTime"] == 10_000 * 1000
    assert captured["params"]["limit"] == 50
    assert len(out) == 2  # candle que fecha depois do entry foi cortado
