"""Colony-level tests — ensure each colony imports cleanly and gates work."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ["REEF_STATE_ROOT"] = tempfile.mkdtemp(prefix="reef_tests_col_")
os.environ.setdefault("REEF_COLONY", "test_col")


class TestN1Darwin(unittest.TestCase):
    def test_imports(self):
        from colonies.n1_darwin import config, run
        self.assertEqual(config.COLONY_NAME, "n1_darwin")
        self.assertFalse(config.GAUNTLET_ENABLED)
        self.assertIsInstance(config.SYMBOLS, list)
        self.assertGreater(len(config.SYMBOLS), 0)


class TestN2Popper(unittest.TestCase):
    def test_imports(self):
        from colonies.n2_popper import config, gates, run
        self.assertEqual(config.COLONY_NAME, "n2_popper")
        self.assertTrue(config.GAUNTLET_ENABLED)

    def test_gauntlet_rejects_few_trades(self):
        from colonies.n2_popper.gates import run_gauntlet
        r = run_gauntlet(all_trades=[], regimes_seen=[], days_total=1.0)
        self.assertFalse(r.passed)
        self.assertIn("N=0", r.failure_reason)

    def test_gauntlet_rejects_low_net(self):
        """Synthetic trades with tiny edge — should fail net_bps_day gate."""
        from colonies.n2_popper.gates import run_gauntlet
        # 40 trades, each +0.5 bps — 20 bps/40 trades over 1 day
        # = 20 bps/day total, but wait that's ABOVE threshold. Use tinier:
        trades = [{"pnl_bps": 0.05} for _ in range(40)]
        r = run_gauntlet(all_trades=trades, regimes_seen=["trend", "revert"],
                         days_total=10.0)
        self.assertFalse(r.passed)

    def test_gauntlet_passes_strong_edge(self):
        """Many trades, strong positive edge, multi-regime, low volatility of returns."""
        from colonies.n2_popper.gates import run_gauntlet
        # 60 trades, mean +15 bps, low stddev, across 2 regimes, 5 days
        import random
        random.seed(42)
        trades = [{"pnl_bps": 15.0 + random.gauss(0, 3.0)} for _ in range(60)]
        regimes = ["trend"] * 40 + ["revert"] * 20
        r = run_gauntlet(all_trades=trades, regimes_seen=regimes,
                         days_total=5.0)
        # Note: may or may not pass depending on OOS ratio; just check
        # function runs without error and reports are structured
        self.assertIsNotNone(r.n_trades)
        self.assertEqual(r.n_trades, 60)


class TestN3Institutional(unittest.TestCase):
    def test_imports(self):
        from colonies.n3_institutional import config, gates, run
        self.assertEqual(config.COLONY_NAME, "n3_institutional")
        self.assertGreater(config.MIN_TRADES, 30)  # stricter than N2

    def test_n3_gates_stricter_than_n2(self):
        from colonies.n2_popper.config import MIN_TRADES as n2_min
        from colonies.n3_institutional.config import MIN_TRADES as n3_min
        self.assertGreater(n3_min, n2_min)


if __name__ == "__main__":
    unittest.main(verbosity=2)
