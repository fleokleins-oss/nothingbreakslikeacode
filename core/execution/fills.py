"""
Fills — latency-aware execution. A creature decides on tick i; the fill
lands on tick i + DECISION_DELAY_TICKS at whatever price is current there.
Partial fills are possible when requested size exceeds `fill_cap_usd`
(proxy for available liquidity at the requested level).

This is how we defeat latency blindness: the creature cannot know its fill
price at decision time, and the worse the depth, the further from mid it ends up.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..config import DECISION_DELAY_TICKS
from .slippage import effective_fill_price
from .fees import fee_usd


@dataclass
class FillResult:
    filled_usd: float
    fill_price: float
    fee_paid: float
    side: int            # +1 buy, -1 sell
    tick_filled: int
    partial: bool


def execute_market(decision_tick: int,
                   fill_tick_price: float,
                   side: int,
                   requested_usd: float,
                   depth_usd: float,
                   fill_cap_usd: float,
                   crowding: float = 0.0) -> FillResult:
    """
    `fill_tick_price` is the mid at tick (decision_tick + DECISION_DELAY_TICKS)
    and MUST be looked up by the caller (simulator). We do not re-look up here.
    """
    filled = min(requested_usd, fill_cap_usd) if fill_cap_usd > 0 else requested_usd
    partial = filled < requested_usd - 1e-9
    px = effective_fill_price(fill_tick_price, side, filled, depth_usd, crowding)
    fee = fee_usd(filled)
    return FillResult(filled_usd=filled, fill_price=px, fee_paid=fee,
                      side=side,
                      tick_filled=decision_tick + DECISION_DELAY_TICKS,
                      partial=partial)
