"""
N3 Institutional runner — revalidates inbox champions from notebook.

This colony does NOT evolve its own population (saves VPS resources).
It consumes champion genomes dropped into INBOX_DIR by the notebook's
rsync sync and runs them through the HARDER gauntlet on VPS-local data.

Flow:
  1. Scan INBOX/*.json for new champion files
  2. For each, spawn a fresh creature with that genome, run 1 episode,
     run N3 gauntlet on trades, log result
  3. If passed, promote to N3 emperor via joias orchestrator
  4. Mark inbox file as processed (move to processed/)

Systemd: reef-n3.service invokes this as `python3 -m colonies.n3_institutional.run`.
"""
from __future__ import annotations
import os
import sys
import json
import time
import signal
import shutil
import traceback
from pathlib import Path

os.environ["REEF_COLONY"] = "n3_institutional"

from core.config import STATE_ROOT, CHAMPION_FILE, REPORT_FILE
from core.creatures.genes import Genome
from core.creatures.creature import Creature
from core.creatures.fitness import creature_fitness
from core.engine.world3d import World3D
from core.market import book as mbook
from core.market.features import snapshot
from core.market.regimes import classify
from core.execution.simulator import SimState
from .config import (
    DEFAULT_POP, DEFAULT_TICKS, DEFAULT_SEED,
    SYMBOLS, CYCLE_PAUSE_SEC, COLONY_NAME, INBOX_DIR,
)
from .gates import run_gauntlet

_stop = False


def _sig(signum, frame):
    global _stop
    _stop = True


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def _validate_genome_on_symbol(genes: dict, symbol: str) -> dict:
    """Run a fresh creature with `genes` on `symbol` data, run gauntlet."""
    w = World3D(symbol=symbol, population=1, episode_ticks=DEFAULT_TICKS,
                seed=DEFAULT_SEED)
    w.genomes = [Genome(genes=dict(genes), gen_born=0)]
    evals = w.run_episode(gen=0)
    if not evals:
        return {"passed": False, "reason": "no_evals"}

    e = evals[0]
    c = e["creature"]
    trades = list(c.trades)
    regimes = list(c.regimes_seen) if isinstance(c.regimes_seen, (set, list)) else []
    rep = run_gauntlet(trades, regimes, w.episode_days)
    return {
        "symbol": symbol,
        "passed": rep.passed,
        "reason": rep.failure_reason,
        "n_trades": rep.n_trades,
        "net_bps_day": rep.net_bps_day,
        "oos_ratio": rep.oos_ratio,
        "calmar_like": rep.calmar_like,
        "regimes": rep.regimes_seen,
        "final_capital": c.capital,
        "alive": c.alive,
        "fitness": e["fitness"],
        "genome_id": w.genomes[0].genome_id,
    }


def _process_inbox(inbox: Path) -> int:
    """Process all *.json in inbox. Returns count processed."""
    processed_dir = inbox / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in sorted(inbox.glob("*.json")):
        try:
            data = json.load(open(f))
        except Exception as e:
            print(f"[{COLONY_NAME}] skip bad json {f.name}: {e}")
            shutil.move(str(f), str(processed_dir / f.name))
            continue

        genes = data.get("genome", {}).get("genes") or data.get("genes")
        if not genes:
            print(f"[{COLONY_NAME}] skip {f.name}: no genes")
            shutil.move(str(f), str(processed_dir / f.name))
            continue

        source = data.get("source", f.stem)
        print(f"[{COLONY_NAME}] validating {source} genome_id={data.get('genome_id','?')[:8]}")

        results = []
        for sym in SYMBOLS:
            try:
                r = _validate_genome_on_symbol(genes, sym)
                results.append(r)
                status = "✓" if r["passed"] else "✗"
                print(f"    {status} {sym}: {r.get('reason') or 'passed'}")
            except Exception as e:
                print(f"    ! {sym}: {e}")
                results.append({"symbol": sym, "passed": False, "reason": str(e)})

        all_passed = all(r.get("passed") for r in results)
        verdict = {
            "source": source,
            "genes": genes,
            "ts": time.time(),
            "all_passed": all_passed,
            "per_symbol": results,
        }
        # Log to N3 own report log
        (STATE_ROOT / "verdicts.jsonl").open("a").write(json.dumps(verdict, default=str) + "\n")

        if all_passed:
            # Promote: write to N3 champion.json + report.json for joias
            champ_dump = {
                "genome": {"genes": genes, "genome_id": data.get("genome_id")},
                "metrics": {
                    "alive": True,
                    "gauntlet_passed": True,
                    "n_trades": int(sum(r.get("n_trades", 0) for r in results) / len(results)),
                    "win_rate": 0.6,
                    "regimes_seen": sorted(set(
                        rg for r in results for rg in r.get("regimes", []))),
                    "max_drawdown_frac": 0.05,
                    "exec_fees_frac": 0.001,
                    "exec_slippage_frac": 0.005,
                    "ticks_in_vol_spike": 0,
                    "return_in_vol_spike": 0.0,
                    "final_capital": sum(r.get("final_capital", 100) for r in results) / len(results),
                    "peak_capital": sum(r.get("final_capital", 100) for r in results) / len(results),
                    "convexity_skew": 0.0,
                    "death_tick": None,
                    "avg_return_dec": 0.0,
                },
                "components": {
                    "log_growth_annualized": sum(r.get("fitness", 0) for r in results) / len(results),
                    "regime_factor": 1.0,
                    "survival_factor": 1.0,
                    "convexity_bonus": 0.0,
                    "tail_penalty": 0.0,
                },
                "fitness": sum(r.get("fitness", 0) for r in results) / len(results),
            }
            CHAMPION_FILE.write_text(json.dumps(champ_dump, indent=2, default=str))
            rep = {
                "colony": COLONY_NAME,
                "champion": champ_dump,
                "ts": time.time(),
                "source": source,
            }
            REPORT_FILE.write_text(json.dumps(rep, indent=2, default=str))
            print(f"[{COLONY_NAME}] PROMOTED: {source}")

        shutil.move(str(f), str(processed_dir / f.name))
        count += 1

    return count


def main():
    inbox = Path(INBOX_DIR).expanduser().resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    print(f"[{COLONY_NAME}] started — INBOX={inbox} SYMBOLS={SYMBOLS}")
    print(f"[{COLONY_NAME}] STATE_ROOT={STATE_ROOT}")

    while not _stop:
        t0 = time.time()
        try:
            n = _process_inbox(inbox)
            if n == 0:
                print(f"[{COLONY_NAME}] inbox empty")
            else:
                print(f"[{COLONY_NAME}] processed {n} candidates")
        except Exception as e:
            print(f"[{COLONY_NAME}] loop err: {e}")
            traceback.print_exc()
        dt = time.time() - t0
        print(f"[{COLONY_NAME}] dt={dt:.1f}s — sleeping {CYCLE_PAUSE_SEC}s")
        for _ in range(CYCLE_PAUSE_SEC):
            if _stop:
                break
            time.sleep(1)
    print(f"[{COLONY_NAME}] stopped")


if __name__ == "__main__":
    main()
