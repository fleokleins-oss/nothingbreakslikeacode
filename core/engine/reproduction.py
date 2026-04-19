"""
Reproduction — produce offspring genomes from a ranked list of parents.
Gene operations live in creatures/genes.py; this module only composes them.
"""
from __future__ import annotations
import random

from ..creatures.genes import Genome, random_genes, mutate, crossover
from .selection import select_parents


def reproduce(survivors: list[dict], pop_size: int, gen: int,
              elite_frac: float = 0.15,
              random_frac: float = 0.10,
              mutation_rate: float = 0.25,
              rng: random.Random | None = None) -> list[Genome]:
    """
    Build a population for the next generation.

    Composition:
      - elite_frac: copy top survivors as-is (genetic backbone)
      - random_frac: fresh random genomes (diversity injection)
      - rest: crossover(parent_a, parent_b) + mutate
    """
    r = rng or random
    if not survivors:
        return [Genome(genes=random_genes(r), gen_born=gen) for _ in range(pop_size)]

    elites_n = max(1, int(pop_size * elite_frac))
    random_n = max(0, int(pop_size * random_frac))
    offspring_n = max(0, pop_size - elites_n - random_n)

    next_pop: list[Genome] = []
    for e in survivors[:elites_n]:
        next_pop.append(Genome(
            genes=dict(e["creature"].genome.genes),
            parent_ids=[e["creature"].genome.genome_id],
            gen_born=gen,
        ))
    for _ in range(offspring_n):
        parents = select_parents(survivors, k=2, rng=r)
        if len(parents) < 2:
            parents = parents * 2
        a, b = parents[0]["creature"].genome, parents[1]["creature"].genome
        child_genes = mutate(crossover(a.genes, b.genes, rng=r), rate=mutation_rate, rng=r)
        next_pop.append(Genome(
            genes=child_genes,
            parent_ids=[a.genome_id, b.genome_id],
            gen_born=gen,
        ))
    for _ in range(random_n):
        next_pop.append(Genome(genes=random_genes(r), gen_born=gen))

    return next_pop
