"""
World3D — the main loop.

Every tick:
  1. Advance the shared SimState (decays crowding, bumps tick counter).
  2. Compute features + regime at this tick ONCE.
  3. For each living creature, call .step(sim, features, regime).
  4. After all creatures act, no further market update (simulator is
     driven by the underlying price series, not by creatures — but
     crowding is now elevated for next tick, which is how the reef
     self-influences execution cost without letting creatures fake-trade
     the tape).

At episode end:
  - Each creature is scored by creatures.fitness.creature_fitness.
  - Extreme outcomes are logged to tail_bank.
  - Survivors feed reproduction for generation+1.

This design kills:
  - replay bias: decisions happen tick-by-tick on a live SimState with
    no future information
  - false ecology: the crowding accumulator transmits reef-level pressure
    back into slippage in real time
  - tail underfitting: every death and every ≥DRAWDOWN_EVENT_FRAC drop is
    written to tail_bank and penalizes nearby genomes next generation
  - fitness drift: log-growth in decimal, multipliers in [0,1], penalty
    in decimal (same units). Stays stable across symbols/generations.
  - latency blindness: execution.fills forces fill at tick+delay with
    slippage ~ √(size/depth) · (1+crowding)
  - signal correlation trap: features.snapshot returns four channels
    computed from different moments; actions.entry_signal requires
    agreement between momentum and imbalance (or explicit disagreement
    for revert), never between two proxies of the same quantity.
"""
from __future__ import annotations
import json
import random
import time
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd

from ..config import (DEFAULT_POPULATION, DEFAULT_EPISODE_TICKS,
                      DEFAULT_GENERATIONS, INITIAL_CAPITAL,
                      DRAWDOWN_EVENT_FRAC, GAIN_EVENT_FRAC,
                      CREATURES_FILE, CHAMPION_FILE, HISTORY_FILE,
                      REPORT_FILE, RNG_SEED)
from ..market import book as mbook
from ..market.features import snapshot
from ..market.regimes import classify
from ..creatures.creature import Creature
from ..creatures.genes import Genome, random_genome
from ..creatures.fitness import creature_fitness
from ..execution.simulator import SimState
from . import tail_bank
from .selection import rank, pick_survivors
from .reproduction import reproduce


def _episode_days(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 1.0
    span_ms = int(df["ts"].iloc[-1] - df["ts"].iloc[0])
    days = span_ms / (86_400_000.0)
    return max(0.1, days)


def _log_tail_events(creature: Creature, gen: int) -> None:
    peak = max(INITIAL_CAPITAL, creature.peak_capital)
    dd = 1.0 - (creature.capital / peak) if peak > 0 else 0.0
    gain = (creature.capital - INITIAL_CAPITAL) / INITIAL_CAPITAL
    base = {"genome_id": creature.genome.genome_id,
            "genes": creature.genome.genes,
            "gen": gen}
    if not creature.alive:
        tail_bank.log_event({**base, "type": "death",
                             "severity_decimal": 1.0 - (creature.capital / INITIAL_CAPITAL),
                             "death_tick": creature.death_tick})
    elif dd >= DRAWDOWN_EVENT_FRAC:
        tail_bank.log_event({**base, "type": "drawdown",
                             "severity_decimal": float(dd)})
    if gain >= GAIN_EVENT_FRAC:
        tail_bank.log_event({**base, "type": "gain",
                             "severity_decimal": float(gain)})


class World3D:
    def __init__(self,
                 symbol: str = "ADAUSDT",
                 population: int = DEFAULT_POPULATION,
                 episode_ticks: int = DEFAULT_EPISODE_TICKS,
                 seed: int | None = RNG_SEED):
        self.symbol = symbol
        self.population = int(population)
        self.episode_ticks = int(episode_ticks)
        self.rng = random.Random(seed) if seed is not None else random.Random()
        self.df = mbook.load(symbol)
        self.prices = mbook.prices_array(self.df)
        self.episode_days = _episode_days(self.df)
        # Trim to episode_ticks if longer; else use all
        if len(self.prices) > self.episode_ticks:
            self.prices = self.prices[-self.episode_ticks:]
            self.df = self.df.iloc[-self.episode_ticks:].reset_index(drop=True)
            self.episode_days = _episode_days(self.df)

        self.genomes: list[Genome] = [random_genome(0, self.rng)
                                      for _ in range(self.population)]
        self.history: list[dict] = []
        self.champion: dict | None = None

    # --------------------------------------------------------------
    def run_generations(self, generations: int = DEFAULT_GENERATIONS) -> None:
        for g in range(1, generations + 1):
            t0 = time.time()
            evaluations = self.run_episode(gen=g)
            ranked = rank(evaluations)
            survivors = pick_survivors(ranked, n=max(4, self.population // 3))
            self._record_gen(g, ranked, survivors, dt=time.time() - t0)
            self.genomes = [x.genome for x in reproduce(
                survivors=survivors, pop_size=self.population,
                gen=g + 1, rng=self.rng,
            )] if g < generations else self.genomes
            # Stop early if everyone died and no edge exists
            if all(not s["metrics"]["alive"] for s in survivors):
                print(f"[gen {g}] total extinction among top — reseeding pop")
                self.genomes = [random_genome(g + 1, self.rng) for _ in range(self.population)]

    def run_episode(self, gen: int) -> list[dict]:
        sim = SimState(prices=self.prices)
        creatures = [Creature(genome=g) for g in self.genomes]

        # tick loop
        n = min(self.episode_ticks, sim.n_ticks - 1)
        # Warm-up: we need at least 60 ticks of history before any feature is useful.
        for sim.tick in range(60, n):
            feats = snapshot(self.prices, sim.tick,
                             trend_lookback=60)  # per-creature lookback applied inside entry
            regime = classify(self.prices, sim.tick)
            # Tail-tick flag: |mom_z|>2 marks a significance-level-2 move.
            # Fed to creature.step so convexity_bonus can reward positive PnL here.
            is_spike = abs(float(feats.get("mom_z", 0.0))) > 2.0
            for c in creatures:
                c.step(sim, feats, regime, is_vol_spike=is_spike)
            sim.advance()  # bumps tick counter AND decays crowding

        # Force-close any open positions at the last tick
        for c in creatures:
            if c.alive and c.position_side != 0:
                c._close(sim, reason="episode_end")

        # Score each creature
        evals: list[dict] = []
        for c in creatures:
            f = creature_fitness(c, self.episode_days, n)
            _log_tail_events(c, gen)
            evals.append({"creature": c, **f})
        return evals

    # --------------------------------------------------------------
    def _record_gen(self, gen: int, ranked: list[dict],
                    survivors: list[dict], dt: float) -> None:
        top = ranked[0]
        alive_n = sum(1 for e in ranked if e["metrics"]["alive"])
        rec = {
            "gen": gen,
            "dt_sec": round(dt, 2),
            "pop": len(ranked),
            "alive": alive_n,
            "best_fitness": top["fitness"],
            "best_genome": top["creature"].genome.to_dict(),
            "best_metrics": top["metrics"],
            "bank_summary": tail_bank.summarize(),
        }
        self.history.append(rec)
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        if self.champion is None or top["fitness"] > self.champion["fitness"]:
            self.champion = {
                "gen": gen,
                "fitness": top["fitness"],
                "components": top["components"],
                "metrics": top["metrics"],
                "genome": top["creature"].genome.to_dict(),
            }
            CHAMPION_FILE.write_text(json.dumps(self.champion, indent=2, default=str))
        finite = [e["fitness"] for e in ranked if e["fitness"] > float("-inf")]
        fit_std = float(np.std(finite)) if len(finite) > 1 else 0.0
        print(f"[gen {gen}] dt={dt:.1f}s  alive={alive_n}/{len(ranked)}  "
              f"fit_std={fit_std:.3f}  best_fit={top['fitness']:.4f}  "
              f"final_cap={top['metrics']['final_capital']:.2f}  "
              f"trades={top['metrics']['n_trades']}  "
              f"dd={top['metrics']['max_drawdown_frac']:.2%}")

    # --------------------------------------------------------------
    def save_final_report(self, out_path: Path | None = None) -> dict:
        out_path = out_path or REPORT_FILE
        rep = {
            "symbol": self.symbol,
            "population": self.population,
            "episode_ticks": self.episode_ticks,
            "episode_days": self.episode_days,
            "generations_run": len(self.history),
            "champion": self.champion,
            "tail_bank": tail_bank.summarize(),
            "ts": time.time(),
        }
        out_path.write_text(json.dumps(rep, indent=2, default=str))
        return rep

    def dump_creatures(self, creatures_evals: list[dict]) -> None:
        """Write last-episode creatures to JSONL for viz."""
        with open(CREATURES_FILE, "w") as f:
            for e in creatures_evals:
                c = e["creature"]
                # Downsample trajectory to ~200 points for HTML viz
                traj = c.trajectory
                if len(traj) > 200:
                    step = len(traj) // 200
                    traj = traj[::step]
                row = {
                    "genome_id": c.genome.genome_id,
                    "alive": c.alive,
                    "fitness": e["fitness"],
                    "components": e.get("components", {}),
                    "metrics": e["metrics"],
                    "trajectory": traj,
                }
                f.write(json.dumps(row, default=str) + "\n")
