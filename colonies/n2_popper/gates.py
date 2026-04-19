"""
N2 Gauntlet gates — adaptado do motor_feynman_v3 para o formato de trades
do core.creatures.creature.TradeLog.

Chamadas a partir de run.py após cada criatura completar um episódio:
  report = run_gauntlet(trades, regimes_seen, days_total)
  report.passed is the boolean flag stored in metrics['gauntlet_passed']

Preserva as 5 gates originais do motor_feynman_v3 com ajuste de unidade
(trade.net_pnl_decimal → pnl_bps via × 10000).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable
import numpy as np

from .config import (
    FEE_BPS_ROUNDTRIP, MIN_TRADES, MIN_NET_BPS_DAY, MIN_OOS_RATIO,
    MIN_CALMAR_LIKE, MIN_DISTINCT_REGIMES, OOS_SPLIT_FRAC,
)


@dataclass
class GateReport:
    passed: bool
    failure_reason: str | None
    n_trades: int
    gross_bps: float
    fees_bps: float
    net_bps_total: float
    net_bps_day: float
    sharpe_train: float
    sharpe_oos: float
    oos_ratio: float
    max_drawdown_bps: float
    final_equity_bps: float
    calmar_like: float
    regimes_seen: list
    evaluation_days: float


def _trades_to_bps(trades: Iterable) -> np.ndarray:
    """Convert core TradeLog list to np array of pnl in bps (10000× decimal).
    Works with either TradeLog dataclasses (has .net_pnl_decimal) or dicts."""
    out = []
    for t in trades:
        if hasattr(t, "net_pnl_decimal"):
            out.append(t.net_pnl_decimal * 10000.0)
        elif isinstance(t, dict):
            if "pnl_bps" in t:
                out.append(float(t["pnl_bps"]))
            elif "net_pnl_decimal" in t:
                out.append(float(t["net_pnl_decimal"]) * 10000.0)
            else:
                out.append(0.0)
        else:
            out.append(0.0)
    return np.asarray(out, dtype=float)


def annualized_sharpe(pnl_bps_array: np.ndarray, trades_per_year: float) -> float:
    arr = np.asarray(pnl_bps_array, dtype=float)
    if len(arr) < 2:
        return 0.0
    mu = float(arr.mean())
    sigma = float(arr.std())
    if sigma < 1e-12 or trades_per_year <= 0:
        return 0.0
    return float((mu / sigma) * np.sqrt(trades_per_year))


def run_gauntlet(
    all_trades: list,
    regimes_seen: list | set,
    days_total: float,
    fee_bps_roundtrip: float = FEE_BPS_ROUNDTRIP,
    oos_split: float = OOS_SPLIT_FRAC,
) -> GateReport:
    """Run all 5 gates. Returns a GateReport with pass/fail and diagnostics.

    `all_trades` — list of TradeLog dataclasses OR dicts with pnl_bps.
    `regimes_seen` — iterable of regime strings the creature actually traded in.
    `days_total` — episode duration in days.
    """
    n = len(all_trades)

    # ── Gate 0: minimum trade count ──
    if n < MIN_TRADES:
        return GateReport(False, f"N={n}<{MIN_TRADES}", n,
                          0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                          list(regimes_seen), float(days_total))

    # Split into train/oos by time order (last oos_split% are OOS)
    split_idx = int(n * (1.0 - oos_split))
    trades_train = all_trades[:split_idx]
    trades_oos   = all_trades[split_idx:]

    gross_all = _trades_to_bps(all_trades)
    gross_train = _trades_to_bps(trades_train)
    gross_oos = _trades_to_bps(trades_oos)

    # Gross trade pnl from core already accounts for fees (creature pays per leg).
    # Gauntlet applies fee NOT as deduction (avoid double counting) but as an
    # extra audit: we report "net if fees hadn't been deducted", to check that
    # gross had edge in bps-terms before cost.
    fees_bps = fee_bps_roundtrip * n
    net_all = gross_all   # already net of fees at creature level
    net_train = gross_train
    net_oos = gross_oos

    gross_bps = float(gross_all.sum())
    net_bps_total = float(net_all.sum())
    net_bps_day = net_bps_total / max(float(days_total), 0.1)

    # ── Gate 1: net bps per day ──
    if net_bps_day < MIN_NET_BPS_DAY:
        return GateReport(False, f"net_bps_day={net_bps_day:.2f}<{MIN_NET_BPS_DAY}",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          0.0, 0.0, 0.0, 0.0, net_bps_total, 0.0,
                          list(regimes_seen), float(days_total))

    if len(net_train) < 2 or len(net_oos) < 2:
        return GateReport(False, "insufficient split for OOS",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          0.0, 0.0, 0.0, 0.0, net_bps_total, 0.0,
                          list(regimes_seen), float(days_total))

    trades_per_day = n / max(float(days_total), 0.1)
    sharpe_train = annualized_sharpe(net_train, trades_per_day * 365.0)
    sharpe_oos = annualized_sharpe(net_oos, trades_per_day * 365.0)

    # ── Gate 2: non-negative train sharpe ──
    if sharpe_train <= 0:
        return GateReport(False, f"sharpe_train={sharpe_train:.2f}<=0",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          sharpe_train, sharpe_oos, 0.0, 0.0, net_bps_total, 0.0,
                          list(regimes_seen), float(days_total))

    # ── Gate 3: OOS ratio ──
    oos_ratio = sharpe_oos / sharpe_train
    if oos_ratio < MIN_OOS_RATIO:
        return GateReport(False, f"oos_ratio={oos_ratio:.2f}<{MIN_OOS_RATIO}",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          sharpe_train, sharpe_oos, oos_ratio, 0.0, net_bps_total, 0.0,
                          list(regimes_seen), float(days_total))

    # Cumulative equity curve for Calmar-like
    equity = np.cumsum(net_all)
    peak = np.maximum.accumulate(equity)
    drawdowns = peak - equity
    max_dd = float(drawdowns.max()) if len(drawdowns) else 0.0
    final_equity = float(equity[-1]) if len(equity) else 0.0
    calmar_like = (final_equity / (max_dd + 1e-9)) if final_equity > 0 else 0.0

    # ── Gate 4: Calmar-like ≥ MIN ──
    if calmar_like < MIN_CALMAR_LIKE:
        return GateReport(False, f"calmar_like={calmar_like:.2f}<{MIN_CALMAR_LIKE}",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          sharpe_train, sharpe_oos, oos_ratio, max_dd, final_equity,
                          calmar_like, list(regimes_seen), float(days_total))

    # ── Gate 5: regime diversity ──
    regimes_list = sorted(set(regimes_seen))
    if len(regimes_list) < MIN_DISTINCT_REGIMES:
        return GateReport(False, f"regimes={len(regimes_list)}<{MIN_DISTINCT_REGIMES}",
                          n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                          sharpe_train, sharpe_oos, oos_ratio, max_dd, final_equity,
                          calmar_like, regimes_list, float(days_total))

    # All passed
    return GateReport(True, None,
                      n, gross_bps, fees_bps, net_bps_total, net_bps_day,
                      sharpe_train, sharpe_oos, oos_ratio, max_dd, final_equity,
                      calmar_like, regimes_list, float(days_total))


def gate_report_to_dict(r: GateReport) -> dict:
    return asdict(r)
