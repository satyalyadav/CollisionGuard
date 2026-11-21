"""Tests for the natural-cohort analysis subsets."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_natural_cohort as analysis


def row(**overrides):
    base = {
        "instance_id": "nc-1",
        "repo": "example/repo",
        "label": 1,
        "stratum": "same",
        "language": "Python",
        "title_similarity": 0.1,
        "same_issue": False,
        "early_issue": False,
        "strict_issue": False,
        "tfidf": 0.5,
        "logistic": 0.4,
    }
    base.update(overrides)
    return base


class MetricTests(unittest.TestCase):
    def test_metrics_need_both_classes(self):
        self.assertIsNone(analysis._metrics([row()], "tfidf"))

    def test_metrics_values(self):
        rows = [row(instance_id="a", label=1, tfidf=0.9),
                row(instance_id="b", label=0, tfidf=0.1)]
        result = analysis._metrics(rows, "tfidf")
        self.assertEqual(result["pairs"], 2)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["prevalence"], 0.5)
        self.assertEqual(result["average_precision"], 1.0)
        self.assertEqual(result["roc_auc"], 1.0)


class SubsetTests(unittest.TestCase):
    def test_subsets_are_nested_as_expected(self):
        rows = [
            row(instance_id="a", stratum="same", title_similarity=0.1, same_issue=False),
            row(instance_id="b", stratum="cross", title_similarity=0.9, same_issue=False),
            row(instance_id="c", stratum="same", title_similarity=0.2, same_issue=True),
        ]
        subsets = analysis._subsets(rows)
        self.assertEqual(len(subsets["all"]), 3)
        self.assertEqual(len(subsets["same_agent"]), 2)
        self.assertEqual(len(subsets["cross_agent"]), 1)
        self.assertEqual([r["instance_id"] for r in subsets["titles_dissimilar"]], ["a", "c"])
        self.assertEqual([r["instance_id"] for r in subsets["different_linked_issue"]], ["a", "b"])
        self.assertEqual([r["instance_id"] for r in subsets["dissimilar_and_different_issue"]],
                         ["a"])

    def test_strict_issue_requires_body_links_and_earlier_issues(self):
        base = {
            "issue_source_a": "body", "issue_source_b": "body",
            "issue_created_a": "2026-01-01T00:00:00Z",
            "issue_created_b": "2026-01-02T00:00:00Z",
            "created_a": "2026-01-03T00:00:00Z",
            "created_b": "2026-01-04T00:00:00Z",
        }
        self.assertTrue(analysis._strict_issue(base))
        self.assertFalse(analysis._strict_issue({**base, "issue_source_b": "timeline"}))
        self.assertFalse(analysis._strict_issue({**base, "issue_created_a": "2026-01-05T00:00:00Z"}))
        self.assertFalse(analysis._strict_issue({**base, "issue_created_b": None}))

    def test_title_similarity(self):
        pair = {"title_a": "Fix parser crash", "title_b": "Fix parser crash"}
        self.assertEqual(analysis._title_similarity(pair), 1.0)
        pair = {"title_a": "Add cache", "title_b": "Remove docs"}
        self.assertEqual(analysis._title_similarity(pair), 0.0)
        self.assertEqual(analysis._title_similarity({"title_a": "", "title_b": ""}), 1.0)


if __name__ == "__main__":
    unittest.main()
