# Reef Citadel

Two evolutionary colonies of tick-by-tick trading creatures, competing on the same data substrate to reveal which selection paradigm produces genuinely robust edge.

## TL;DR

```bash
cd reef_citadel
bash install.sh                    # validates + tests + installs systemd
systemctl --user enable --now reef-n1 reef-n2 reef-joias reef-viz reef-watchboard
open http://127.0.0.1:8090         # dashboard
```

After 14+ days of parallel training:

```bash
python3 scripts/compare_n1_n2.py --oos-symbol BTCUSDT
```

Winner is whichever colony's champion has lower PnL variance on unseen data.

## Architecture

```
┌───────── core/ ──────────┐
│  creatures, market,      │   tick-by-tick engine, 3D trajectories,
│  execution, engine,      │   4 orthogonal feature channels, tail bank,
│  joias, viz              │   4 emperors / 3 jewels / 2 females
└──────┬───────────────────┘
       │
       ├──── colonies/n1_darwin/           Pure fitness. No gauntlet.
       │     └── champion = top_fit(gen)    Darwinian survival.
       │
       ├──── colonies/n2_popper/           Fitness + 5 gauntlet gates.
       │     └── gates.py                   Popperian falsifiability.
       │         (MIN_TRADES, Calmar,
       │          OOS, regimes, edge)
       │
       └──── colonies/n3_institutional/    VPS-only. Revalidates inbox.
             └── Harder gates (60/3.0/0.7) Institutional grade.
```

## Why two colonies

Most GA systems overfit training data invisibly — the population concentrates around genomes that happened to work, without mechanism to reject luck. Each colony tests a different hypothesis about what "good" means:

- **N1 (Darwinian)** — does fitness-based selection alone produce robust edge? Control group.
- **N2 (Popperian)** — does adding falsifiability gates before coronation produce *more* robust edge than raw fitness?

After enough training, run both champions on data neither saw. Lower variance wins. The answer is discoverable, not assumed.

## Requirements

```
python3 (tested with 3.14)
numpy
pandas
pyarrow
fastapi       # watchboard only
uvicorn       # watchboard only
```

Install tested on Arch/EndeavourOS; should work on any modern Linux with systemd user session.

## Data

Expects parquet trade files at `$REEF_DATA_ROOT/<SYMBOL>/trades_*.parquet`. Defaults to `~/apex_data`. If a symbol has no data, the engine transparently falls back to synthetic tape (clearly marked in logs).

## Colors in the unified 3D viz

- **N1 Darwin**:        green
- **N2 Popper**:        blue
- **N3 Institutional**: gold

Dead creatures fade. Champions (top-1 per colony) have a cone marker above their final position.

## Operational runs vs backtests

Every colony runs a continuous cycle:
1. Pick next symbol from rotation
2. Train N gens
3. Archive to `runs_<timestamp>/`
4. Sleep briefly
5. Next cycle

Archives grow. Use `du -sh .state/` periodically to watch size; each archive is ~1-5MB.

## Deleting junk

Archived cycles before a breakthrough can be pruned:

```bash
# keep the last 20 runs per colony, delete older
for d in ~/reef_citadel/.state/n{1,2}_*/runs_*; do
  echo $d
done | sort | head -n -20 | xargs -r rm -rf
```

## License

MIT. Use at your own risk. Trading involves risk of total loss.

## Files you'll actually edit

- `colonies/n1_darwin/config.py` — N1 tuning
- `colonies/n2_popper/config.py` — N2 tuning
- `core/creatures/genes.py::GENE_BOUNDS` — genome search space
- `core/creatures/actions.py::entry_signal` — entry logic

## Files you should probably NOT touch

- `core/execution/fees.py` — single source of truth
- `core/creatures/creature.py` — fee accounting is delicate
- `colonies/n2_popper/gates.py::run_gauntlet` — 5 gates are the product

## Docs

- `CLAUDE.md` — operational manual + invariants for maintainers
- `scripts/compare_n1_n2.py` — the Galápagos verdict tool
- `scripts/sync_to_vps.sh` — notebook → VPS champion sync

---

*Two colonies. One substrate. One question: what selects for real edge.*
