"""Core invariants — genes, fees uniqueness, tail_penalty, distance."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Put the package parent on sys.path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# Isolated test state dir (prevents polluting real STATE_ROOT)
os.environ["REEF_STATE_ROOT"] = tempfile.mkdtemp(prefix="reef_tests_")
os.environ.setdefault("REEF_COLONY", "test_core")


class TestConfig(unittest.TestCase):
    def test_colony_isolation(self):
        from core.config import STATE_ROOT, COLONY
        self.assertEqual(COLONY, "test_core")
        self.assertTrue(str(STATE_ROOT).endswith("test_core"))
        self.assertTrue(STATE_ROOT.exists())

    def test_constants_coherent(self):
        from core.config import INITIAL_CAPITAL, DEATH_FRAC, KELLY_CAP
        self.assertEqual(INITIAL_CAPITAL, 100.0)
        self.assertGreater(DEATH_FRAC, 0.0)
        self.assertLess(DEATH_FRAC, 1.0)
        self.assertLessEqual(KELLY_CAP, 0.5)


class TestGenes(unittest.TestCase):
    def test_random_genome_has_all_bounds(self):
        from core.creatures.genes import random_genes, GENE_BOUNDS
        g = random_genes()
        for key in GENE_BOUNDS:
            self.assertIn(key, g)

    def test_mutation_stays_within_bounds(self):
        from core.creatures.genes import random_genes, mutate, GENE_BOUNDS
        g = random_genes()
        for _ in range(100):
            g = mutate(g, rate=1.0)
            for key, bound in GENE_BOUNDS.items():
                v = g[key]
                if isinstance(bound, list):
                    self.assertIn(v, bound)
                else:
                    lo, hi = bound
                    slack = (hi - lo) * 0.02
                    self.assertGreaterEqual(v, lo - slack)
                    self.assertLessEqual(v, hi + slack)

    def test_distance_symmetric_zero_for_identical(self):
        from core.creatures.genes import random_genes, normalized_distance
        g = random_genes()
        self.assertEqual(normalized_distance(g, g), 0.0)
        g2 = random_genes()
        self.assertAlmostEqual(
            normalized_distance(g, g2),
            normalized_distance(g2, g),
            places=10,
        )


class TestFeesUnique(unittest.TestCase):
    """ONE source of truth for fee rates (execution.fees)."""

    def test_no_other_module_references_fee_rates(self):
        import core
        pkg_root = Path(core.__file__).parent
        allowed = {
            "execution/fees.py",
            "execution/fills.py",
            "execution/simulator.py",
            "execution/__init__.py",
        }
        bad = []
        for p in pkg_root.rglob("*.py"):
            rel = p.relative_to(pkg_root).as_posix()
            if rel in allowed:
                continue
            txt = p.read_text(encoding="utf-8")
            for needle in ("FEE_BPS", "fee_bps"):
                if needle in txt:
                    bad.append(f"{rel}: contains '{needle}'")
        self.assertFalse(bad, "Fee rates must live only in execution/fees.py:\n" + "\n".join(bad))


class TestTailBank(unittest.TestCase):
    def test_empty_bank_zero_penalty(self):
        from core.engine.tail_bank import tail_penalty
        from core.creatures.genes import random_genes
        self.assertEqual(tail_penalty(random_genes(), bank=[]), 0.0)

    def test_identical_genome_bank_penalizes(self):
        from core.engine.tail_bank import tail_penalty
        from core.creatures.genes import random_genes
        g = random_genes()
        bank = [{"genes": g, "severity_decimal": 0.5, "type": "death"}
                for _ in range(15)]
        pen = tail_penalty(g, bank=bank)
        self.assertGreater(pen, 0.0)


class TestCreature(unittest.TestCase):
    def test_spawn_initial_state(self):
        from core.creatures.creature import Creature
        from core.creatures.genes import random_genome
        from core.config import INITIAL_CAPITAL
        c = Creature(genome=random_genome(0))
        self.assertEqual(c.capital, INITIAL_CAPITAL)
        self.assertTrue(c.alive)
        self.assertEqual(c.position_side, 0)


class TestJoiasHierarchy(unittest.TestCase):
    def test_four_tronos(self):
        from core.joias.hierarchy import TRONOS
        self.assertEqual(len(TRONOS), 4)
        self.assertEqual(set(TRONOS),
                         {"trend_up", "trend_down", "revert", "vol_spike"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
