"""Tests for the natural-cohort text baselines."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_natural_predictions as runner


def pair(**overrides):
    base = {
        "instance_id": "nc-1",
        "repo": "example/repo",
        "label": "conflict",
        "title_a": "Fix the parser",
        "title_b": "Add a cache layer",
        "body_a": "body a",
        "body_b": "body b",
        "issue_title_a": "Parser fails",
        "issue_title_b": "Add cache",
        "issue_body_a": "issue body a",
        "issue_body_b": "issue body b",
    }
    base.update(overrides)
    return base


class TextVariantTests(unittest.TestCase):
    def test_title_variants(self):
        self.assertEqual(runner._text(pair(), "title"),
                         ("Fix the parser", "Add a cache layer"))
        a, b = runner._text(pair(), "title_body")
        self.assertIn("body a", a)
        self.assertIn("body b", b)

    def test_missing_body_is_tolerated(self):
        a, b = runner._text(pair(body_a=None, body_b=None), "title_body")
        self.assertEqual(a, "Fix the parser")
        self.assertEqual(b, "Add a cache layer")

    def test_issue_variants_require_both_titles(self):
        self.assertEqual(runner._text(pair(), "issue_title"),
                         ("Parser fails", "Add cache"))
        self.assertEqual(runner._text(pair(issue_title_b=None), "issue_title"), ("Parser fails", ""))
        self.assertEqual(runner._text(pair(issue_title_a=None), "issue_title_body"), ("", ""))
        a, b = runner._text(pair(), "issue_title_body")
        self.assertIn("issue body a", a)
        self.assertIn("issue body b", b)

    def test_unknown_variant_fails(self):
        with self.assertRaises(ValueError):
            runner._text(pair(), "nope")


class EligibilityTests(unittest.TestCase):
    def test_drops_missing_text_and_identical_titles(self):
        table = {"pairs": [
            pair(instance_id="ok"),
            pair(instance_id="same", title_a="Same Task", title_b="same task"),
            pair(instance_id="no-issue", issue_title_b=None),
            pair(instance_id="short", title_b=""),
        ]}
        rows, excluded = runner._eligible(table, "issue_title")
        self.assertEqual([row["instance_id"] for row in rows], ["ok", "same", "short"])
        self.assertEqual(excluded, 0)
        rows, excluded = runner._eligible(table, "title")
        self.assertEqual([row["instance_id"] for row in rows], ["ok", "no-issue"])
        self.assertEqual(excluded, 1)


class FoldTests(unittest.TestCase):
    def test_repositories_stay_together(self):
        table = {"pairs": [
            pair(instance_id="a1", repo="a/one", title_a="one", title_b="two"),
            pair(instance_id="a2", repo="a/one", title_a="three", title_b="four"),
            pair(instance_id="b1", repo="b/two", title_a="five", title_b="six"),
            pair(instance_id="c1", repo="c/three", title_a="seven", title_b="eight"),
            pair(instance_id="d1", repo="d/four", title_a="nine", title_b="ten"),
            pair(instance_id="e1", repo="e/five", title_a="eleven", title_b="twelve"),
        ]}
        eligible, _ = runner._eligible(table, "title")
        records = runner._records(eligible)
        folds = runner._folds(records)
        self.assertEqual(len(folds), 5)
        for train, test in folds:
            train_repos = {records[i]["repo"] for i in train}
            test_repos = {records[i]["repo"] for i in test}
            self.assertFalse(train_repos & test_repos)


if __name__ == "__main__":
    unittest.main()
