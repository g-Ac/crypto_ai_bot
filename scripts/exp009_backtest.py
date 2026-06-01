"""
EXP-009 — K Crowded Long OI Chase | Backtest Honesto (GREEN phase)

Tese: Após pump + OI subindo + funding positivo + crowd long em perp,
existe pressão de reversão de curto prazo (6h–48h) explorável via SHORT,
com edge líquido positivo após custos.

Critérios travados em:
  /home/pi/obsidian-vault/context/decisoes/2026-05-06-exp009-abertura-criterios-pre-commit.md

Hash do documento gravado abaixo. Mudou? Abrir EXP-009b, não editar este módulo.

Sem dado fabricado. Sem placeholder. Sem grid search.
Origem única: bot.db real do Pi.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ============================================================
# Trava do documento de critérios
# ============================================================

PINNED_CRITERIA_HASH = (
    "219bf08ed096abb56cf76402869e9e0194c90fcc242e9b7b358ae0ac8b5d604a"
)

# ============================================================
# Constantes (espelho do documento)
# ============================================================

DB_PATH = Path("/home/pi/crypto_ai_bot/runtime/baseline/bot.db")

UNIVERSE = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "HYPEUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "TRXUSDT",
    "SUIUSDT", "1000PEPEUSDT",
)

ROUND_TRIP_COST = 0.0012
LIQ_FACTOR = 0.90
LIQ_PNL_RETURN = -0.90

LEVERAGES_REPORT = (1, 2, 3, 5)
LEVERAGES_STRESS = (10,)
LEVERAGES_BANNED = (20, 50)

HORIZONS_HOURS = (6, 12, 24, 48)
ENTRY_POLICIES = ("ingenuous", "defensible", "conservative")
ENTRY_OFFSETS_S = {"ingenuous": 0, "defensible": 3600, "conservative": 7200}

P1_NET_EDGE_MIN = 2 * ROUND_TRIP_COST
P1_NW_T_MIN = 2.0
P1_LIQ_MAX = 0.05
P3_MIN_POSITIVE_SYMBOLS = 5
P3_MAX_PNL_CONCENTRATION = 0.50
P4_DEFENSIBLE_VS_INGENUOUS_MIN = 0.80
P5_MIN_REGIMES = 2

MIN_TRADES_FOR_VERDICT = 200

SIGNAL_MODES = ("A0", "A1", "A2", "A3")

# Modo A3 herda os limiares de A0 com teto adicional de funding.
SIGNAL_SPECS = {
    "A0": dict(
        ret24_min=0.02, oi24_min=0.03, funding_ann_min=0.0,
        top_long_min=0.52, global_long_min=0.50, funding_ann_max=None,
    ),
    "A1": dict(
        ret24_min=0.03, oi24_min=0.05, funding_ann_min=10.0,
        top_long_min=0.55, global_long_min=0.52, funding_ann_max=None,
    ),
    "A2": dict(
        ret24_min=0.05, oi24_min=0.10, funding_ann_min=0.0,
        top_long_min=0.0, global_long_min=0.0, funding_ann_max=None,
    ),
    "A3": dict(
        ret24_min=0.02, oi24_min=0.03, funding_ann_min=0.0,
        top_long_min=0.52, global_long_min=0.50, funding_ann_max=10.0,
    ),
}

REGIME_THRESHOLD = 0.02


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class Dataset:
    source_path: Path
    symbols: tuple
    prices: dict          # prices[sym][ts] = {open, close, high, low, volume}
    ratios: dict          # ratios[sym][ts][source] = {long_account, short_account}
    open_interest: dict   # open_interest[sym][ts] = {sum_oi, sum_oi_value}
    funding: dict         # funding[sym] = sorted list of {funding_time, funding_rate}
    btc_returns: dict     # btc_returns[(ts, h)] = float (cached)


@dataclass
class Fold:
    ts_min: int
    ts_max: int
    n: int
    mean_net: float


@dataclass
class Cell:
    """Métricas agregadas para uma combinação (mode, horizon, leverage)."""
    mode: str = "A0"
    horizon: int = 24
    leverage: int = 1
    n: int = 0
    win_rate: float = 0.0
    mean_net: float = 0.0
    median_net: float = 0.0
    p05: float = 0.0
    p95: float = 0.0
    nw_t: float = 0.0
    liq_rate: float = 0.0
    fold_means: list = field(default_factory=list)
    folds: list = field(default_factory=list)
    per_symbol: dict = field(default_factory=dict)
    positive_symbols: int = 0
    max_symbol_pnl_share: float = 0.0
    regimes_passing: list = field(default_factory=list)
    defensible_ratio: float = 1.0

    # Compatibilidade com testes que passam `net_edge` e `liq`
    @property
    def net_edge(self) -> float:
        return self.mean_net

    @property
    def liq(self) -> float:
        return self.liq_rate


@dataclass
class Report:
    cells: dict = field(default_factory=dict)        # (mode, h, L) -> Cell
    stress_cells: dict = field(default_factory=dict)
    report_section_leverages: tuple = LEVERAGES_REPORT
    stress_section_leverages: tuple = LEVERAGES_STRESS
    universe: tuple = UNIVERSE

    def folds_for(self, key):
        return self.cells[key].folds

    def per_symbol(self, key):
        per = self.cells[key].per_symbol
        # Garante presença de todos os 14 símbolos (alguns podem ter N=0)
        out = {sym: per.get(sym, {"n": 0, "mean_net": 0.0}) for sym in UNIVERSE}
        return out


# ============================================================
# Loader
# ============================================================

def load_dataset(**kwargs) -> Dataset:
    """Carrega o dataset real do Pi. Qualquer kwarg é proibido."""
    if kwargs:
        raise RuntimeError(
            f"load_dataset não aceita kwargs (recebi: {sorted(kwargs)}). "
            "Dado fabricado/sintético é proibido neste EXP."
        )
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB real ausente: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    prices: dict = {}
    ratios: dict = defaultdict(lambda: defaultdict(dict))
    open_interest: dict = {}
    funding: dict = {}

    for sym in UNIVERSE:
        prices[sym] = {
            r["bucket_ts"]: {
                "open": r["open_price"], "close": r["close_price"],
                "high": r["high_price"], "low": r["low_price"],
                "volume": r["volume"],
            }
            for r in cur.execute(
                "SELECT * FROM k_prices WHERE symbol=? ORDER BY bucket_ts",
                (sym,),
            )
        }
        for r in cur.execute(
            "SELECT * FROM k_ratios WHERE symbol=? ORDER BY bucket_ts",
            (sym,),
        ):
            ratios[sym][r["bucket_ts"]][r["source"]] = {
                "long_account": r["long_account"],
                "short_account": r["short_account"],
                "long_short_ratio": r["long_short_ratio"],
            }
        open_interest[sym] = {
            r["bucket_ts"]: {
                "sum_oi": r["sum_open_interest"],
                "sum_oi_value": r["sum_open_interest_value"],
            }
            for r in cur.execute(
                "SELECT * FROM k_open_interest WHERE symbol=? "
                "ORDER BY bucket_ts",
                (sym,),
            )
        }
        funding[sym] = [
            {"funding_time": r["funding_time"],
             "funding_rate": r["funding_rate"]}
            for r in cur.execute(
                "SELECT * FROM k_funding_rates WHERE symbol=? "
                "ORDER BY funding_time",
                (sym,),
            )
        ]

    conn.close()

    return Dataset(
        source_path=DB_PATH,
        symbols=UNIVERSE,
        prices=prices,
        ratios={s: dict(v) for s, v in ratios.items()},
        open_interest=open_interest,
        funding=funding,
        btc_returns={},
    )


def truncate_after(ds: Dataset, ts0: int) -> Dataset:
    """Retorna um Dataset com todas as observações > ts0 removidas."""
    new_prices = {s: {ts: v for ts, v in d.items() if ts <= ts0}
                  for s, d in ds.prices.items()}
    new_ratios = {
        s: {ts: v for ts, v in d.items() if ts <= ts0}
        for s, d in ds.ratios.items()
    }
    new_oi = {s: {ts: v for ts, v in d.items() if ts <= ts0}
              for s, d in ds.open_interest.items()}
    new_funding = {
        s: [r for r in lst if r["funding_time"] <= ts0]
        for s, lst in ds.funding.items()
    }
    return Dataset(
        source_path=ds.source_path,
        symbols=ds.symbols,
        prices=new_prices,
        ratios=new_ratios,
        open_interest=new_oi,
        funding=new_funding,
        btc_returns={},
    )


def midpoint_timestamp(ds: Dataset) -> int:
    """Timestamp medianos dos preços de BTC (ou do primeiro símbolo disponível)."""
    base = ds.prices.get("BTCUSDT") or next(iter(ds.prices.values()))
    ts = sorted(base.keys())
    if not ts:
        return 0
    return ts[len(ts) // 2]


# ============================================================
# Features sem lookahead
# ============================================================

def _last_funding_at_or_before(funding_list, ts):
    """Última taxa de funding com funding_time <= ts. Linear porque listas pequenas."""
    last = None
    for r in funding_list:
        if r["funding_time"] <= ts:
            last = r
        else:
            break
    return last


def build_features(ds: Dataset) -> dict:
    """Retorna dict feats[(symbol, ts)] = {ret24, oi24, funding_ann, top_long, global_long}.

    Cada feature usa apenas dados <= ts. Especificamente:
      - ret24[t] = close[t] / close[t-24h] - 1
      - oi24[t] = oi[t] / oi[t-24h] - 1
      - funding_ann[t] = último funding rate <= t, anualizado (rate * 3 * 365 * 100)
      - top_long[t] = ratios[t][top_position].long_account
      - global_long[t] = ratios[t][global_account].long_account
    """
    feats: dict = {}
    for sym in ds.symbols:
        price_map = ds.prices.get(sym, {})
        oi_map = ds.open_interest.get(sym, {})
        ratio_map = ds.ratios.get(sym, {})
        funding_list = ds.funding.get(sym, [])
        for ts in sorted(price_map.keys()):
            ts_prev = ts - 86400
            if ts_prev not in price_map or ts_prev not in oi_map:
                continue
            if ts not in oi_map or ts not in ratio_map:
                continue
            top = ratio_map[ts].get("top_position")
            glb = ratio_map[ts].get("global_account")
            if not top or not glb:
                continue
            if top.get("long_account") is None or glb.get("long_account") is None:
                continue
            p_now = price_map[ts]["close"]
            p_prev = price_map[ts_prev]["close"]
            if not p_prev:
                continue
            oi_now = oi_map[ts]["sum_oi_value"] or oi_map[ts]["sum_oi"]
            oi_prev = oi_map[ts_prev]["sum_oi_value"] or oi_map[ts_prev]["sum_oi"]
            if not oi_prev or oi_prev <= 0:
                continue
            fd = _last_funding_at_or_before(funding_list, ts)
            if not fd:
                continue
            feats[(sym, ts)] = {
                "ret24": p_now / p_prev - 1.0,
                "oi24": oi_now / oi_prev - 1.0,
                "funding_ann": float(fd["funding_rate"]) * 3 * 365 * 100,
                "top_long": float(top["long_account"]),
                "global_long": float(glb["long_account"]),
                "close": p_now,
            }
    return feats


def compare_features_up_to(feats_a: dict, feats_b: dict, ts0: int) -> int:
    """Conta quantas chaves (sym, ts) com ts <= ts0 divergem entre os dois dicts."""
    diff = 0
    keys_a = {k for k in feats_a if k[1] <= ts0}
    keys_b = {k for k in feats_b if k[1] <= ts0}
    if keys_a != keys_b:
        diff += len(keys_a.symmetric_difference(keys_b))
    for k in keys_a & keys_b:
        a = feats_a[k]
        b = feats_b[k]
        for field_name in ("ret24", "oi24", "funding_ann",
                           "top_long", "global_long", "close"):
            va, vb = a[field_name], b[field_name]
            if va is None and vb is None:
                continue
            if va is None or vb is None or abs(va - vb) > 1e-12:
                diff += 1
                break
    return diff


# ============================================================
# Specs / entries / costs / liquidação
# ============================================================

def get_signal_spec(mode: str):
    return SIGNAL_SPECS.get(mode)


def entry_offset_seconds(policy: str) -> int:
    return ENTRY_OFFSETS_S[policy]


def signal_fires(spec: dict, feat: dict) -> bool:
    if feat["ret24"] < spec["ret24_min"]:
        return False
    if feat["oi24"] < spec["oi24_min"]:
        return False
    if feat["funding_ann"] < spec["funding_ann_min"]:
        return False
    if spec.get("funding_ann_max") is not None \
            and feat["funding_ann"] > spec["funding_ann_max"]:
        return False
    if feat["top_long"] < spec["top_long_min"]:
        return False
    if feat["global_long"] < spec["global_long_min"]:
        return False
    return True


def apply_costs(*, gross_return: float, side: str,
                entry_ts: int, exit_ts: int, symbol: str,
                funding_events: Iterable[dict]) -> float:
    """Aplica custo round-trip e funding ao retorno bruto.

    SHORT: recebe funding positivo (paga negativo).
    LONG: paga funding positivo.
    Funding incluído quando entry_ts < funding_time <= exit_ts.
    """
    if side not in ("SHORT", "LONG"):
        raise ValueError(f"side inválido: {side}")
    funding_sum = 0.0
    for ev in funding_events:
        ft = ev["funding_time"]
        if entry_ts < ft <= exit_ts:
            rate = float(ev["funding_rate"])
            funding_sum += rate if side == "SHORT" else -rate
    return gross_return - ROUND_TRIP_COST + funding_sum


def liquidation_threshold(*, leverage: int) -> float:
    return LIQ_FACTOR / leverage


def compute_levered_pnl(*, net_unlev: float, adverse: float,
                        leverage: int) -> float:
    if adverse >= liquidation_threshold(leverage=leverage):
        return LIQ_PNL_RETURN
    return net_unlev * leverage


# ============================================================
# Estatística
# ============================================================

def compute_nw_t(*, values, horizon_hours: int) -> float:
    """t-stat com correção de sobreposição (n_eff = N / horizonte)."""
    vals = list(values)
    n = len(vals)
    if n == 0:
        return 0.0
    mean = sum(vals) / n
    if n < 2:
        return 0.0
    sd = statistics.pstdev(vals)
    if sd == 0:
        return 0.0
    n_eff = max(1.0, n / horizon_hours)
    return mean / (sd / math.sqrt(n_eff))


def classify_btc_regime(*, ret: float, horizon_hours: int) -> str:
    if ret > REGIME_THRESHOLD:
        return "up"
    if ret < -REGIME_THRESHOLD:
        return "down"
    return "sideways"


# ============================================================
# Cell helpers (para testes e síntese)
# ============================================================

def make_cell_for_test(*, net_edge: float = 0.0, nw_t: float = 0.0,
                       liq: float = 0.0, n: int = 0,
                       fold_means=None, positive_symbols: int = 14,
                       max_symbol_pnl_share: float = 0.10,
                       regimes_passing=None,
                       defensible_ratio: float = 1.0,
                       mode: str = "A0", horizon: int = 24,
                       leverage: int = 1) -> Cell:
    return Cell(
        mode=mode, horizon=horizon, leverage=leverage,
        n=n,
        mean_net=net_edge,
        nw_t=nw_t,
        liq_rate=liq,
        fold_means=list(fold_means) if fold_means else [net_edge] * 3,
        positive_symbols=positive_symbols,
        max_symbol_pnl_share=max_symbol_pnl_share,
        regimes_passing=list(regimes_passing) if regimes_passing
        else ["up", "sideways", "down"],
        defensible_ratio=defensible_ratio,
    )


def passes_p1(cell: Cell) -> bool:
    return (cell.mean_net >= P1_NET_EDGE_MIN
            and cell.nw_t >= P1_NW_T_MIN
            and cell.liq_rate <= P1_LIQ_MAX
            and cell.n >= MIN_TRADES_FOR_VERDICT)


def passes_p2(cell: Cell) -> bool:
    if not cell.fold_means:
        return False
    return all(f >= 0 for f in cell.fold_means)


def passes_p3(cell: Cell) -> bool:
    return (cell.positive_symbols >= P3_MIN_POSITIVE_SYMBOLS
            and cell.max_symbol_pnl_share <= P3_MAX_PNL_CONCENTRATION)


def defensible_vs_ingenuous_ratio(*, ingenuous: float,
                                  defensible: float) -> float:
    if ingenuous == 0:
        return 0.0
    return defensible / ingenuous


def passes_p4(ratio: float) -> bool:
    return ratio >= P4_DEFENSIBLE_VS_INGENUOUS_MIN


def passes_p5(cell: Cell) -> bool:
    return len(set(cell.regimes_passing)) >= P5_MIN_REGIMES


def triggers_f2(cell: Cell) -> bool:
    if not cell.fold_means or len(cell.fold_means) < 3:
        return False
    others = cell.fold_means[:-1]
    last = cell.fold_means[-1]
    return last < 0 and all(f >= 0 for f in others)


def triggers_f3(cell: Cell) -> bool:
    return cell.positive_symbols <= 2


def triggers_f4(report: Report) -> bool:
    """F4: 5x passa P1 mas 1x não atinge net_edge mínimo."""
    for (mode, h, L), cell in report.cells.items():
        if L != 5 or not passes_p1(cell):
            continue
        cell_1x = report.cells.get((mode, h, 1))
        if cell_1x and cell_1x.mean_net < P1_NET_EDGE_MIN:
            return True
    return False


def triggers_f5(*, defensible_ratio: float) -> bool:
    return defensible_ratio < P4_DEFENSIBLE_VS_INGENUOUS_MIN


def cell_verdict(cell: Cell) -> str:
    if cell.n < MIN_TRADES_FOR_VERDICT:
        return "DADO INSUFICIENTE"
    if not passes_p1(cell):
        return "NO-GO"
    if not (passes_p2(cell) and passes_p3(cell) and passes_p5(cell)):
        return "AMBÍGUO"
    return "GO experimental"


def final_verdict(report: Report) -> str:
    """NO-GO se nenhuma cell passa P1; senão delega para a melhor cell."""
    best: Cell | None = None
    for cell in report.cells.values():
        if not passes_p1(cell):
            continue
        if best is None or cell.mean_net > best.mean_net:
            best = cell
    if best is None:
        return "NO-GO"
    return cell_verdict(best)


def synthesize_report_for_test(*, any_p1_pass=None, mode: str = "A0",
                               horizon: int = 24,
                               edge_by_lev: dict | None = None) -> Report:
    """Constrói um Report mínimo para testes de F1/F4."""
    cells: dict = {}
    if edge_by_lev is not None:
        for L, edge in edge_by_lev.items():
            cells[(mode, horizon, L)] = make_cell_for_test(
                net_edge=edge,
                nw_t=P1_NW_T_MIN + 1.0 if edge >= P1_NET_EDGE_MIN else 1.0,
                liq=0.01,
                n=MIN_TRADES_FOR_VERDICT + 50,
                mode=mode, horizon=horizon, leverage=L,
            )
    elif any_p1_pass is False:
        for L in LEVERAGES_REPORT:
            cells[(mode, horizon, L)] = make_cell_for_test(
                net_edge=0.0001, nw_t=0.5, liq=0.01,
                n=MIN_TRADES_FOR_VERDICT + 50,
                mode=mode, horizon=horizon, leverage=L,
            )
    return Report(
        cells=cells,
        stress_cells={},
        report_section_leverages=LEVERAGES_REPORT,
        stress_section_leverages=LEVERAGES_STRESS,
        universe=UNIVERSE,
    )


# ============================================================
# Backtest engine
# ============================================================

def _ts_set(price_map):
    return set(price_map.keys())


def _btc_return(ds: Dataset, t_entry: int, t_exit: int) -> float | None:
    btc = ds.prices.get("BTCUSDT", {})
    if t_entry not in btc or t_exit not in btc:
        return None
    p0 = btc[t_entry].get("open")
    p1 = btc[t_exit].get("close")
    if not p0 or not p1:
        return None
    return p1 / p0 - 1.0


def _gen_short_trades(ds: Dataset, feats: dict, mode: str,
                      horizon_hours: int, policy: str):
    """Gera todos os trades SHORT para (mode, horizon, policy).

    Retorna lista de dicts: sym, signal_ts, entry_ts, exit_ts, gross,
    adverse, funding_window_events.
    """
    spec = SIGNAL_SPECS[mode]
    offset = ENTRY_OFFSETS_S[policy]
    horizon_s = horizon_hours * 3600
    trades = []
    for sym in ds.symbols:
        price_map = ds.prices.get(sym, {})
        if not price_map:
            continue
        ts_set = _ts_set(price_map)
        sorted_ts = sorted(price_map.keys())
        funding_list = ds.funding.get(sym, [])
        for t in sorted_ts:
            feat = feats.get((sym, t))
            if feat is None or not signal_fires(spec, feat):
                continue
            entry_ts = t + offset
            exit_ts = entry_ts + horizon_s
            # entry e exit precisam estar nos buckets
            if entry_ts not in ts_set or exit_ts not in ts_set:
                continue
            entry_bar = price_map[entry_ts]
            exit_bar = price_map[exit_ts]
            entry_px = entry_bar["open"] if offset > 0 else entry_bar["close"]
            exit_px = exit_bar["close"]
            if not entry_px or not exit_px:
                continue
            # MFE/MAE no caminho — adverse = high máximo / entry - 1 para short
            high = entry_bar["high"]
            cur = entry_ts + 3600
            while cur <= exit_ts:
                bar = price_map.get(cur)
                if bar:
                    if bar["high"] > high:
                        high = bar["high"]
                cur += 3600
            adverse = max(0.0, high / entry_px - 1.0)
            gross = (entry_px - exit_px) / entry_px
            trades.append({
                "sym": sym,
                "signal_ts": t,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross": gross,
                "adverse": adverse,
                "funding": funding_list,
            })
    return trades


def _build_cell(trades: list, mode: str, horizon_hours: int,
                leverage: int, ds: Dataset,
                ingenuous_mean: float | None = None) -> Cell:
    if not trades:
        return Cell(mode=mode, horizon=horizon_hours, leverage=leverage, n=0)

    # Aplica custo + funding e calcula PnL alavancado por trade
    pnls = []
    nets_unlev = []
    by_symbol_pnls: dict = defaultdict(list)
    by_regime_pnls: dict = defaultdict(list)
    by_regime_count: dict = defaultdict(int)
    liq_count = 0

    for tr in trades:
        net = apply_costs(
            gross_return=tr["gross"], side="SHORT",
            entry_ts=tr["entry_ts"], exit_ts=tr["exit_ts"],
            symbol=tr["sym"], funding_events=tr["funding"],
        )
        pnl = compute_levered_pnl(
            net_unlev=net, adverse=tr["adverse"], leverage=leverage,
        )
        if pnl == LIQ_PNL_RETURN:
            liq_count += 1
        pnls.append(pnl)
        nets_unlev.append(net)
        by_symbol_pnls[tr["sym"]].append(pnl)
        btc_ret = _btc_return(ds, tr["entry_ts"], tr["exit_ts"])
        if btc_ret is None:
            continue
        regime = classify_btc_regime(ret=btc_ret, horizon_hours=horizon_hours)
        by_regime_pnls[regime].append(pnl)
        by_regime_count[regime] += 1

    n = len(pnls)
    mean_net = sum(pnls) / n
    sorted_pnls = sorted(pnls)
    median_net = statistics.median(pnls)
    p05 = sorted_pnls[max(0, int(0.05 * (n - 1)))]
    p95 = sorted_pnls[min(n - 1, int(0.95 * (n - 1)))]
    nw_t = compute_nw_t(values=pnls, horizon_hours=horizon_hours)
    liq_rate = liq_count / n
    win_rate = sum(1 for p in pnls if p > 0) / n

    # Folds temporais
    sorted_trades = sorted(zip(trades, pnls), key=lambda x: x[0]["entry_ts"])
    chunk = max(1, len(sorted_trades) // 3)
    folds: list = []
    fold_means: list = []
    for i in range(3):
        start = i * chunk
        end = (i + 1) * chunk if i < 2 else len(sorted_trades)
        seg = sorted_trades[start:end]
        if not seg:
            folds.append(Fold(0, 0, 0, 0.0))
            fold_means.append(0.0)
            continue
        seg_pnls = [p for _, p in seg]
        seg_ts = [tr["entry_ts"] for tr, _ in seg]
        f_mean = sum(seg_pnls) / len(seg_pnls)
        folds.append(Fold(min(seg_ts), max(seg_ts), len(seg), f_mean))
        fold_means.append(f_mean)

    # Per-symbol
    per_symbol_dict = {}
    total_abs_pnl = sum(abs(p) for p in pnls) or 1.0
    positive_symbols = 0
    max_share = 0.0
    for sym in UNIVERSE:
        sym_pnls = by_symbol_pnls.get(sym, [])
        if not sym_pnls:
            per_symbol_dict[sym] = {"n": 0, "mean_net": 0.0,
                                    "share_abs_pnl": 0.0}
            continue
        sm = sum(sym_pnls) / len(sym_pnls)
        share = sum(abs(p) for p in sym_pnls) / total_abs_pnl
        per_symbol_dict[sym] = {
            "n": len(sym_pnls), "mean_net": sm, "share_abs_pnl": share,
        }
        if sm > 0:
            positive_symbols += 1
        if share > max_share:
            max_share = share

    # Regimes onde net edge >= 2x custo
    regimes_passing = []
    for regime, regime_pnls in by_regime_pnls.items():
        if not regime_pnls:
            continue
        rm = sum(regime_pnls) / len(regime_pnls)
        if rm >= P1_NET_EDGE_MIN:
            regimes_passing.append(regime)

    # Defensible vs ingenuous (preenchido pelo caller)
    defensible_ratio = 1.0
    if ingenuous_mean is not None and ingenuous_mean != 0:
        defensible_ratio = mean_net / ingenuous_mean

    return Cell(
        mode=mode, horizon=horizon_hours, leverage=leverage,
        n=n, win_rate=win_rate,
        mean_net=mean_net, median_net=median_net,
        p05=p05, p95=p95, nw_t=nw_t, liq_rate=liq_rate,
        fold_means=fold_means, folds=folds,
        per_symbol=per_symbol_dict,
        positive_symbols=positive_symbols,
        max_symbol_pnl_share=max_share,
        regimes_passing=regimes_passing,
        defensible_ratio=defensible_ratio,
    )


def run_full_backtest() -> Report:
    ds = load_dataset()
    feats = build_features(ds)
    cells: dict = {}
    stress_cells: dict = {}

    for mode in SIGNAL_MODES:
        for h in HORIZONS_HOURS:
            # Trades para defensible (relatório principal) e ingenuous (P4 ratio)
            trades_def = _gen_short_trades(ds, feats, mode, h, "defensible")
            trades_ing = _gen_short_trades(ds, feats, mode, h, "ingenuous")
            ing_cell_1x = _build_cell(trades_ing, mode, h, 1, ds)
            for L in LEVERAGES_REPORT:
                cell = _build_cell(
                    trades_def, mode, h, L, ds,
                    ingenuous_mean=ing_cell_1x.mean_net or None,
                )
                cells[(mode, h, L)] = cell
            for L in LEVERAGES_STRESS:
                cell = _build_cell(
                    trades_def, mode, h, L, ds,
                    ingenuous_mean=ing_cell_1x.mean_net or None,
                )
                stress_cells[(mode, h, L)] = cell

    return Report(
        cells=cells,
        stress_cells=stress_cells,
        report_section_leverages=LEVERAGES_REPORT,
        stress_section_leverages=LEVERAGES_STRESS,
        universe=UNIVERSE,
    )


# ============================================================
# Relatório textual
# ============================================================

def _fts(ts: int) -> str:
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def render_report(report: Report) -> str:
    lines = []
    lines.append("EXP-009 — K Crowded Long OI Chase | resultado")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Sessão: backtest contra dado real do Pi.")
    lines.append("Critérios travados em "
                 "2026-05-06-exp009-abertura-criterios-pre-commit.md")
    lines.append(f"Hash pinned: {PINNED_CRITERIA_HASH}")
    lines.append("")
    lines.append("RELATÓRIO PRINCIPAL (1x, 2x, 3x, 5x)")
    lines.append("-" * 60)
    header = (
        f"{'mode':4s} {'h':>3s} {'L':>3s} {'N':>5s} {'mean%':>8s} "
        f"{'med%':>8s} {'p05%':>8s} {'NW_t':>7s} {'liq%':>6s} "
        f"{'win%':>6s} {'def/ing':>8s}"
    )
    lines.append(header)
    for mode in SIGNAL_MODES:
        for h in HORIZONS_HOURS:
            for L in LEVERAGES_REPORT:
                c = report.cells[(mode, h, L)]
                lines.append(
                    f"{mode:4s} {h:>3d} {L:>3d} {c.n:>5d} "
                    f"{c.mean_net*100:>8.2f} {c.median_net*100:>8.2f} "
                    f"{c.p05*100:>8.2f} {c.nw_t:>7.2f} "
                    f"{c.liq_rate*100:>6.1f} {c.win_rate*100:>6.1f} "
                    f"{c.defensible_ratio:>8.2f}"
                )
    lines.append("")
    lines.append("STRESS / DO-NOT-USE (10x — apenas auditoria de fragilidade)")
    lines.append("-" * 60)
    for mode in SIGNAL_MODES:
        for h in HORIZONS_HOURS:
            for L in LEVERAGES_STRESS:
                c = report.stress_cells[(mode, h, L)]
                lines.append(
                    f"{mode:4s} {h:>3d} {L:>3d} {c.n:>5d} "
                    f"{c.mean_net*100:>8.2f} liq={c.liq_rate*100:>5.1f}%"
                )
    lines.append("")
    lines.append("FOLDS por (mode, h, L=3) — divisão temporal igual em 3")
    lines.append("-" * 60)
    for mode in SIGNAL_MODES:
        for h in HORIZONS_HOURS:
            c = report.cells[(mode, h, 3)]
            fm = c.fold_means
            if not fm:
                continue
            f1, f2, f3 = (fm + [0.0, 0.0, 0.0])[:3]
            lines.append(
                f"{mode:4s} h={h:>2d} f1={f1*100:>6.2f}% "
                f"f2={f2*100:>6.2f}% f3={f3*100:>6.2f}% "
                f"drift(f1-f3)={(f1-f3)*100:>6.2f}pp"
            )
    lines.append("")
    lines.append("VERDICT FINAL")
    lines.append("-" * 60)
    lines.append(final_verdict(report))
    return "\n".join(lines)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    rep = run_full_backtest()
    print(render_report(rep))
