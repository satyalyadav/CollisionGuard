"""Tests for the natural-mix cohort builder."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_natural_cohort as builder


def row(**overrides):
    base = {
        "repo": "example/repo",
        "prA": 10,
        "prB": 11,
        "label": "CONFLICT",
        "stratum": "cross",
        "agentA": "OpenAI_Codex",
        "agentB": "Devin",
        "created_a": "2026-01-01T00:00:00Z",
        "created_b": "2026-01-02T00:00:00Z",
        "title_a": "Fix the parser",
        "title_b": "Add a cache layer",
        "body_a": "Body A",
        "body_b": None,
        "issue_title_a": "Parser fails",
        "issue_title_b": None,
        "issue_body_a": "Steps to reproduce",
        "issue_body_b": None,
        "issue_number_a": 5,
        "issue_number_b": None,
        "issue_source_a": "body",
        "issue_source_b": None,
        "issue_created_a": "2025-12-01T00:00:00Z",
        "issue_created_b": None,
        "language": "Python",
        "license": "MIT",
        "stars": 12,
        "is_forked": False,
        "files": "src/a.py|tests/test_a.py",
        "types": "content|modify/delete",
        "agent_a": "OpenAI_Codex",
        "agent_b": "Devin",
        "merged_a": None,
        "merged_b": None,
    }
    base.update(overrides)
    return base


class PairTests(unittest.TestCase):
    def test_pair_maps_label_and_paths(self):
        pair = builder._pair(row())
        self.assertEqual(pair["label"], "conflict")
        self.assertEqual(pair["conflict_paths"], ["src/a.py", "tests/test_a.py"])
        self.assertEqual(pair["conflict_types"], ["content", "modify/delete"])
        self.assertEqual(pair["repo"], "example/repo")
        self.assertEqual(pair["issue_source_a"], "body")
        self.assertIsNone(pair["issue_body_b"])

    def test_pair_requires_both_titles(self):
        self.assertIsNone(builder._pair(row(title_b="  ")))

    def test_instance_id_is_deterministic(self):
        first = builder._instance_id("example/repo", 10, 11)
        second = builder._instance_id("example/repo", 10, 11)
        other = builder._instance_id("example/repo", 10, 12)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("nc-"))

    def test_clean_label_and_empty_paths(self):
        pair = builder._pair(row(label="CLEAN", files=None, types=None))
        self.assertEqual(pair["label"], "clean")
        self.assertEqual(pair["conflict_paths"], [])


class DigestTests(unittest.TestCase):
    def test_round_trip_and_tamper(self):
        table = {"protocol_version": "x", "pairs": [{"a": 1}]}
        table["table_sha256"] = builder.table_body_digest(table)
        builder.verify_table(table)
        table["pairs"][0]["a"] = 2
        with self.assertRaises(ValueError):
            builder.verify_table(table)

    def test_timestamp_and_digest_are_excluded(self):
        table = {"pairs": [], "built_at": "first"}
        digest = builder.table_body_digest(table)
        table["built_at"] = "second"
        table["table_sha256"] = "ignored"
        self.assertEqual(digest, builder.table_body_digest(table))


class SummaryTests(unittest.TestCase):
    def test_counts_and_subsets(self):
        pairs = [
            {"repo": "a/one", "label": "conflict", "stratum": "cross",
             "language": "Python", "license": "MIT",
             "issue_title_a": "i", "issue_title_b": "j",
             "body_a": "b", "body_b": "b"},
            {"repo": "b/two", "label": "clean", "stratum": "same",
             "language": "Go", "license": "Apache-2.0",
             "issue_title_a": "i", "issue_title_b": None,
             "body_a": "b", "body_b": "b"},
        ]
        table = {
            "pairs": pairs,
            "table_sha256": "abc",
            "source": {"x": 1},
        }
        summary = builder._summary(table)
        self.assertEqual(summary["pairs"], 2)
        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(summary["clean"], 1)
        self.assertEqual(summary["prevalence"], 0.5)
        self.assertEqual(summary["repositories"], 2)
        self.assertEqual(summary["both_linked_issues"], 1)
        self.assertEqual(summary["both_linked_issue_conflicts"], 1)
        self.assertEqual(summary["strata"], {"cross": 1, "same": 1})
        self.assertEqual(summary["languages"], {"Python": 1, "Go": 1})
        self.assertFalse(summary["task_text_public"])


if __name__ == "__main__":
    unittest.main()
