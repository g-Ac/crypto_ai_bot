"""Regressão: parsers do k_collector devem degradar (não crashar) quando a API
devolve um dict de erro, uma string, ou lista com itens não-dict.

Bug original (2026-06-17): no backfill de novos símbolos, /futures/data/basis (e
funding/OI) devolveu dict de erro intermitente; os parsers iteravam as CHAVES
(strings) e chamavam .get() -> AttributeError não capturado -> derrubava o símbolo
INTEIRO (perdia também klines/funding/OI/LSR daquele símbolo no run)."""
import scripts.k_collector as kc

ERROR_DICT = {"code": -1003, "msg": "Too many requests"}

DICT_PARSERS = [
    (kc.parse_basis_response, "TIAUSDT"),
    (kc.parse_funding_response, "TIAUSDT"),
    (kc.parse_open_interest_response, "TIAUSDT"),
    (kc.parse_ratio_response, "global_account"),
]


def test_parsers_resilientes_a_dict_de_erro():
    for fn, arg in DICT_PARSERS:
        assert fn(ERROR_DICT, arg) == [], f"{fn.__name__} não degradou em dict de erro"


def test_parsers_resilientes_a_string():
    for fn, arg in DICT_PARSERS:
        assert fn("erro inesperado", arg) == [], f"{fn.__name__} não degradou em string"


def test_parsers_resilientes_a_none():
    for fn, arg in DICT_PARSERS:
        assert fn(None, arg) == [], f"{fn.__name__} não degradou em None"


def test_basis_pula_itens_nao_dict_mas_mantem_validos():
    rows = ["lixo", None, {"pair": "X", "timestamp": 1700000000000,
                           "basis": "1.0", "basisRate": "0.01"}]
    out = kc.parse_basis_response(rows, "X")
    assert len(out) == 1 and out[0]["basis"] == 1.0


def test_basis_normal_intacto():
    rows = [{"pair": "TIAUSDT", "timestamp": 1700000000000, "basis": "1.5",
             "basisRate": "0.02", "indexPrice": "10.0", "futuresPrice": "10.15"}]
    out = kc.parse_basis_response(rows, "TIAUSDT")
    assert len(out) == 1 and out[0]["symbol"] == "TIAUSDT" and out[0]["basis"] == 1.5
