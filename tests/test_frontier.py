from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.frontier import frontier


class FrontierTests(unittest.TestCase):
    def test_keeps_incomparable_points(self):
        points = [dict(id="base", r_time=1, r_memory=1),
                  dict(id="fast", r_time=.7, r_memory=1.1),
                  dict(id="small", r_time=1.1, r_memory=.6),
                  dict(id="bad", r_time=1.2, r_memory=1.2)]
        result = {point["id"]: point for point in frontier(points)}
        self.assertTrue(all(result[name]["pareto"] for name in ("base", "fast", "small")))
        self.assertFalse(result["bad"]["pareto"])
        self.assertIn("base", result["bad"]["dominated_by"])


if __name__ == "__main__":
    unittest.main()
