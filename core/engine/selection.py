"""
Selection — antifragile ranking. Rewards survival + growth + convexity.
Never ranks by Sharpe alone.

Rank key per creature, tuples compared left-to-right:
  1. alive              — True beats False
  2. proved activity    — n_trades ≥ MIN_TRADES_FOR_CHAMPION (30 by default).
                          Below this threshold, the creature hasn't generated
                          enough evidence to be a champion in a 9-day window
                          (3.3 trades/day is the realistic baseline for
                          tick-level crypto). Gate is hard: sub-threshold
                          creatures sit below *all* sufficiently-active ones
                          regardless of fitness.
  3. acted              — n_trades ≥ 1 (still applies among sub-threshold pool)
  4. fitness            — log-growth × regime × survival × (1+convex) − tail_pen
  5. convexity_skew     — positive fat right tail preferred
  6. max_drawdown       — smaller DD preferred, final tiebreak

All six dimensions explicit. No single metric can dominate pathologically.
"""
from __future__ import annotations
import os

MIN_TRADES_FOR_CHAMPION = int(os.getenv("ENC3D_MIN_TRADES_CHAMPION", "30"))


def rank(evaluations: list[dict]) -> list[dict]:
    """
    `evaluations` is a list of dicts each with keys:
      creature (Creature), fitness (float), components (dict), metrics (dict)
    Returns the same list sorted best-first.
    """
    def key(e):
        m = e["metrics"]
        n = m.get("n_trades", 0)
        return (
            0 if m["alive"] else 1,                       # alive first
            0 if n >= MIN_TRADES_FOR_CHAMPION else 1,     # champion-eligible first
            0 if n > 0 else 1,                             # at least acted
            -e["fitness"],                                 # higher fitness first
            -m["convexity_skew"],                          # positive skew first
            m["max_drawdown_frac"],                        # smaller DD first
        )
    return sorted(evaluations, key=key)


def pick_survivors(ranked: list[dict], n: int) -> list[dict]:
    """Take top-n. If fewer creatures are alive than n, include dead ones
    (they still carry genes — reproduction will mix them with living)."""
    n = max(1, n)
    return ranked[:n]


def select_parents(survivors: list[dict], k: int = 2,
                   rng=None) -> list[dict]:
    """Pick k parents biased by rank. Linear weight (no exponentials —
    keep selection pressure moderate so diversity survives)."""
    import random as _random
    r = rng or _random
    if not survivors:
        return []
    weights = [max(1, len(survivors) - i) for i in range(len(survivors))]
    return r.choices(survivors, weights=weights, k=k)
