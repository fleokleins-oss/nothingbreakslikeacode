# Reef Citadel — CLAUDE.md

> Operational manual for Claude Code (and you) when working inside this repo.
> Read this before patching anything.

## Mental model

Two colonies breed in parallel on the same substrate:

```
                        ┌─── N1 Darwin ───┐   pure fitness, no gauntlet
        shared core ────┤                 │   champion = top-fit of generation
   (creatures, market,  ├─── N2 Popper ───┤   fitness + 5-gate gauntlet required
    execution, joias,   │                 │   champion = top-fit with passed=True
      tail_bank, viz)   └─── N3 Institut ─┘   VPS-only, revalidates inbox
                                              strictest gates (60 trades / Calmar 3.0)
```

A genome that **wins in N1 but fails in N2** is likely over-fit sorcery. A genome that **wins in both** is a candidate. A genome that **also survives N3** is a real edge.

## Paths

```
REEF_STATE_ROOT (= ~/reef_citadel/.state by default)
├── n1_darwin/
│   ├── champion.json      # current best in memory
│   ├── report.json        # full report of last run
│   ├── creatures.jsonl    # all creatures last gen (for viz)
│   ├── history.jsonl      # per-gen stats (append)
│   ├── tail_bank.jsonl    # death/DD events with genomes
│   ├── reef3d.html        # last-colony 3D viz
│   ├── runs_<TS>/         # archived cycles
│   │   └── state_<SYM>/
│   ├── joias/
│   │   ├── emperors.json
│   │   ├── kings.jsonl
│   │   ├── females.json
│   │   └── lineage.jsonl
│   └── female_seed/       # hints for next-cycle seeding
├── n2_popper/             # (same structure + gauntlet.jsonl)
│   └── gauntlet.jsonl     # every gauntlet attempt logged (audit)
├── n3_institutional/
│   ├── inbox/             # <-- rsync drop here from notebook
│   │   └── processed/
│   ├── verdicts.jsonl
│   └── champion.json      # revalidated winners
└── reef3d_unified.html    # combined viz, N1+N2+N3 in one scene
```

## Systemd (notebook)

```
reef-n1.service           # colony N1 loop, CPUQuota=40%
reef-n2.service           # colony N2 loop, CPUQuota=40%
reef-joias.service        # hourly emperor orchestration
reef-viz.service          # unified viz, regenerated every 10min
reef-watchboard.service   # FastAPI :8090
```

Total CPUQuota budget on 4-core notebook:
- N1 + N2 = 80% (two cores worth, 3rd and 4th free for OS + misc)
- joias + viz + watchboard = 10%+5%+5% = 20% shared

## Systemd (VPS, via install.sh --vps)

```
reef-n3.service           # validate inbox, CPUQuota=20%
reef-viz.service          # same viz (reads VPS-side state only)
reef-watchboard.service   # same dashboard (bind 0.0.0.0 to expose via Tailscale)
```

## Daily ops

**Check health** (15s):
```bash
systemctl --user status reef-n1 reef-n2 reef-joias reef-viz reef-watchboard
```

**See dashboard**:
```
http://127.0.0.1:8090
```

**Watch live** (N1):
```bash
journalctl --user -u reef-n1 -f
```

**Inspect last champion**:
```bash
jq . ~/reef_citadel/.state/n1_darwin/champion.json
jq . ~/reef_citadel/.state/n2_popper/champion.json
```

**Force one joias cycle now**:
```bash
cd ~/reef_citadel
REEF_COLONY=n1_darwin python3 -m core.joias.orchestrator
REEF_COLONY=n2_popper REEF_JOIAS_REQUIRE_GAUNTLET=1 python3 -m core.joias.orchestrator
```

**Render viz manually**:
```bash
cd ~/reef_citadel
python3 -m reef3d.render
# open .state/reef3d_unified.html
```

## The Galápagos test (after ≥14 days)

After both colonies have trained a few days, run:

```bash
cd ~/reef_citadel
python3 scripts/compare_n1_n2.py --oos-symbol BTCUSDT --ticks 50000
```

This picks each colony's best archived champion and pits them on data they've never seen. The **winner is whichever has lower returns variance with positive final capital**. That is the mathematical definition of "edge genuinely transfers" — not "higher fitness in training".

If the verdict is TIE/LOSS after 14 days, the arch doesn't work and you redesign — not patch.

## How to kill a colony that's gone bad

Imagine N2 starts producing garbage (e.g., a bug in gauntlet lets junk through). To stop ONLY N2:

```bash
systemctl --user stop reef-n2
systemctl --user disable reef-n2
# N1 keeps running normally. VPS N3 keeps receiving from N1.
```

## When to add a new colony (N4, N5...)

You don't, yet. The Galápagos test rigorously compares 2-3 colonies. More colonies = noise > signal.

## Invariants to preserve when patching

1. **Fees live only in `core/execution/fees.py`.** The test `test_core.py::TestFeesUnique` enforces this. If you want to add a fee tier, add it there.
2. **State is colony-scoped.** Never hardcode a path to `n1_darwin/` anywhere except N1's own run.py.
3. **Joias reads champions, not raw creatures.** Champions are reports; creatures are transitory. This is the correct semantics.
4. **N3 does NOT evolve its own population.** It revalidates inbox. Changing this would turn VPS into a full trainer and the architecture loses meaning.
5. **Gauntlet thresholds MUST be harder from N1 → N2 → N3.** If they ever invert, comparison breaks.

## Common failure modes (diagnosis)

| Symptom | Likely cause | Fix |
|---|---|---|
| `no champions found` in joias | Early run, not enough cycles yet | Wait. First champion appears after cycle 1 of a colony completes. |
| N2 `gauntlet_passed: false` forever | Thresholds too hard for your data | Lower `N2_MIN_TRADES` or widen data window. |
| Viz HTML empty / black | No creatures.jsonl, or trajectories empty | Creatures didn't trade at all. Look at champion n_trades. |
| `OSError: cannot allocate memory` | Pop * ticks * creatures too big | Reduce `REEF_POP` or `REEF_TICKS`. |
| `No such file: apex_data/SYMBOL` | Missing data for symbol | Engine falls back to synthetic — but remove symbol from `REEF_SYMBOLS` to avoid confusion. |
| Watchboard returns 404 on `/reef3d` | reef-viz service not yet generated file | `systemctl --user start reef-viz` or run `python3 -m reef3d.render` manually. |
| Two colonies clobber each other's state | `REEF_COLONY` not set in service file | Check systemd unit has `Environment=REEF_COLONY=nX_...` |

## Spiritual (the joias layer)

The 4 emperors / 3 jewels / 2 females are not decoration. They're a constraint structure:

- **4 emperors** force regime coverage. A reef with only a `revert` emperor has no defense in a trending market.
- **3 jewels** (Simons / Feynman / Livermore) force tri-dimensional edge: risk-controlled + execution-aware + directionally right. Miss any, no coronation.
- **2 females** (Memoria / Caos) force continual diversity: Memoria mutates existing emperors (stable drift), Caos injects randomness (explore space).

The orchestrator rewrites `female_seed/*.json` on trigger events (vacant throne, stagnation, severe tail event). The engine's next cycle CAN optionally consume those seeds to bias its initial genome pool — that integration is the `female_seed/` directory, already wired in the orchestrator side but not yet read by engines (a planned 10-line patch in `world3d.py` once you decide the seeding policy you want).

## Don't patch these files without understanding

- `core/execution/fees.py` — single source of truth. Changes break everything.
- `core/creatures/creature.py::_open/_close` — fee accounting is sharp. Double-fee bugs hide here.
- `colonies/n2_popper/gates.py::run_gauntlet` — if you add a gate, remember the test suite expects 5.
- `core/joias/hierarchy.py::TRONOS` — 4 is the constant. Adding a 5th breaks emperor allocation.

## Emergency full reset

```bash
# STOP everything
systemctl --user stop reef-n1 reef-n2 reef-joias reef-viz reef-watchboard

# Wipe state (KEEP code, KEEP archived runs_*)
rm -rf ~/reef_citadel/.state/n1_darwin/champion.json
rm -rf ~/reef_citadel/.state/n1_darwin/creatures.jsonl
rm -rf ~/reef_citadel/.state/n1_darwin/tail_bank.jsonl
# ... (same for n2_popper)

# Restart
systemctl --user start reef-n1 reef-n2
```

Archived runs_*/ are preserved because they're evidence, not noise.

---

*Quando o trono vaga, Memória muta — quando o tempo congela, Caos visita.*
