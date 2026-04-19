#!/usr/bin/env python3
"""
compare_n1_n2.py — the OOS test that decides the Galápagos winner.

After N days of running N1 and N2 in parallel, run this to pick the best
champion from each and compare them on fresh, unseen data.

Usage:
    python3 scripts/compare_n1_n2.py [--days 14] [--oos-symbol BTCUSDT]

Picks:
  - N1 champion: highest fitness seen in archived runs_*/
  - N2 champion: highest fitness seen in archived runs_*/ WITH gauntlet_passed=True

Runs both on --oos-symbol (default BTCUSDT — must not be in N1/N2's training
rotation). Reports:
  - PnL
  - Sharpe
  - Max DD
  - OOS variance (primary winning criterion: LOWER variance wins)
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core.config import STATE_ROOT_ALL
from core.creatures.genes import Genome
from core.engine.world3d import World3D


def _find_best_archived_champion(colony: str,
                                 require_gauntlet: bool = False) -> dict | None:
    """Scan STATE_ROOT_ALL/<colony>/runs_*/state_*/champion.json for best."""
    root = STATE_ROOT_ALL / colony
    best = None
    best_fit = float("-inf")
    for champ_f in root.rglob("champion.json"):
        try:
            data = json.load(open(champ_f))
        except Exception:
            continue
        fit = data.get("fitness", float("-inf"))
        if require_gauntlet and not data.get("metrics", {}).get("gauntlet_passed"):
            continue
        if fit > best_fit:
            best_fit = fit
            best = data
            best["_source"] = str(champ_f.relative_to(STATE_ROOT_ALL))
    return best


def _validate_on_symbol(genes: dict, symbol: str, ticks: int, seed: int = 777) -> dict:
    """Run a single creature with `genes` on `symbol` data, report metrics."""
    w = World3D(symbol=symbol, population=1, episode_ticks=ticks, seed=seed)
    w.genomes = [Genome(genes=dict(genes), gen_born=0)]
    evals = w.run_episode(gen=0)
    if not evals:
        return {"error": "no evals"}
    e = evals[0]
    c = e["creature"]
    returns = [t.net_pnl_decimal for t in c.trades]
    if not returns:
        return {
            "fitness": e["fitness"],
            "n_trades": 0,
            "final_capital": c.capital,
            "alive": c.alive,
            "returns_var": None,
            "error": "no trades",
        }
    return {
        "fitness": e["fitness"],
        "n_trades": len(returns),
        "win_rate": sum(1 for r in returns if r > 0) / len(returns),
        "final_capital": c.capital,
        "alive": c.alive,
        "regimes": sorted(list(c.regimes_seen)),
        "returns_mean": statistics.mean(returns),
        "returns_var": statistics.variance(returns) if len(returns) > 1 else 0.0,
        "max_drawdown_frac": c.max_drawdown_frac,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-symbol", default="BTCUSDT",
                    help="Symbol to use for out-of-sample comparison (should NOT "
                         "be in N1/N2 training rotation)")
    ap.add_argument("--ticks", type=int, default=50000,
                    help="Episode length for OOS run")
    ap.add_argument("--days", type=int, default=14,
                    help="Informational: how many days of training preceded this")
    args = ap.parse_args()

    print(f"═══ N1 vs N2 — OOS comparison on {args.oos_symbol} ═══")
    print(f"(training days: {args.days}, oos ticks: {args.ticks})\n")

    n1 = _find_best_archived_champion("n1_darwin", require_gauntlet=False)
    n2 = _find_best_archived_champion("n2_popper", require_gauntlet=True)

    if not n1:
        print("✗ no N1 champion found"); return
    if not n2:
        print("✗ no N2 gauntlet-passed champion found — may need more training")
        return

    print(f"N1 source: {n1.get('_source')}")
    print(f"N1 training fitness: {n1.get('fitness'):+.4f}")
    print(f"N2 source: {n2.get('_source')}")
    print(f"N2 training fitness: {n2.get('fitness'):+.4f}")
    print()

    print("Running both on OOS data...")
    n1_res = _validate_on_symbol(n1["genome"]["genes"], args.oos_symbol, args.ticks)
    n2_res = _validate_on_symbol(n2["genome"]["genes"], args.oos_symbol, args.ticks)

    def pp(label, r):
        print(f"▸ {label}")
        for k in ("fitness", "n_trades", "final_capital", "max_drawdown_frac",
                 "returns_mean", "returns_var"):
            v = r.get(k)
            if v is None:
                continue
            if isinstance(v, float):
                print(f"  {k}: {v:.6f}")
            else:
                print(f"  {k}: {v}")
        if "regimes" in r:
            print(f"  regimes: {r['regimes']}")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        print()

    pp("N1 DARWIN on OOS", n1_res)
    pp("N2 POPPER on OOS", n2_res)

    print("═══ VERDICT ═══")
    # Primary criterion: LOWER returns variance wins (more consistent edge)
    # Tiebreak: higher final_capital
    v1 = n1_res.get("returns_var")
    v2 = n2_res.get("returns_var")
    c1 = n1_res.get("final_capital", 0)
    c2 = n2_res.get("final_capital", 0)

    if v1 is None or v2 is None:
        print("Inconclusive — one side made no trades on OOS tape")
    elif v1 < v2 and c1 >= 95:
        print(f"  N1 WINS (lower variance: {v1:.2e} vs {v2:.2e}, final_cap: {c1:.2f})")
    elif v2 < v1 and c2 >= 95:
        print(f"  N2 WINS (lower variance: {v2:.2e} vs {v1:.2e}, final_cap: {c2:.2f})")
    else:
        print(f"  TIE or LOSS — neither shows robust edge on OOS")
        print(f"  (N1 var={v1:.2e} cap={c1:.2f} | N2 var={v2:.2e} cap={c2:.2f})")


if __name__ == "__main__":
    main()
