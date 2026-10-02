import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.export_h200_phases import rows_from_report, summarize


class PhaseExportTests(unittest.TestCase):
    def test_h200_receipt_keeps_proving_separate_from_process_time(self):
        report = json.loads((ROOT / "data/reports/h200-direct-2026-10-02.json").read_text())
        rows = rows_from_report(report)
        self.assertEqual(len(rows), 20)
        medians = {row["case_id"]: row for row in summarize(rows)}
        self.assertEqual(len(medians), 10)
        pie = medians["pie:15582797_15582797"]
        self.assertAlmostEqual(pie["proof_stage_s"], 1.2825594195)
        self.assertGreater(pie["process_s"], pie["proof_stage_s"])
        fold = medians["recursion:two-leaf-wrap-fold"]
        self.assertEqual(fold["proof_stage_s"], "")
        self.assertGreater(fold["fold_stage_s"], 2)
        pipeline = medians["pipeline:two-leaf-batch-integrated"]
        self.assertEqual(pipeline["proof_stage_s"], "")
        self.assertGreater(pipeline["cairo_leaf_proof_sum_s"], 0)


if __name__ == "__main__":
    unittest.main()
