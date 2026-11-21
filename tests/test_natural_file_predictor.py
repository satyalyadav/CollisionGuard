"""Tests for the natural-cohort file-predictor evaluation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_natural_file_predictor as evaluation


def fetched(**overrides):
    base = {
        "status": "ok",
        "tree_paths": [
            "src/parser.py",
            "src/cache.py",
            "tests/test_parser.py",
            "tests/test_cache.py",
            "docs/readme.md",
        ],
        "files_a": [{"path": "src/parser.py"}, {"path": "tests/test_parser.py"}],
        "files_b": [{"path": "src/cache.py"}, {"path": "src/parser.py"}],
        "tree_truncated": False,
        "files_truncated": False,
    }
    base.update(overrides)
    return base


def pair(**overrides):
    base = {
        "instance_id": "nc-1",
        "repo": "example/repo",
        "pr_a": 10,
        "pr_b": 11,
        "label": "conflict",
        "stratum": "cross",
        "language": "Python",
        "task_a": "Fix parser crash",
        "task_b": "Add cache layer",
        "conflict_paths": ["src/parser.py"],
    }
    base.update(overrides)
    return base


class SmallFunctionTests(unittest.TestCase):
    def test_jaccard(self):
        self.assertEqual(evaluation.jaccard(["a"], ["a"]), 1.0)
        self.assertEqual(evaluation.jaccard(["a"], ["b"]), 0.0)
        self.assertEqual(evaluation.jaccard(["a", "b"], ["b", "c"]), 1 / 3)
        self.assertEqual(evaluation.jaccard([], []), 0.0)

    def test_recall_handles_empty_actual(self):
        self.assertEqual(evaluation.recall(["a"], []), 0.0)
        self.assertEqual(evaluation.recall(["a"], ["a", "b"]), 0.5)

    def test_directory(self):
        self.assertEqual(evaluation.directory("src/a.py"), "src")
        self.assertEqual(evaluation.directory("README.md"), "")

    def test_conflict_recall_none_without_paths(self):
        self.assertIsNone(evaluation._conflict_recall(["a"], ["b"], []))


class PairRowTests(unittest.TestCase):
    def test_row_contains_overlap_and_recall(self):
        row = evaluation.pair_row(pair(), fetched(), 0.4,
                                  "Fix parser crash", "Add cache layer")
        self.assertEqual(row["instance_id"], "nc-1")
        self.assertEqual(row["label"], "conflict")
        self.assertEqual(row["actual_overlap"], 1 / 3)
        self.assertGreaterEqual(row["predicted_overlap"], 0.0)
        self.assertLessEqual(row["predicted_overlap"], 1.0)
        self.assertIn("directory_overlap", row)
        self.assertIn("stripped_overlap", row)
        self.assertGreaterEqual(row["recall_mean"], 0.0)


class SummaryTests(unittest.TestCase):
    def test_summary_shape(self):
        rows = [
            evaluation.pair_row(pair(instance_id="a", repo="example/one"), fetched(), 0.9,
                                "Fix parser crash", "Add cache layer"),
            evaluation.pair_row(pair(instance_id="b", repo="example/two", label="clean"),
                                fetched(), 0.1, "Fix parser crash", "Add cache layer"),
        ]
        summary = evaluation.summarize(rows)
        self.assertEqual(summary["pairs"], 2)
        self.assertEqual(summary["conflicts"], 1)
        self.assertTrue(summary["actual_overlap_is_oracle"])
        self.assertIn("predicted_overlap_ap_interval", summary)
        self.assertIn("overlap_positive_rule", summary)
        self.assertIn("cross", summary["strata"])


if __name__ == "__main__":
    unittest.main()
