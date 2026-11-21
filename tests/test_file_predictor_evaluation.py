"""Tests for the file-predictor evaluation."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_file_predictor as evaluation


PAIR = {
    "instance_id": "p1",
    "cohort": "c",
    "repo": "example/repo",
    "repo_id": "repo",
    "label": "conflict",
    "task_a": "A",
    "task_b": "B",
    "changed_paths_a": ["src/a.py", "README.md"],
    "changed_paths_b": ["src/a.py", "tests/test_a.py"],
    "conflict_paths": ["src/a.py"],
}


def fake_rank(task, files, top_k=5, strip_paths=False):
    predictions = {
        ("A", False): ["src/a.py", "tests/test_a.py"],
        ("B", False): ["src/a.py", "docs/x.md"],
        ("A", True): ["src/a.py"],
        ("B", True): ["README.md"],
    }
    return [(path, 1.0) for path in predictions[(task, strip_paths)]]


class PairRowTest(unittest.TestCase):
    def test_overlap_recall_and_stripped_values(self):
        row = evaluation.pair_row(PAIR, ["src/a.py"], {"p1": 0.9}, top_k=2,
                                  rank=fake_rank)
        self.assertEqual(row["predicted_a"], ["src/a.py", "tests/test_a.py"])
        self.assertEqual(row["predicted_b"], ["src/a.py", "docs/x.md"])
        self.assertAlmostEqual(row["predicted_overlap"], 1 / 3)
        self.assertAlmostEqual(row["recall_a"], 0.5)
        self.assertAlmostEqual(row["recall_b"], 0.5)
        self.assertAlmostEqual(row["recall_mean"], 0.5)
        self.assertAlmostEqual(row["conflict_recall"], 1.0)
        self.assertAlmostEqual(row["stripped_overlap"], 0.0)
        self.assertAlmostEqual(row["stripped_recall_mean"], 0.25)
        self.assertAlmostEqual(row["stripped_conflict_recall"], 1.0)


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"instance_id": "1", "repo": "r1", "label": "conflict",
             "text_score": 0.9, "predicted_overlap": 0.5, "actual_overlap": 1.0,
             "recall_mean": 0.5, "conflict_recall": 1.0,
             "stripped_overlap": 0.4, "stripped_recall_mean": 0.3,
             "stripped_conflict_recall": 0.5},
            {"instance_id": "2", "repo": "r2", "label": "clean",
             "text_score": 0.2, "predicted_overlap": 0.0, "actual_overlap": 0.0,
             "recall_mean": 0.0, "conflict_recall": None,
             "stripped_overlap": 0.0, "stripped_recall_mean": 0.0,
             "stripped_conflict_recall": None},
            {"instance_id": "3", "repo": "r3", "label": "conflict",
             "text_score": 0.1, "predicted_overlap": 0.0, "actual_overlap": 0.0,
             "recall_mean": 0.0, "conflict_recall": None,
             "stripped_overlap": 0.0, "stripped_recall_mean": 0.0,
             "stripped_conflict_recall": None},
        ]

    def test_ranking_counts_and_rule(self):
        summary = evaluation.summarize(self.rows, top_k=5)
        self.assertEqual(summary["pairs"], 3)
        self.assertEqual(summary["conflicts"], 2)
        self.assertAlmostEqual(summary["predicted_overlap_ap"], 5 / 6)
        self.assertAlmostEqual(summary["predicted_overlap_pr_auc"], 11 / 12)
        self.assertAlmostEqual(summary["mean_recall_at_k"], 1 / 6)
        self.assertAlmostEqual(summary["mean_conflict_path_recall"], 1.0)
        self.assertAlmostEqual(summary["stripped_mean_recall_at_k"], 0.1)
        self.assertEqual(summary["overlap_positive_rule"], {
            "flagged": 1, "true_positives": 1, "false_positives": 0,
            "missed_conflicts": 1,
        })


class EvaluateTest(unittest.TestCase):
    def test_evaluate_uses_injected_loader_and_rank(self):
        table = {"pairs": [dict(PAIR), dict(PAIR, instance_id="p2", label="clean")]}
        texts = {"p1": 0.9, "p2": 0.1}
        rows, summary = evaluation.evaluate(
            table, {"c": "anchor"}, texts, top_k=2,
            file_loader=lambda anchor, repo: ["src/a.py"],
            rank=fake_rank,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(summary["pairs"], 2)
        self.assertEqual(summary["repositories"], 1)

    def test_evaluate_rejects_nonpositive_top_k(self):
        with self.assertRaises(ValueError):
            evaluation.evaluate({"pairs": []}, {}, {}, top_k=0)

    def test_rank_task_strips_paths_before_ranking(self):
        with mock.patch.object(evaluation, "predict_files_tfidf",
                               side_effect=lambda text, files, top_k: [(text, 1.0)]):
            result = evaluation.rank_task(
                "Edit src/foo.py now", ["src/foo.py"], top_k=1, strip_paths=True)
        self.assertNotIn("src/foo.py", result[0][0])
        self.assertTrue(result[0][0].startswith("Edit"))


if __name__ == "__main__":
    unittest.main()
