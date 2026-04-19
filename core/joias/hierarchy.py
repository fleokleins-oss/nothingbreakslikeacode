"""
Joias — hierarquia 4 imperadores / 3 reis / 2 fêmeas sobre enc_v2.

4 IMPERADORES (1 por trono/regime): trend_up, trend_down, revert, vol_spike.
    Imortais até destronados por fitness superior no MESMO regime.
REIS (pool expansível): passaram 3 joias — risco, execução, direção.
    Sobem a imperador vencendo desafio.
2 FÊMEAS (stateful): parem ninhada em triggers — trono vago, estagnação, evento tail.
    Council-3 interno (Feynman/Livermore/Simons) aprova breeding.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional
import json

from ..config import STATE_ROOT

Regime = Literal["trend_up", "trend_down", "revert", "vol_spike"]
TRONOS: tuple[Regime, ...] = ("trend_up", "trend_down", "revert", "vol_spike")

# Per-colony joias state goes under <STATE_ROOT>/joias/
STATE = STATE_ROOT / "joias"
STATE.mkdir(parents=True, exist_ok=True)

EMPERORS_F = STATE / "emperors.json"
KINGS_F    = STATE / "kings.jsonl"
FEMALES_F  = STATE / "females.json"
NURSERY_F  = STATE / "nursery.jsonl"
LINEAGE_F  = STATE / "lineage.jsonl"

# 3 joias dos Reis — thresholds
JOIA_RISCO_KELLY_MAX    = 0.25   # size_frac no genoma ≤ 0.25
JOIA_RISCO_SURVIVAL_MIN = 0.80   # survival_factor ≥ 0.80
JOIA_EXECUCAO_DRAG_MAX  = 0.02   # fees + slippage < 2% do capital
JOIA_DIRECAO_WINRATE    = 0.50   # win rate > 50% nos trades não-nulos
JOIA_DIRECAO_MIN_TRADES = 30     # statistical significance (9d of data = 3.3 trades/day)

# Fêmeas — triggers
STAGNATION_GENS = 5              # trono sem novo desafiante por N gens → trigger
TAIL_EVENT_SEVERITY = 0.50       # tail_bank event com severity ≥ isto → trigger


@dataclass
class Emperor:
    regime: Regime
    genome_id: str
    genes: dict
    fitness: float
    crowned_at: int             # gen
    challenges_survived: int = 0
    components: dict = field(default_factory=dict)


@dataclass
class King:
    genome_id: str
    genes: dict
    fitness: float
    joia_risco: bool
    joia_execucao: bool
    joia_direcao: bool
    components: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


@dataclass
class Female:
    name: str   # "Memoria" | "Caos"
    last_birth_gen: int = -1
    births_total: int = 0
    accepted_by_council: int = 0
    rejected_by_council: int = 0


def check_joia_risco(creature) -> bool:
    """Joia de Simons — algoritmo não-suicida."""
    kelly_ok = creature.genome.genes.get("size_frac", 1.0) <= JOIA_RISCO_KELLY_MAX
    survival = creature.components.get("survival_factor", 0.0)
    return kelly_ok and survival >= JOIA_RISCO_SURVIVAL_MIN


def check_joia_execucao(creature) -> bool:
    """Joia de Feynman — entende o custo do trade."""
    drag = creature.metrics.get("exec_fees_frac", 1.0) + creature.metrics.get("exec_slippage_frac", 1.0)
    return drag < JOIA_EXECUCAO_DRAG_MAX


def check_joia_direcao(creature) -> bool:
    """Joia de Livermore — timing correto mais que metade das vezes.
    Requer N ≥ 30 trades (significância estatística em 9d de data).
    """
    n_trades = creature.metrics.get("n_trades", 0)
    if n_trades < JOIA_DIRECAO_MIN_TRADES:
        return False
    return creature.metrics.get("win_rate", 0.0) >= JOIA_DIRECAO_WINRATE


def dominant_regime(creature) -> Optional[Regime]:
    """Qual regime a criatura mais explorou com trades.
    Prioridade: regimes_seen REAL (onde tradou) > regime_pref (onde queria tradar).
    """
    action = creature.genome.genes.get("action_bias", "both")
    regimes_seen = creature.metrics.get("regimes_seen", []) or []
    # 1. Fonte de verdade: regimes onde efetivamente tradou
    if len(regimes_seen) == 1:
        r = regimes_seen[0]
        if r in TRONOS:
            return r
        if r == "trend":
            return "trend_down" if action == "short_only" else "trend_up"
        if r == "revert":
            return "revert"
        if r == "breakout":
            return "vol_spike"
    # 2. Fallback: preferência do genoma
    pref = creature.genome.genes.get("regime_pref", None)
    if pref in TRONOS:
        return pref
    if pref == "trend":
        return "trend_down" if action == "short_only" else "trend_up"
    if pref == "revert":
        return "revert"
    if pref == "breakout":
        return "vol_spike"
    return None  # "any", "chop", unknown — não tem trono dedicado


def council_approves(mother: Female, child_genes: dict, parents: list) -> tuple[bool, str]:
    """Council-3 veta se filho é redundante ou violador de invariantes."""
    from ..creatures.genes import GENE_BOUNDS
    # Feynman: entende o child? (genes dentro dos bounds)
    for k, b in GENE_BOUNDS.items():
        if k not in child_genes:
            return False, f"feynman: missing {k}"
    # Livermore: timing distinto dos pais?
    if parents:
        parent_lookbacks = [p.get("trend_lookback", 0) for p in parents]
        if all(abs(child_genes.get("trend_lookback", 0) - pl) < 5 for pl in parent_lookbacks):
            return False, "livermore: timing idêntico aos pais"
    # Simons: tamanho sob controle (Kelly cap)
    if child_genes.get("size_frac", 1.0) > JOIA_RISCO_KELLY_MAX:
        return False, "simons: size_frac > kelly_cap"
    return True, "ok"


def load_emperors() -> dict:
    if not EMPERORS_F.exists():
        return {t: None for t in TRONOS}
    raw = json.load(open(EMPERORS_F))
    return {t: Emperor(**raw[t]) if raw.get(t) else None for t in TRONOS}


def save_emperors(emps: dict):
    raw = {t: asdict(e) if e else None for t, e in emps.items()}
    EMPERORS_F.write_text(json.dumps(raw, indent=2, default=str))


def load_females() -> list:
    if not FEMALES_F.exists():
        return [Female(name="Memoria"), Female(name="Caos")]
    raw = json.load(open(FEMALES_F))
    return [Female(**f) for f in raw]


def save_females(fs: list):
    FEMALES_F.write_text(json.dumps([asdict(f) for f in fs], indent=2, default=str))
