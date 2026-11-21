"""Tests for the natural-cohort repository fetcher."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_natural_repo_data as fetch


def pair(instance_id, repo, pr_a=1, pr_b=2, title_a="Fix a", title_b="Add b", label="clean"):
    return {"instance_id": instance_id, "repo": repo, "pr_a": pr_a, "pr_b": pr_b,
            "title_a": title_a, "title_b": title_b, "label": label, "language": "Python"}


class SelectionTests(unittest.TestCase):
    def test_all_pairs_keeps_multiple_pairs_per_repo(self):
        table = {"pairs": [
            pair("a1", "a/one", 1, 2),
            pair("a2", "a/one", 3, 4),
            pair("b1", "b/two", 5, 6),
        ]}
        chosen = fetch._select(table, 0, all_pairs=True)
        self.assertEqual(len(chosen), 3)
        self.assertEqual({row["instance_id"] for row in chosen}, {"a1", "a2", "b1"})

    def test_sample_keeps_one_pair_per_repo(self):
        table = {"pairs": [
            pair("a1", "a/one", 1, 2),
            pair("a2", "a/one", 3, 4),
            pair("b1", "b/two", 5, 6),
        ]}
        chosen = fetch._select(table, 10)
        self.assertEqual(len(chosen), 2)
        self.assertIn("a1", {row["instance_id"] for row in chosen})
        self.assertIn("b1", {row["instance_id"] for row in chosen})

    def test_identical_titles_are_excluded(self):
        table = {"pairs": [pair("a1", "a/one", title_a="Same task", title_b="same task")]}
        self.assertEqual(fetch._select(table, 0, all_pairs=True), [])


class MergeBaseTests(unittest.TestCase):
    def test_compare_runs_even_when_target_bases_match(self):
        api = mock.Mock()
        api.get.return_value = {"merge_base_commit": {"sha": "truebase"}}
        pull_a = {"base": {"sha": "same"}, "head": {"sha": "head-a"}}
        pull_b = {"base": {"sha": "same"}, "head": {"sha": "head-b"}}
        sha, source = fetch._merge_base(api, "a/one", pull_a, pull_b)
        self.assertEqual(sha, "truebase")
        self.assertEqual(source, "compare-merge-base")
        api.get.assert_called_once()

    def test_compare_failure_returns_none(self):
        api = mock.Mock()
        api.get.return_value = None
        pull_a = {"base": {"sha": "a"}, "head": {"sha": "head-a"}}
        pull_b = {"base": {"sha": "b"}, "head": {"sha": "head-b"}}
        sha, source = fetch._merge_base(api, "a/one", pull_a, pull_b)
        self.assertIsNone(sha)
        self.assertEqual(source, "compare-failed")


class FilesTests(unittest.TestCase):
    def test_non_list_response_is_unavailable(self):
        api = mock.Mock()
        api.get.return_value = {"message": "unexpected"}
        rows, truncated = fetch._files(api, "a/one", 1)
        self.assertIsNone(rows)
        self.assertFalse(truncated)

    def test_empty_list_is_a_valid_empty_change_set(self):
        api = mock.Mock()
        api.get.return_value = []
        rows, truncated = fetch._files(api, "a/one", 1)
        self.assertEqual(rows, [])
        self.assertFalse(truncated)


if __name__ == "__main__":
    unittest.main()
