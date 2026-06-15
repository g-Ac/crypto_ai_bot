"""Rotulagem cega de trades — camada de dados (experimento do olho).

Grava o veredito do trader sobre trades passados do momentum SEM revelar o
resultado. As 4 pistas (empurrao, nivel, direcao, recuo) sao o checklist; o
palpite de saida vem de um clique no grafico. Mede o olho; o cruzamento com o
PnL real fica na fase de revelacao. NUNCA opina sobre o trade.

Spec: docs/superpowers/specs/2026-06-12-rotulagem-cega.md
Tabela: blind_labels (1 rotulo por trade).
"""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS blind_labels (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id         INTEGER NOT NULL UNIQUE,
  labeled_at       INTEGER NOT NULL,
  verdict          TEXT NOT NULL CHECK(verdict IN ('gostei','nao')),
  cue_empurrao     INTEGER NOT NULL DEFAULT 0,
  cue_nivel        INTEGER NOT NULL DEFAULT 0,
  cue_direcao      INTEGER NOT NULL DEFAULT 0,
  cue_recuo        INTEGER NOT NULL DEFAULT 0,
  exit_price_guess REAL,
  notes            TEXT
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def save_label(conn: sqlite3.Connection, payload: dict) -> dict:
    """Grava o rotulo de um trade. Retorna {ok, label_id} ou {ok: False, errors}."""
    ensure_schema(conn)
    if payload.get("verdict") not in ("gostei", "nao"):
        return {"ok": False, "errors": ["verdict invalido (use 'gostei' ou 'nao')"]}
    cues = payload.get("cues") or {}
    cur = conn.execute(
        "INSERT INTO blind_labels (trade_id, labeled_at, verdict, cue_empurrao,"
        " cue_nivel, cue_direcao, cue_recuo, exit_price_guess, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            int(payload["trade_id"]),
            int(payload["now_s"]),
            payload["verdict"],
            1 if cues.get("empurrao") else 0,
            1 if cues.get("nivel") else 0,
            1 if cues.get("direcao") else 0,
            1 if cues.get("recuo") else 0,
            payload.get("exit_price_guess"),
            payload.get("notes"),
        ),
    )
    return {"ok": True, "label_id": cur.lastrowid}


def get_label(conn: sqlite3.Connection, trade_id: int) -> dict | None:
    """Le o rotulo de um trade (ou None se nao rotulado)."""
    cur = conn.execute("SELECT * FROM blind_labels WHERE trade_id=?", (int(trade_id),))
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row is not None else None


def labeled_trade_ids(conn: sqlite3.Connection) -> set[int]:
    """Set dos trade_ids ja rotulados — a tela pula esses e mede progresso."""
    ensure_schema(conn)
    cur = conn.execute("SELECT trade_id FROM blind_labels")
    return {row[0] for row in cur.fetchall()}
