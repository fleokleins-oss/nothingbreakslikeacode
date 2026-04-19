"""
N1 Darwin runner — 24/7 training loop.

One cycle = one symbol × N gens. At cycle end, archives results to
runs_<timestamp>/ then rotates to next symbol. Produces:
  STATE_ROOT/n1_darwin/state/ — live
  STATE_ROOT/n1_darwin/runs_<ts>/state_<SYM>/ — archived per cycle

Systemd: reef-n1.service invokes this as `python3 -m colonies.n1_darwin.run`.
"""
from __future__ import annotations
import os
import sys
import time
import json
import shutil
import signal
import traceback
from pathlib import Path

# Force colony identity BEFORE importing core.config
os.environ["REEF_COLONY"] = "n1_darwin"

from core.config import (
    STATE_ROOT, CHAMPION_FILE, REPORT_FILE, HISTORY_FILE, VIZ_HTML
)
from core.engine.world3d import World3D
from core.engine.selection import rank, pick_survivors
from core.engine.reproduction import reproduce
from core.viz import chart3d
from .config import (
    DEFAULT_POP, DEFAULT_TICKS, DEFAULT_GENS, DEFAULT_SEED,
    SYMBOLS, CYCLE_PAUSE_SEC, COLONY_NAME,
)

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    print(f"[{COLONY_NAME}] signal {signum} received — stopping after current cycle")


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _clear_live_state():
    """Wipe live state/ between cycles but keep runs_*/ archives intact."""
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
                 "creatures.jsonl", "tail_bank.jsonl", "reef3d.html"):
        src = STATE_ROOT / name
        if src.exists():
            try:
                shutil.copy2(src, sym_arc / name)
            except Exception as e:
                print(f"[{COLONY_NAME}] archive err {name}: {e}")
    return arc


def run_one_cycle(symbol: str, pop: int, ticks: int, gens: int,
                  seed: int | None) -> dict:
    """One episode set over `symbol`. Returns the final report dict."""
    print(f"[{COLONY_NAME}] starting cycle sym={symbol} pop={pop} "
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
            ranked = rank(evals)
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
                print(f"[{COLONY_NAME}] cycle #{cycle_i} {sym}: "
                      f"fit={champ.get('fitness', 0):+.3f} "
                      f"trades={champ.get('metrics', {}).get('n_trades', 0)}")
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

    print(f"[{COLONY_NAME}] stopped cleanly after {cycle_i} cycles")


if __name__ == "__main__":
    main()
