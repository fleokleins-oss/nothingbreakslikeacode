"""
Joias Orchestrator — processa champions de UMA colônia e promove
imperadores/reis/fêmeas.

Design: cada colônia (n1_darwin, n2_popper, n3_institutional) tem seu
próprio state/ em STATE_ROOT/<colony>/, e as joias correm separadamente
por colônia. A promoção a imperador exige:
  N1: apenas fitness + 3 joias (risco/execução/direção)
  N2: fitness + 3 joias + gauntlet já passou
  N3: idem N2 mas thresholds mais duros

Fonte dos champions:
  STATE_ROOT/<colony>/report.json       (champion da run atual/última)
  STATE_ROOT/<colony>/runs_*/report.json (runs arquivadas, se existirem)
"""
from __future__ import annotations
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .hierarchy import (
    TRONOS, Emperor, King, Female,
    check_joia_risco, check_joia_execucao, check_joia_direcao,
    dominant_regime,
    load_emperors, save_emperors, load_females, save_females,
    KINGS_F, LINEAGE_F,
    STAGNATION_GENS, TAIL_EVENT_SEVERITY,
)
from ..config import STATE_ROOT, COLONY


class _Box:
    def __init__(self, d=None):
        if d:
            self.__dict__.update(d)

    def get(self, k, default=None):
        return self.__dict__.get(k, default)


def _creature_from_champion(champ: dict, source: str) -> _Box:
    c = _Box()
    c.genome = _Box()
    c.genome.genes = champ.get("genome", {}).get("genes", {})
    c.metrics = champ.get("metrics", {})
    c.components = champ.get("components", {})
    c.fitness = champ.get("fitness", 0.0)
    c.genome_id = champ.get("genome", {}).get("genome_id") or f"champ-{source}"
    c._source = source
    return c


def _collect_champions(colony_state: Path) -> list:
    champions = []
    live = colony_state / "report.json"
    if live.exists():
        try:
            rep = json.load(open(live))
            if rep.get("champion"):
                champions.append(_creature_from_champion(
                    rep["champion"], f"live:{rep.get('symbol', '?')}"))
        except Exception as e:
            print(f"[joias:{COLONY}] parse err {live}: {e}")

    for run_dir in sorted(colony_state.glob("runs_*")):
        for sym_state in sorted(run_dir.glob("state_*")):
            rep_f = sym_state / "report.json"
            if not rep_f.exists():
                continue
            try:
                rep = json.load(open(rep_f))
                if rep.get("champion"):
                    sym = rep.get("symbol", sym_state.name.replace("state_", ""))
                    champions.append(_creature_from_champion(
                        rep["champion"], f"{run_dir.name}:{sym}"))
            except Exception as e:
                print(f"[joias:{COLONY}] parse err {rep_f}: {e}")
        rep_f = run_dir / "report.json"
        if rep_f.exists():
            try:
                rep = json.load(open(rep_f))
                if rep.get("champion"):
                    champions.append(_creature_from_champion(
                        rep["champion"], run_dir.name))
            except Exception:
                pass
    return champions


def _qualify_kings(champions: Iterable, require_gauntlet: bool = False) -> list:
    kings = []
    for c in champions:
        if not c.metrics.get("alive", False):
            continue
        if require_gauntlet and not c.metrics.get("gauntlet_passed", False):
            continue
        jr = check_joia_risco(c)
        je = check_joia_execucao(c)
        jd = check_joia_direcao(c)
        if jr and je and jd:
            kings.append(King(
                genome_id=c.genome_id,
                genes=c.genome.genes,
                fitness=c.fitness,
                joia_risco=jr, joia_execucao=je, joia_direcao=jd,
                components=c.components,
                metrics=c.metrics,
            ))
    return kings


def coronation_cycle(gen: int, require_gauntlet: bool = False) -> dict:
    events = {
        "colony": COLONY, "gen": gen, "ts": int(time.time()),
        "require_gauntlet": require_gauntlet, "actions": [],
    }
    emperors = load_emperors()
    females = load_females()
    champions = _collect_champions(STATE_ROOT)
    events["nursery_size"] = len(champions)
    if not champions:
        events["actions"].append("no champions found")
        _append_lineage(events)
        print(f"[joias:{COLONY} gen={gen}] no champions")
        return events

    kings = _qualify_kings(champions, require_gauntlet=require_gauntlet)
    events["kings_qualified"] = len(kings)

    with open(KINGS_F, "a") as f:
        for k in kings:
            f.write(json.dumps({**asdict(k), "gen": gen, "colony": COLONY}) + "\n")

    for rei in kings:
        c_proxy = _Box()
        c_proxy.genome = _Box()
        c_proxy.genome.genes = rei.genes
        c_proxy.metrics = rei.metrics
        c_proxy.components = rei.components
        trono = dominant_regime(c_proxy)
        if trono is None:
            continue
        cur = emperors.get(trono)
        if cur is None or rei.fitness > cur.fitness:
            emperors[trono] = Emperor(
                regime=trono, genome_id=rei.genome_id, genes=rei.genes,
                fitness=rei.fitness, crowned_at=gen, components=rei.components,
            )
            events["actions"].append(
                f"coronation:{trono} → {rei.genome_id[:8]} fit={rei.fitness:.3f}")
        elif cur is not None:
            cur.challenges_survived += 1

    triggers = []
    for t in TRONOS:
        e = emperors[t]
        if e is None:
            triggers.append(f"vacant:{t}")
        elif gen - e.crowned_at >= STAGNATION_GENS:
            triggers.append(f"stagnant:{t}")

    tb = STATE_ROOT / "tail_bank.jsonl"
    if tb.exists():
        try:
            recent = [json.loads(l) for l in open(tb) if l.strip()][-20:]
            severe = [e for e in recent
                      if e.get("severity_decimal", 0) >= TAIL_EVENT_SEVERITY]
            if severe:
                triggers.append(f"tail_severe:{len(severe)}")
        except Exception:
            pass

    if triggers:
        events["female_triggers"] = triggers
        seed_dir = STATE_ROOT / "female_seed"
        seed_dir.mkdir(parents=True, exist_ok=True)
        memoria = [{"source": f"mut:{t}", "base_genes": e.genes}
                   for t, e in emperors.items() if e]
        (seed_dir / "memoria.json").write_text(json.dumps(memoria, indent=2))
        (seed_dir / "caos.json").write_text(json.dumps({"n_random": 20}))
        for f in females:
            f.last_birth_gen = gen
            f.births_total += 1

    save_emperors(emperors)
    save_females(females)
    _append_lineage(events)

    filled = sum(1 for e in emperors.values() if e)
    print(f"[joias:{COLONY} gen={gen}] champs={len(champions)} "
          f"kings={len(kings)} emperors={filled}/4 triggers={len(triggers)}")
    for a in events["actions"]:
        print(f"    → {a}")
    return events


def _append_lineage(events: dict) -> None:
    with open(LINEAGE_F, "a") as f:
        f.write(json.dumps(events, default=str) + "\n")


if __name__ == "__main__":
    import os
    gen = int(time.time() // 3600)
    require = os.getenv("REEF_JOIAS_REQUIRE_GAUNTLET", "0") == "1"
    coronation_cycle(gen, require_gauntlet=require)
