"""
Creature — stateful agent that lives tick-by-tick.

Invariants (checked in code):
  - capital is real USD, monotone inside a tick (no retroactive rewrites)
  - a closed position pays fees via execution.fees ONCE per leg
  - trajectory is a list of (tick, capital, Z) where Z = cumulative execution
    drag (fees + slippage_cost) / cumulative notional. Units: decimal.
  - death is permanent: once alive=False, the creature is skipped in the loop.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from ..config import INITIAL_CAPITAL, DEATH_FRAC, KELLY_CAP
from ..execution.simulator import SimState
from ..execution.fees import roundtrip_fee_decimal
from .genes import Genome
from .actions import entry_signal, exit_signal, kelly_capped_size


@dataclass
class TradeLog:
    tick_open: int
    tick_close: int
    side: int
    entry_price: float
    exit_price: float
    size_usd: float
    fees_paid: float
    slippage_cost: float   # USD lost to execution vs mid-mid
    net_pnl_usd: float
    net_pnl_decimal: float
    regime: str
    exit_reason: str


@dataclass
class Creature:
    genome: Genome
    capital: float = INITIAL_CAPITAL
    peak_capital: float = INITIAL_CAPITAL
    alive: bool = True

    # Open-position state
    position_side: int = 0           # +1 long, -1 short, 0 flat
    position_size_usd: float = 0.0
    entry_price: float = 0.0
    entry_tick: int = -1
    entry_regime: str = "chop"

    # Lifetime counters
    trades: list[TradeLog] = field(default_factory=list)
    cumulative_notional: float = 0.0
    cumulative_fees: float = 0.0
    cumulative_slippage_cost: float = 0.0
    regimes_seen: set = field(default_factory=set)
    cooldown_until_tick: int = -1
    death_tick: int | None = None

    # Convexity accounting (Taleb-style: reward PnL *during* tail ticks)
    ticks_in_vol_spike: int = 0
    return_in_vol_spike: float = 0.0

    # 3D trajectory: (tick, capital, Z) sampled every tick.
    # Kept at target density via downsampling in save().
    trajectory: list[tuple[int, float, float]] = field(default_factory=list)

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------
    def step(self, sim: SimState, features: dict, regime: str,
             is_vol_spike: bool = False) -> None:
        """Advance one tick. Called by world3d.World for every living creature.
        `is_vol_spike` signals a tail-event tick (|mom_z|>2); the creature's
        MTM delta during these ticks feeds the convexity_bonus in fitness."""
        if not self.alive:
            return

        prev_eq = self.trajectory[-1][1] if self.trajectory else INITIAL_CAPITAL

        # 1) check open position for exit
        if self.position_side != 0:
            reason = exit_signal(
                price_now=sim.mid,
                entry_price=self.entry_price,
                side=self.position_side,
                ticks_in_position=sim.tick - self.entry_tick,
                genes=self.genome.genes,
            )
            if reason is not None:
                self._close(sim, reason=reason)

        # 2) otherwise evaluate entry (respecting cooldown)
        if self.position_side == 0 and sim.tick >= self.cooldown_until_tick:
            direction = entry_signal(features, self.genome.genes, regime)
            if direction != 0:
                self._open(sim, side=direction, regime=regime)

        # 3) compute MTM equity and mark trajectory
        cur_eq = self.mark_to_market(sim.mid)
        self._record_trajectory(sim.tick, cur_eq)

        # 4) convexity accounting during spike ticks
        if is_vol_spike:
            self.ticks_in_vol_spike += 1
            if prev_eq > 0:
                self.return_in_vol_spike += (cur_eq - prev_eq) / prev_eq

        # 5) death test on MTM equity (not just cash)
        if cur_eq < INITIAL_CAPITAL * DEATH_FRAC:
            self._die(sim)

    def unrealized_pnl_usd(self, current_price: float) -> float:
        if self.position_side == 0:
            return 0.0
        move = (current_price - self.entry_price) / max(self.entry_price, 1e-9)
        return self.position_size_usd * move * self.position_side

    def mark_to_market(self, current_price: float) -> float:
        return self.capital + self.unrealized_pnl_usd(current_price)

    @property
    def max_drawdown_frac(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return max(0.0, 1.0 - self.capital / self.peak_capital)

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------
    def _open(self, sim: SimState, side: int, regime: str) -> None:
        g = self.genome.genes
        # Online Kelly: use own stats from closed trades so far
        wins = [t.net_pnl_decimal for t in self.trades if t.net_pnl_decimal > 0]
        losses = [abs(t.net_pnl_decimal) for t in self.trades if t.net_pnl_decimal < 0]
        size_frac = kelly_capped_size(
            base_size_frac=float(g.get("size_frac", 0.25)),
            win_rate=(len(wins) / max(1, len(self.trades))),
            avg_win=float(np.mean(wins)) if wins else 0.0,
            avg_loss=float(np.mean(losses)) if losses else 0.0,
            cap=KELLY_CAP,
        )
        if size_frac <= 0:
            return
        req_usd = self.capital * size_frac
        if req_usd < 1.0:  # below 1 USD, not worth executing
            return

        fill = sim.submit(side=side, requested_usd=req_usd)
        if fill is None or fill.filled_usd <= 0:
            return

        # slippage_cost in USD vs mid at fill time
        mid_at_fill = sim.mid_at(fill.tick_filled)
        slip_cost = abs(fill.fill_price - mid_at_fill) * (fill.filled_usd /
                                                          max(fill.fill_price, 1e-9))
        # Entry leg fee is already in fill.fee_paid
        self.capital -= fill.fee_paid  # pay entry leg fee now
        self.cumulative_fees += fill.fee_paid
        self.cumulative_slippage_cost += slip_cost
        self.cumulative_notional += fill.filled_usd

        self.position_side = side
        self.position_size_usd = fill.filled_usd
        self.entry_price = fill.fill_price
        self.entry_tick = fill.tick_filled
        self.entry_regime = regime
        self.regimes_seen.add(regime)

    def _close(self, sim: SimState, reason: str) -> None:
        side = self.position_side
        assert side != 0
        fill = sim.submit(side=-side, requested_usd=self.position_size_usd)
        if fill is None:
            # Forced close at last tick — compute pnl vs last mid, no fee
            exit_px = sim.mid
            fee = 0.0
            slip_cost = 0.0
        else:
            exit_px = fill.fill_price
            fee = fill.fee_paid
            mid_exit = sim.mid_at(fill.tick_filled)
            slip_cost = abs(exit_px - mid_exit) * (fill.filled_usd /
                                                    max(exit_px, 1e-9))

        move_dec = (exit_px - self.entry_price) / max(self.entry_price, 1e-9) * side
        gross_pnl_usd = self.position_size_usd * move_dec
        # Net = gross - exit leg fee. Entry fee already paid at _open.
        net_pnl_usd = gross_pnl_usd - fee
        self.capital += net_pnl_usd
        self.cumulative_fees += fee
        self.cumulative_slippage_cost += slip_cost
        self.cumulative_notional += (fill.filled_usd if fill else 0.0)

        self.trades.append(TradeLog(
            tick_open=self.entry_tick,
            tick_close=sim.tick if fill is None else fill.tick_filled,
            side=side,
            entry_price=self.entry_price,
            exit_price=exit_px,
            size_usd=self.position_size_usd,
            fees_paid=fee,   # exit leg only, paired with entry leg in cumulative
            slippage_cost=slip_cost,
            net_pnl_usd=net_pnl_usd,
            net_pnl_decimal=net_pnl_usd / max(self.position_size_usd, 1e-9),
            regime=self.entry_regime,
            exit_reason=reason,
        ))
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital

        self.position_side = 0
        self.position_size_usd = 0.0
        self.entry_price = 0.0
        self.entry_tick = -1
        self.cooldown_until_tick = sim.tick + int(self.genome.genes.get("cooldown_ticks", 20))

    def _die(self, sim: SimState) -> None:
        self.alive = False
        self.death_tick = sim.tick
        if self.position_side != 0:
            # Liquidate at mid with no fee (already dead economically)
            move_dec = (sim.mid - self.entry_price) / max(self.entry_price, 1e-9) * self.position_side
            self.capital += self.position_size_usd * move_dec
            self.position_side = 0
            self.position_size_usd = 0.0

    def _record_trajectory(self, tick: int, equity: float | None = None) -> None:
        # Z = cumulative execution drag as decimal of cumulative notional
        if self.cumulative_notional > 0:
            z = (self.cumulative_fees + self.cumulative_slippage_cost) / self.cumulative_notional
        else:
            z = 0.0
        eq = float(equity) if equity is not None else float(self.capital)
        self.trajectory.append((tick, eq, z))
