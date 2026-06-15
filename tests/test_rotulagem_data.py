"""Testes do rotulagem_data (rotulagem cega de trades — experimento do olho).

Grava o veredito do trader sobre trades passados do momentum, SEM revelar o
resultado. Mede o olho; o cruzamento com o PnL real e a fase de revelacao.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import rotulagem_data


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    rotulagem_data.ensure_schema(c)
    return c


def _payload(**over):
    base = {
        "trade_id": 42,
        "verdict": "gostei",
        "cues": {"empurrao": True, "nivel": True, "direcao": False, "recuo": True},
        "exit_price_guess": 75000.0,
        "now_s": 1776000000,
    }
    base.update(over)
    return base


def test_save_label_grava_e_le_de_volta(conn):
    res = rotulagem_data.save_label(conn, _payload())
    assert res["ok"] is True
    got = rotulagem_data.get_label(conn, 42)
    assert got is not None
    assert got["verdict"] == "gostei"
    assert got["cue_empurrao"] == 1
    assert got["cue_direcao"] == 0
    assert got["cue_recuo"] == 1
    assert got["exit_price_guess"] == 75000.0
    assert got["labeled_at"] == 1776000000


@pytest.mark.parametrize("verdict", ["talvez", "", "GOSTEI"])
def test_save_label_rejeita_verdict_invalido(conn, verdict):
    res = rotulagem_data.save_label(conn, _payload(verdict=verdict))
    assert res["ok"] is False
    assert any("verdict" in e or "veredito" in e for e in res["errors"])
    assert rotulagem_data.get_label(conn, 42) is None


def test_labeled_trade_ids_retorna_os_ja_rotulados(conn):
    rotulagem_data.save_label(conn, _payload(trade_id=10))
    rotulagem_data.save_label(conn, _payload(trade_id=25))
    assert rotulagem_data.labeled_trade_ids(conn) == {10, 25}
    assert rotulagem_data.labeled_trade_ids(conn) == {10, 25}  # idempotente


def test_labeled_trade_ids_vazio_quando_nada_rotulado(conn):
    assert rotulagem_data.labeled_trade_ids(conn) == set()
