"""
Genome for creatures. Genes control *orthogonal* decision facets so the
selector cannot reward redundancy (signal correlation trap is prevented
architecturally: each gene drives a distinct feature channel).
"""
from __future__ import annotations
import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

# Each gene maps to ONE feature channel. No gene pair controls the same signal.
# - trend_lookback        → momentum / trend channel
# - mean_revert_zscore_k  → mean-reversion channel (independent)
# - vol_entry_min/max     → volatility regime channel
# - imbalance_trigger     → microstructure channel (book-side)
# - depth_pressure_limit  → liquidity/impact channel (Z-axis)
# - cooldown_ticks        → time channel
# - stop_frac / target_frac → risk shape (convexity)
# - size_frac             → exposure (capped by Kelly downstream)
# - regime_pref           → categorical filter over regimes
# - action_bias           → discrete posture (long/short/both)
GENE_BOUNDS: dict[str, Any] = {
    "trend_lookback":        (20, 300),
    "mean_revert_zscore_k":  (1.0, 4.0),
    "vol_entry_min":         (0.00001, 0.001),
    "vol_entry_max":         (0.001, 0.05),
    "imbalance_trigger":     (0.05, 0.6),
    "depth_pressure_limit":  (0.2, 2.5),    # abort if own-size/depth > this
    "cooldown_ticks":        (5, 30),
    "stop_frac":             (0.02, 0.10),  # decimal of entry
    "target_frac":           (0.04, 0.20),  # decimal of entry
    "size_frac":             (0.05, 0.25),   # fraction of capital, hard-capped at Kelly (JOIA_RISCO)
    "regime_pref":           ["trend", "revert", "breakout", "chop"],
    "action_bias":           ["long_only", "short_only", "both"],
}

# V668: weighted sampling for regime_pref so population matches the market.
# INJ diag showed 60% chop ticks; ADA ~55%. 40% weight on chop gives creatures
# a realistic shot at tracking the dominant regime. Applied in both
# random_genes() and mutate() so long-term drift doesn't wash it out.
REGIME_PREF_WEIGHTS = [0.20, 0.20, 0.20, 0.40]   # trend, revert, breakout, chop


def _sample_regime_pref(rng: random.Random | None = None) -> str:
    r = rng or random
    opts = GENE_BOUNDS["regime_pref"]
    return r.choices(opts, weights=REGIME_PREF_WEIGHTS, k=1)[0]


@dataclass
class Genome:
    genes: dict
    parent_ids: list[str] = field(default_factory=list)
    gen_born: int = 0

    @property
    def genome_id(self) -> str:
        s = "|".join(f"{k}={self.genes.get(k)}" for k in sorted(GENE_BOUNDS))
        return hashlib.md5(s.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {"genes": self.genes, "parent_ids": list(self.parent_ids),
                "gen_born": self.gen_born, "genome_id": self.genome_id}


def random_genes(rng: random.Random | None = None) -> dict:
    r = rng or random
    g: dict = {}
    for k, b in GENE_BOUNDS.items():
        if isinstance(b, list):
            g[k] = _sample_regime_pref(r) if k == "regime_pref" else r.choice(b)
        else:
            lo, hi = b
            if isinstance(lo, int):
                g[k] = r.randint(int(lo), int(hi))
            else:
                g[k] = r.uniform(float(lo), float(hi))
    _enforce_coherence(g)
    return g


def random_genome(gen: int = 0, rng: random.Random | None = None) -> Genome:
    return Genome(genes=random_genes(rng), gen_born=gen)


def mutate(genes: dict, rate: float = 0.25,
           rng: random.Random | None = None) -> dict:
    r = rng or random
    out = dict(genes)
    for k, b in GENE_BOUNDS.items():
        if r.random() > rate:
            continue
        if isinstance(b, list):
            out[k] = _sample_regime_pref(r) if k == "regime_pref" else r.choice(b)
        else:
            lo, hi = b
            v = out.get(k, lo)
            sigma = (hi - lo) * 0.15
            if isinstance(lo, int):
                v = int(v + r.gauss(0, sigma))
                out[k] = max(int(lo), min(int(hi), v))
            else:
                v = float(v) * (1.0 + r.gauss(0, 0.2))
                out[k] = max(float(lo), min(float(hi), v))
    _enforce_coherence(out)
    return out


def crossover(a: dict, b: dict,
              rng: random.Random | None = None) -> dict:
    r = rng or random
    child = {k: (a.get(k) if r.random() < 0.5 else b.get(k)) for k in GENE_BOUNDS}
    _enforce_coherence(child)
    return child


def _enforce_coherence(g: dict) -> None:
    """Keep dependent bounds consistent. Called after mutate/crossover/random."""
    if g.get("vol_entry_min", 0) >= g.get("vol_entry_max", 1):
        lo, hi = GENE_BOUNDS["vol_entry_max"]
        g["vol_entry_max"] = min(float(hi), g["vol_entry_min"] * 1.5)
    if g.get("target_frac", 0) <= g.get("stop_frac", 1):
        g["target_frac"] = min(GENE_BOUNDS["target_frac"][1],
                               g["stop_frac"] * 2.0)


def normalized_distance(a: dict, b: dict,
                        bounds: dict = GENE_BOUNDS) -> float:
    """Average per-gene distance, scaled to [0,1] per gene.
    Numeric: |a-b|/span clipped; categorical: 0 or 1."""
    if not a or not b:
        return float("inf")
    total, count = 0.0, 0
    for k, bd in bounds.items():
        if k not in a or k not in b:
            continue
        va, vb = a[k], b[k]
        if isinstance(bd, list):
            total += 0.0 if va == vb else 1.0
            count += 1
        else:
            lo, hi = bd
            span = float(hi - lo)
            if span <= 0:
                continue
            try:
                total += min(1.0, abs(float(va) - float(vb)) / span)
                count += 1
            except (TypeError, ValueError):
                continue
    return total / count if count else float("inf")
