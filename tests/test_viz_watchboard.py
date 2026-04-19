"""Viz + watchboard — import smoke tests."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ["REEF_STATE_ROOT"] = tempfile.mkdtemp(prefix="reef_tests_viz_")
os.environ.setdefault("REEF_COLONY", "test_viz")


class TestReef3DRender(unittest.TestCase):
    def test_render_empty_produces_html(self):
        from reef3d.render import render, STATE_ROOT_ALL
        out = STATE_ROOT_ALL / "reef3d_unified.html"
        path = render(output=out)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 500)
        # Should contain the title string
        content = path.read_text()
        self.assertIn("REEF CITADEL", content)


class TestWatchboard(unittest.TestCase):
    def test_status_works_without_state(self):
        from watchboard.server import status
        s = status()
        # All 3 colonies should be keys, even if empty
        self.assertIn("n1_darwin", s)
        self.assertIn("n2_popper", s)
        self.assertIn("n3_institutional", s)

    def test_champions_works_without_state(self):
        from watchboard.server import champions
        c = champions()
        # None is OK for colonies with no champion.json
        self.assertIsInstance(c, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
