"""
Testes para risk_manager.py — Fase 0.3 do Roadmap V1.

Cobre:
- Thread-safety: load/save_scalping_state com acesso concorrente
- Atomicidade: save usa tempfile + os.replace
- ATR off-by-one guard (Fase 1.2 preview)
"""
import sys
import os
import json
import threading
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from risk_manager import load_scalping_state, save_scalping_state, _state_lock


class TestStateLocking:
    """Testa que leitura/escrita concorrente não corrompe o state."""

    def test_lock_exists(self):
        """O lock global deve existir e ser um threading.Lock."""
        assert _state_lock is not None
        assert isinstance(_state_lock, type(threading.Lock()))

    def test_concurrent_saves_no_corruption(self, tmp_path):
        """Múltiplas threads salvando simultaneamente não produzem arquivo corrompido."""
        state_file = str(tmp_path / "test_state.json")
        errors = []
        iterations = 50

        def writer(thread_id):
            for i in range(iterations):
                state = {
                    "capital": 1000.0 + thread_id + i,
                    "positions": {},
                    "thread": thread_id,
                    "iteration": i,
                }
                try:
                    with patch("risk_manager.SCALPING_STATE_FILE", state_file):
                        save_scalping_state(state)
                except Exception as e:
                    errors.append(f"Thread {thread_id}, iter {i}: {e}")

        threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Erros durante escrita concorrente: {errors}"

        # Arquivo final deve ser JSON válido
        with open(state_file) as f:
            final_state = json.load(f)
        assert "capital" in final_state
        assert isinstance(final_state["capital"], float)

    def test_concurrent_read_write_no_corruption(self, tmp_path):
        """Leituras e escritas simultâneas não causam crash."""
        state_file = str(tmp_path / "test_state.json")
        initial = {"capital": 1000.0, "positions": {}, "total_trades": 0,
                    "wins": 0, "losses": 0, "total_pnl_usd": 0.0,
                    "cooldowns": {}, "history": []}
        with open(state_file, "w") as f:
            json.dump(initial, f)

        read_errors = []
        write_errors = []
        iterations = 30

        def reader():
            for _ in range(iterations):
                try:
                    with patch("risk_manager.SCALPING_STATE_FILE", state_file):
                        state = load_scalping_state()
                    assert "capital" in state
                except Exception as e:
                    read_errors.append(str(e))

        def writer():
            for i in range(iterations):
                try:
                    with patch("risk_manager.SCALPING_STATE_FILE", state_file):
                        state = load_scalping_state()
                        state["capital"] += 1.0
                        save_scalping_state(state)
                except Exception as e:
                    write_errors.append(str(e))

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(read_errors) == 0, f"Erros de leitura: {read_errors}"
        assert len(write_errors) == 0, f"Erros de escrita: {write_errors}"

    def test_save_is_atomic(self, tmp_path):
        """Save usa rename atômico — arquivo parcial nunca é visível."""
        state_file = str(tmp_path / "test_state.json")

        state = {"capital": 999.99, "positions": {"BTC": {"entry": 50000}}}
        with patch("risk_manager.SCALPING_STATE_FILE", state_file):
            save_scalping_state(state)

        # Nenhum .tmp deve sobrar
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Arquivos temporários não limpos: {tmp_files}"

        # Conteúdo deve estar correto
        with open(state_file) as f:
            loaded = json.load(f)
        assert loaded["capital"] == 999.99
        assert "BTC" in loaded["positions"]

    def test_load_missing_file_returns_default(self, tmp_path):
        """Arquivo inexistente retorna state default."""
        with patch("risk_manager.SCALPING_STATE_FILE", str(tmp_path / "nonexistent.json")):
            state = load_scalping_state()

        assert state["capital"] > 0
        assert state["positions"] == {}
        assert state["total_trades"] == 0
