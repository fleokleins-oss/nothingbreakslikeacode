"""
N2 Popper runner — 24/7 training with gauntlet gate.

Identical cycle structure to N1 but:
  - After each episode, each creature's trades are run through run_gauntlet()
  - metrics['gauntlet_passed'] is True/False and always present
  - Champion selection prefers gauntlet-passed genomes over fitness alone

Systemd: reef-n2.service invokes this as `python3 -m colonies.n2_popper.run`.
"""
from __future__ import annotations
import os
import sys
import time
import json
import shutil
import signal
import traceback
from dataclasses import asdict
from pathlib import Path

# Force colony BEFORE core.config import
os.environ["REEF_COLONY"] = "n2_popper"

from core.config import (
    STATE_ROOT, CHAMPION_FILE, REPORT_FILE, HISTORY_FILE, VIZ_HTML,
    GAUNTLET_FILE,
)
from core.engine.world3d import World3D
from core.engine.selection import rank, pick_survivors
from core.engine.reproduction import reproduce
from core.viz import chart3d
from .config import (
    DEFAULT_POP, DEFAULT_TICKS, DEFAULT_GENS, DEFAULT_SEED,
    SYMBOLS, CYCLE_PAUSE_SEC, COLONY_NAME,
)
from .gates import run_gauntlet, gate_report_to_dict

_stop = False


def _sig(signum, frame):
    global _stop
    _stop = True
    print(f"[{COLONY_NAME}] signal {signum} — stopping after cycle")


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def _clear_live_state():
    for f in (CHAMPION_FILE, REPORT_FILE, HISTORY_FILE,
              STATE_ROOT / "creatures.jsonl", STATE_ROOT / "tail_bank.jsonl"):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def _archive_cycle(symbol: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    arc = STATE_ROOT / f"runs_{stamp}"
    sym_arc = arc / f"state_{symbol}"
    sym_arc.mkdir(parents=True, exist_ok=True)
    for name in ("champion.json", "report.json", "history.jsonl",
                 "creatures.jsonl", "tail_bank.jsonl", "reef3d.html",
                 "gauntlet.jsonl"):
        src = STATE_ROOT / name
        if src.exists():
            try:
                shutil.copy2(src, sym_arc / name)
            except Exception as e:
                print(f"[{COLONY_NAME}] archive err {name}: {e}")
    return arc


def _run_gauntlet_on_evals(evals: list, episode_days: float, gen: int):
    """For each eval, run gauntlet on its trades and mutate metrics in place.

    Adds to each eval['metrics']: 'gauntlet_passed', 'gauntlet_report'.
    Logs every attempt to GAUNTLET_FILE (audit trail).
    """
    with open(GAUNTLET_FILE, "a") as f:
        for e in evals:
            c = e.get("creature")
            if c is None:
                e["metrics"]["gauntlet_passed"] = False
                continue
            trades = list(c.trades)
            regimes = list(c.regimes_seen) if isinstance(c.regimes_seen, (set, list)) else []
            rep = run_gauntlet(
                all_trades=trades,
                regimes_seen=regimes,
                days_total=episode_days,
            )
            e["metrics"]["gauntlet_passed"] = rep.passed
            e["metrics"]["gauntlet_reason"] = rep.failure_reason
            e["metrics"]["gauntlet_calmar"] = rep.calmar_like
            e["metrics"]["gauntlet_sharpe_oos"] = rep.sharpe_oos
            e["metrics"]["gauntlet_oos_ratio"] = rep.oos_ratio
            f.write(json.dumps({
                "gen": gen,
                "genome_id": c.genome.genome_id,
                "passed": rep.passed,
                "reason": rep.failure_reason,
                "report": gate_report_to_dict(rep),
            }, default=str) + "\n")


def _popper_rank(evals: list) -> list:
    """Popper ranking: gauntlet-passed genomes first, then by fitness."""
    def key(e):
        m = e["metrics"]
        return (
            0 if m.get("alive") else 1,
            0 if m.get("gauntlet_passed") else 1,   # <<< gauntlet gate
            0 if m.get("n_trades", 0) >= 30 else 1,
            0 if m.get("n_trades", 0) > 0 else 1,
            -e["fitness"],
            -m.get("convexity_skew", 0.0),
            m.get("max_drawdown_frac", 0.0),
        )
    return sorted(evals, key=key)


def run_one_cycle(symbol: str, pop: int, ticks: int, gens: int,
                  seed: int | None) -> dict:
    print(f"[{COLONY_NAME}] cycle sym={symbol} pop={pop} "
          f"ticks={ticks} gens={gens} seed={seed}")
    _clear_live_state()
    w = World3D(symbol=symbol, population=pop,
                episode_ticks=ticks, seed=seed)
    print(f"[{COLONY_NAME}] loaded {len(w.prices)} ticks "
          f"spanning {w.episode_days:.2f} days")

    last_evals: list[dict] = []
    try:
        for g in range(1, gens + 1):
            if _stop:
                break
            te = time.time()
            evals = w.run_episode(gen=g)
            _run_gauntlet_on_evals(evals, w.episode_days, g)
            ranked = _popper_rank(evals)  # gauntlet-aware ranking
            survivors = pick_survivors(ranked, n=max(4, pop // 3))
            w._record_gen(g, ranked, survivors, dt=time.time() - te)
            last_evals = ranked
            if g < gens:
                w.genomes = [x for x in reproduce(
                    survivors, pop_size=pop, gen=g + 1, rng=w.rng)]
    finally:
        rep = w.save_final_report()
        w.dump_creatures(last_evals)
        try:
            chart3d.render(prices=w.prices, champion=rep.get("champion"))
        except Exception as e:
            print(f"[{COLONY_NAME}] viz err: {e}")
    return rep


def main():
    pop = DEFAULT_POP
    ticks = DEFAULT_TICKS
    gens = DEFAULT_GENS
    seed = DEFAULT_SEED
    print(f"[{COLONY_NAME}] running — STATE_ROOT={STATE_ROOT}")
    print(f"[{COLONY_NAME}] symbols={SYMBOLS} pause={CYCLE_PAUSE_SEC}s")
    cycle_i = 0
    while not _stop:
        sym = SYMBOLS[cycle_i % len(SYMBOLS)]
        cycle_i += 1
        t0 = time.time()
        try:
            rep = run_one_cycle(sym, pop, ticks, gens, seed + cycle_i)
            champ = rep.get("champion")
            if champ:
                m = champ.get("metrics", {})
                print(f"[{COLONY_NAME}] cycle #{cycle_i} {sym}: "
                      f"fit={champ.get('fitness', 0):+.3f} "
                      f"trades={m.get('n_trades', 0)} "
                      f"gauntlet={m.get('gauntlet_passed', False)}")
            _archive_cycle(sym)
        except Exception as e:
            print(f"[{COLONY_NAME}] cycle err: {e}")
            traceback.print_exc()

        dt = time.time() - t0
        print(f"[{COLONY_NAME}] cycle dt={dt:.1f}s — sleeping {CYCLE_PAUSE_SEC}s")
        for _ in range(CYCLE_PAUSE_SEC):
            if _stop:
                break
            time.sleep(1)
    print(f"[{COLONY_NAME}] stopped after {cycle_i} cycles")


if __name__ == "__main__":
    main()
