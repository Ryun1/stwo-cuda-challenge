import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.score import InvalidRun, aggregate


class ScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "benchmark.json").read_text())
        raw = (ROOT / "fixtures/public-v1.json").read_bytes()
        cls.manifest = json.loads(raw)
        cls.manifest_hash = hashlib.sha256(raw).hexdigest()

    def evidence(self, time_ratio=1.0, memory_ratio=1.0):
        baseline = []
        candidate = []
        for case in self.manifest["cases"]:
            for round_id in range(3):
                common = dict(case_id=case["id"], round=round_id, verified=True,
                              protocol_ok=True, gpu_resident=True, statement_ok=True,
                              input_hash_ok=True)
                baseline.append(dict(common, time_s=10.0, peak_device_bytes=80_000_000_000,
                                     planned_arena_bytes=70_000_000_000))
                candidate.append(dict(common, time_s=10.0 * time_ratio,
                                      peak_device_bytes=int(80_000_000_000 * memory_ratio),
                                      planned_arena_bytes=70_000_000_000))
        return dict(schema="stwo-cuda-paired-evidence-v1", contract_epoch="h200-v1",
                    manifest_sha256=self.manifest_hash,
                    source_commit=self.config["sourceCommit"], baseline=baseline,
                    candidate=candidate)

    def score(self, evidence):
        return aggregate(self.manifest, evidence, self.manifest_hash, self.config)

    def test_baseline_is_one(self):
        result = self.score(self.evidence())
        self.assertAlmostEqual(result["r_time"], 1)
        self.assertAlmostEqual(result["r_memory"], 1)
        self.assertTrue(all(x["score"] == 1 for x in result["tracks"].values()))

    def test_equal_family_weights_and_product(self):
        evidence = self.evidence()
        only_pie = next(x["id"] for x in self.manifest["cases"] if x["family"] == "pie")
        for row in evidence["candidate"]:
            if row["case_id"] == only_pie:
                row["time_s"] /= 8
                row["peak_device_bytes"] //= 8
        result = self.score(evidence)
        self.assertAlmostEqual(result["r_time"], 8 ** (-1 / 18))
        self.assertAlmostEqual(result["r_memory"], 8 ** (-1 / 18))
        self.assertAlmostEqual(result["tracks"]["balanced"]["score"], 8 ** (1 / 18))

    def test_memory_win_with_slowdown_is_separate_track(self):
        result = self.score(self.evidence(time_ratio=1.3, memory_ratio=0.5))
        self.assertFalse(result["tracks"]["memory"]["eligible"])
        self.assertIsNone(result["tracks"]["memory"]["score"])
        self.assertFalse(result["tracks"]["balanced"]["eligible"])

    def test_latency_rejects_memory_regression(self):
        result = self.score(self.evidence(time_ratio=0.5, memory_ratio=1.11))
        self.assertFalse(result["tracks"]["latency"]["eligible"])
        self.assertTrue(result["tracks"]["balanced"]["eligible"])

    def test_missing_round_or_failed_proof_rejected(self):
        evidence = self.evidence()
        evidence["candidate"].pop()
        with self.assertRaises(InvalidRun):
            self.score(evidence)
        evidence = self.evidence()
        evidence["candidate"][0]["verified"] = False
        with self.assertRaises(InvalidRun):
            self.score(evidence)

    def test_oversized_arena_rejected(self):
        evidence = self.evidence()
        evidence["candidate"][0]["planned_arena_bytes"] = 145_000_000_000
        with self.assertRaises(InvalidRun):
            self.score(evidence)

    def test_wrong_manifest_rejected(self):
        evidence = self.evidence()
        evidence["manifest_sha256"] = "0" * 64
        with self.assertRaises(InvalidRun):
            self.score(evidence)

    def test_ranked_promotion_requires_aa_and_confidence(self):
        evidence = self.evidence(time_ratio=0.7)
        evidence["tier"] = "rank"
        with self.assertRaises(InvalidRun):
            self.score(evidence)
        evidence["aa"] = {"time_log_ratios": [0.001, -0.001, 0.0],
                          "memory_log_ratios": [0.0, 0.001, -0.001]}
        result = self.score(evidence)
        self.assertTrue(result["tracks"]["latency"]["promotable_against_baseline"])
        self.assertEqual(len(result["tracks"]["latency"]["confidence_95"]), 2)


if __name__ == "__main__":
    unittest.main()
