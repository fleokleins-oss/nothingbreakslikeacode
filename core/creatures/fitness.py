"""
Fitness — antifragile, dimensionally coherent, tail-aware.

    fitness = log_growth_annualized * regime_factor * survival_factor
              - tail_penalty_local

All terms are in decimal per-year (a pure growth rate). Subtracting a
decimal tail penalty is dimensionally legal and lets us compare genomes
with wildly different trade counts directly.

Growth is computed from the *actual realized capital path* — we do NOT
reapply Kelly in fitness. Kelly is a risk policy applied at sizing time,
inside the creature. Fitness just rewards what actually happened.
"""
from __future__ import annotations
import math
import numpy as np

from ..config import INITIAL_CAPITAL, TRADING_DAYS_PER_YEAR
from ..engine.tail_bank import tail_penalty, load as load_bank

CONVEXITY_BONUS_MAX = 0.20   # cap: +20% of fitness for strong tail-convexity
# Activity gating lives in selection.py (hard tier ≥30 trades). The fitness
# here stays clean: 0 trades → -inf, else the canonical log-growth formula.
# A soft-penalty multiplier inside fitness was redundant with the selection
# gate and would double-count the cost of being half-active.


def _regime_factor(regimes_seen: set) -> float:
    """Multiplier. Harder monoculture penalty:
    1 regime → 0.47, 2 → 0.74, 3+ → 1.0. Forces diversity earlier."""
    n = len(regimes_seen)
    return min(1.0, 0.20 + 0.27 * n)


CONVEXITY_FULL_AVG = 5e-6     # avg MTM return per spike-tick that buys full bonus.
                              # calibrated to crypto TICK data — a creature that
                              # generates +0.5 bp avg per spike tick (across ALL
                              # spike ticks, including those where it's flat) is
                              # genuinely exploiting the tails. zip's 0.01 would
                              # require a creature compounding 10%/spike average,
                              # which is orders-of-magnitude off from real tape.


def _convexity_bonus(creature) -> float:
    """
    Taleb convexity: reward positive MTM return *during* tail ticks.
    Returns bonus in [0, CONVEXITY_BONUS_MAX]. Zero when there are no
    spikes, or average per-spike return is non-positive. Scale is set by
    CONVEXITY_FULL_AVG (see note).
    """
    if creature.ticks_in_vol_spike <= 0:
        return 0.0
    avg = creature.return_in_vol_spike / creature.ticks_in_vol_spike
    if avg <= 0:
        return 0.0
    scale = min(1.0, avg / CONVEXITY_FULL_AVG)
    return CONVEXITY_BONUS_MAX * scale


def _survival_factor(alive: bool, death_tick: int | None,
                     total_ticks: int) -> float:
    if alive:
        return 1.0
    if total_ticks <= 0:
        return 0.0
    # Quadratic penalty: dying at 50% of the episode yields 0.25 factor
    frac = max(0.0, min(1.0, (death_tick or 0) / total_ticks))
    return frac ** 2


def creature_fitness(creature,
                     episode_days: float,
                     total_ticks: int) -> dict:
    """
    Returns {fitness, components, metrics} for one creature.
    `creature` must expose: capital, alive, death_tick, regimes_seen,
    trades, genome, trajectory, peak_capital.
    """
    # ------- log-growth (real, realized) -------
    final_cap = creature.capital
    growth = math.log(max(final_cap, 1e-9) / INITIAL_CAPITAL)
    days = max(episode_days, 0.1)
    log_growth_annualized = growth * TRADING_DAYS_PER_YEAR / days

    # ------- multipliers -------
    regime_mult = _regime_factor(creature.regimes_seen)
    surv_mult = _survival_factor(creature.alive, creature.death_tick, total_ticks)

    # ------- convexity bonus (Taleb: win during tails) -------
    conv_bonus = _convexity_bonus(creature)

    # ------- inactivity penalty (no free ride) -------
    # A creature that never trades contributed nothing to the ecology, leaves
    # no evidence of antifragility, and must not be rewarded for cowardice.
    # We give it -infinity directly so selection can still compare against
    # creatures that DID try and lost. Creatures that tried a reasonable
    # amount pay no penalty.
    if len(creature.trades) == 0:
        return {
            "fitness": float("-inf"),
            "components": {
                "log_growth_annualized": 0.0,
                "regime_factor": float(regime_mult),
                "survival_factor": float(surv_mult),
                "convexity_bonus": 0.0,
                "tail_penalty": 0.0,
                "inactivity": True,
            },
            "metrics": {
                "final_capital": float(final_cap),
                "peak_capital": float(creature.peak_capital),
                "max_drawdown_frac": float(creature.max_drawdown_frac),
                "alive": bool(creature.alive),
                "death_tick": creature.death_tick,
                "n_trades": 0,
                "win_rate": 0.0,
                "avg_return_dec": 0.0,
                "convexity_skew": 0.0,
                "regimes_seen": sorted(list(creature.regimes_seen)),
                "exec_fees_frac": 0.0,
                "exec_slippage_frac": 0.0,
                "ticks_in_vol_spike": int(creature.ticks_in_vol_spike),
                "return_in_vol_spike": float(creature.return_in_vol_spike),
            },
        }

    # ------- local tail penalty (decimal per year: scale by 1 = same units) -------
    bank = load_bank()
    tail_pen = tail_penalty(creature.genome.genes, bank)

    fitness = log_growth_annualized * regime_mult * surv_mult * (1.0 + conv_bonus) - tail_pen

    # ------- auxiliary metrics -------
    n_trades = len(creature.trades)
    if n_trades > 0:
        returns = np.array([t.net_pnl_decimal for t in creature.trades], dtype=float)
        win_rate = float((returns > 0).mean())
        avg_ret = float(returns.mean())
        std_ret = float(returns.std())
        # Convexity proxy: skewness of per-trade returns (fat right tail = good)
        if std_ret > 1e-9:
            convexity = float(((returns - avg_ret) ** 3).mean() / (std_ret ** 3))
        else:
            convexity = 0.0
    else:
        win_rate = avg_ret = std_ret = convexity = 0.0

    max_dd = creature.max_drawdown_frac
    total_fees_pct = (creature.cumulative_fees / max(creature.cumulative_notional, 1e-9))
    total_slip_pct = (creature.cumulative_slippage_cost / max(creature.cumulative_notional, 1e-9))

    return {
        "fitness": float(fitness),
        "components": {
            "log_growth_annualized": float(log_growth_annualized),
            "regime_factor": float(regime_mult),
            "survival_factor": float(surv_mult),
            "convexity_bonus": float(conv_bonus),
            "tail_penalty": float(tail_pen),
        },
        "metrics": {
            "final_capital": float(final_cap),
            "peak_capital": float(creature.peak_capital),
            "max_drawdown_frac": float(max_dd),
            "alive": bool(creature.alive),
            "death_tick": creature.death_tick,
            "n_trades": int(n_trades),
            "win_rate": float(win_rate),
            "avg_return_dec": float(avg_ret),
            "convexity_skew": float(convexity),
            "regimes_seen": sorted(list(creature.regimes_seen)),
            "exec_fees_frac": float(total_fees_pct),
            "exec_slippage_frac": float(total_slip_pct),
            "ticks_in_vol_spike": int(creature.ticks_in_vol_spike),
            "return_in_vol_spike": float(creature.return_in_vol_spike),
        },
    }
