"""
Fees — the ONLY source of truth. No other module in encruzilhada3d is
allowed to define, override, or redefine a fee rate. If you see
`pnl -= 0.001` or similar outside this file, it's a bug.

Two fee tiers (taker / maker) are configurable via env vars; they are
converted to decimal once at import time and reused. Funding is optional
and charged per N ticks, independent of fills.
"""
from __future__ import annotations
import os


_BPS_TAKER = float(os.getenv("ENC3D_FEE_BPS_TAKER", "5.0"))   # 5 bps = 0.05% per leg
_BPS_MAKER = float(os.getenv("ENC3D_FEE_BPS_MAKER", "1.0"))   # 1 bps = 0.01% per leg

_FUNDING_BPS_PER_INTERVAL = float(os.getenv("ENC3D_FUNDING_BPS", "0.0"))
_FUNDING_EVERY_N_TICKS    = int(os.getenv("ENC3D_FUNDING_N_TICKS", "0"))


def bps_to_decimal(bps: float) -> float:
    return float(bps) * 1e-4


def fee_decimal_per_leg(is_taker: bool = True) -> float:
    """Per-leg fee in decimal. 5 bps taker → 0.0005."""
    return bps_to_decimal(_BPS_TAKER if is_taker else _BPS_MAKER)


def roundtrip_fee_decimal(is_taker: bool = True) -> float:
    return 2.0 * fee_decimal_per_leg(is_taker)


def fee_usd(notional_usd: float, is_taker: bool = True) -> float:
    """Fee charged on ONE leg of `notional_usd`."""
    return abs(float(notional_usd)) * fee_decimal_per_leg(is_taker)


def apply_fee_decimal(notional: float, fee_dec: float) -> float:
    """Explicit helper for tests & audits: fee in quote currency for a
    notional and a decimal rate. Caller picks the rate."""
    return abs(float(notional)) * float(fee_dec)


# -----------------------------------------------------------------------------
# Funding (per-interval; caller decides when to invoke)
# -----------------------------------------------------------------------------
def funding_charge_usd(position_notional: float,
                       funding_bps: float | None = None) -> float:
    """USD charge on position notional at a funding boundary. Positive =
    holder pays. If `funding_bps` omitted, uses the env-configured rate."""
    bps = _FUNDING_BPS_PER_INTERVAL if funding_bps is None else float(funding_bps)
    return float(position_notional) * bps_to_decimal(bps)


def should_charge_funding(tick: int) -> bool:
    """True if this tick is a funding boundary. Disabled when interval ≤ 0."""
    if _FUNDING_EVERY_N_TICKS <= 0:
        return False
    return tick > 0 and (tick % _FUNDING_EVERY_N_TICKS == 0)
