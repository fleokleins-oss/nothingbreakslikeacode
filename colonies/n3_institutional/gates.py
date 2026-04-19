"""N3 institutional gates — same structure as N2, stricter thresholds.

Thin wrapper: reuses the 5-gate logic from n2_popper.gates but with N3's
tighter constants. Could be merged with n2.gates via parametrization, but
keeping them separate makes the difference explicit and auditable.
"""
from __future__ import annotations
from typing import Iterable
from dataclasses import asdict

# Reuse gate logic from N2 but with N3's constants
from colonies.n2_popper.gates import run_gauntlet as _n2_gauntlet
from colonies.n2_popper.gates import GateReport, gate_report_to_dict

from .config import (
    FEE_BPS_ROUNDTRIP, MIN_TRADES, MIN_NET_BPS_DAY, MIN_OOS_RATIO,
    MIN_CALMAR_LIKE, MIN_DISTINCT_REGIMES, OOS_SPLIT_FRAC,
)


def run_gauntlet(all_trades: list, regimes_seen: list | set,
                 days_total: float) -> GateReport:
    # Temporarily monkey-patch n2.gates thresholds via direct call
    # with N3 params (cleanest would be class-based; this is simpler).
    from colonies.n2_popper import gates as n2g
    saved = (n2g.MIN_TRADES, n2g.MIN_NET_BPS_DAY, n2g.MIN_OOS_RATIO,
             n2g.MIN_CALMAR_LIKE, n2g.MIN_DISTINCT_REGIMES)
    try:
        n2g.MIN_TRADES = MIN_TRADES
        n2g.MIN_NET_BPS_DAY = MIN_NET_BPS_DAY
        n2g.MIN_OOS_RATIO = MIN_OOS_RATIO
        n2g.MIN_CALMAR_LIKE = MIN_CALMAR_LIKE
        n2g.MIN_DISTINCT_REGIMES = MIN_DISTINCT_REGIMES
        return _n2_gauntlet(all_trades, regimes_seen, days_total,
                            fee_bps_roundtrip=FEE_BPS_ROUNDTRIP,
                            oos_split=OOS_SPLIT_FRAC)
    finally:
        (n2g.MIN_TRADES, n2g.MIN_NET_BPS_DAY, n2g.MIN_OOS_RATIO,
         n2g.MIN_CALMAR_LIKE, n2g.MIN_DISTINCT_REGIMES) = saved
