"""Tests for the ten-pair prediction table and its baseline run."""

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_controlled_prediction as builder
import run_controlled_predictions as runner


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fixture(root):
    """Write two five-pair cohorts in the shape the frozen plans use."""
    paths = {}
    for cohort, labels in (("controlled-v3", ["clean", "clean", "clean", "conflict", "conflict"]),
                           ("fresh-2026-11", ["conflict"] * 5)):
        plan_dir = root / cohort
        (plan_dir / "prompts").mkdir(parents=True)
        repositories, tasks, plan_pairs = [], [], []
        for index, label in enumerate(labels):
            repo_id = f"{cohort}-repo-{index}"
            pair_id = f"{cohort}-pair-{index}"
            task_ids = [f"{cohort}-task-{index}-a", f"{cohort}-task-{index}-b"]
            repositories.append({"repo_id": repo_id,
                                 "canonical_name": f"example/{repo_id}"})
            for arm, task_id in zip("AB", task_ids):
                acceptance = (f"Add helper {task_id} to src/module_{index}.py and "
                              f"tests/test_module_{index}.py. Keep the existing behavior "
                              f"for arm {arm}.")
                prompt = ("You are a coding worker for a private research exercise.\n\n"
                          f"Task-specific acceptance criteria follow:\n\n{acceptance}\n\n"
                          f"Focused test target: tests/test_module_{index}.py\n")
                prompt_path = plan_dir / "prompts" / f"{task_id}.txt"
                prompt_path.write_text(prompt, encoding="utf-8")
                tasks.append({
                    "task_id": task_id,
                    "acceptance": acceptance,
                    "prompt_file": f"prompts/{task_id}.txt",
                    "prompt_sha256": _sha256(prompt),
                    "repo_id": repo_id,
                    "pair_id": pair_id,
                })
            plan_pairs.append({"pair_id": pair_id, "repo_id": repo_id, "task_ids": task_ids})
        plan = {"run_id": f"run-{cohort}", "repositories": repositories,
                "tasks": tasks, "pairs": plan_pairs}
        plan["plan_sha256"] = builder._sha256_bytes(builder._canonical_json(plan))
        plan_path = plan_dir / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        if cohort == "controlled-v3":
            rows = []
            for index, (pair, label) in enumerate(zip(plan_pairs, labels)):
                changed = [{"path": f"src/module_{index}.py", "status": "M"}]
                rows.append(dict(pair, posthoc_git_visible={
                    "identical_repeats": True,
                    "merge_status": label,
                    "conflict_paths": [f"src/module_{index}.py"] if label == "conflict" else [],
                    "tasks": [{"task_id": task_id, "status": "ok", "changed_paths": changed}
                              for task_id in pair["task_ids"]],
                }, raw_full_directory_capture={
                    "starting_snapshots_equal": True,
                    "merge_repeats_identical": True,
                }))
            results = {"pairs": rows}
        else:
            task_rows, rows = [], []
            for index, (pair, label) in enumerate(zip(plan_pairs, labels)):
                task_paths = {
                    pair["task_ids"][0]: [f"src/a_{index}.py"],
                    pair["task_ids"][1]: [f"src/b_{index}.py"],
                }
                for task_id in pair["task_ids"]:
                    task = next(item for item in tasks if item["task_id"] == task_id)
                    task_rows.append({"task_id": task_id, "pair_id": pair["pair_id"],
                                      "repo_id": pair["repo_id"], "replay_ok": True,
                                      "prompt_sha256": task["prompt_sha256"],
                                      "changed_paths": task_paths[task_id]})
                # The pair list is in replay order, which is the reverse of the sorted task ids.
                rows.append(dict(pair, label=label,
                                 starting_snapshots_equal=True,
                                 merge_repeats_identical=True,
                                 changed_paths=[task_paths[pair["task_ids"][1]],
                                                task_paths[pair["task_ids"][0]]],
                                 conflict_paths=[f"src/a_{index}.py"] if label == "conflict" else []))
            results = {"run_id": plan["run_id"], "plan_sha256": plan["plan_sha256"],
                       "capture_policy": "ordinary-git-staging-v1",
                       "tasks": task_rows, "pairs": rows}
        result_path = plan_dir / "results.json"
        result_path.write_text(json.dumps(results), encoding="utf-8")
        paths[cohort] = (plan_path, result_path)
    return (paths["controlled-v3"][0], paths["controlled-v3"][1],
            paths["fresh-2026-11"][0], paths["fresh-2026-11"][1])


class BuildTableTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = _fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_builds_ten_pairs_with_public_hashes_only(self):
        table, summary = builder.build_table(*self.paths)
        self.assertEqual(len(table["pairs"]), 10)
        self.assertEqual(summary["pairs"], 10)
        self.assertEqual(summary["clean"], 3)
        self.assertEqual(summary["conflict"], 7)
        self.assertEqual(summary["repositories"], 10)
        self.assertEqual(len(summary["cohorts"]), 2)
        self.assertFalse(summary["task_text_public"])
        rendered = json.dumps(summary)
        self.assertNotIn("Add helper", rendered)
        self.assertNotIn("module_0.py", rendered)

    def test_table_hash_is_stable(self):
        first, _ = builder.build_table(*self.paths)
        second, _ = builder.build_table(*self.paths)
        self.assertEqual(first["table_sha256"], second["table_sha256"])

    def test_changed_paths_follow_task_ids(self):
        table, _ = builder.build_table(*self.paths)
        pair = next(item for item in table["pairs"]
                    if item["cohort"] == "fresh-2026-11" and item["repo"].endswith("repo-0"))
        self.assertEqual(pair["changed_paths_a"], ["src/a_0.py"])
        self.assertEqual(pair["changed_paths_b"], ["src/b_0.py"])
        self.assertEqual(pair["conflict_paths"], ["src/a_0.py"])

    def test_tampered_table_body_fails_verification(self):
        table, _ = builder.build_table(*self.paths)
        table["pairs"][0]["task_a"] += " tampered"
        with self.assertRaises(ValueError):
            builder.verify_table(table)

    def test_tampered_plan_digest_is_rejected(self):
        path = self.root / "controlled-v3" / "plan.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["frozen_at"] = "tampered"
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(ValueError):
            builder.build_table(*self.paths)

    def test_changed_prompt_is_rejected(self):
        prompt = self.root / "controlled-v3" / "prompts" / "controlled-v3-task-0-a.txt"
        prompt.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            builder.build_table(*self.paths)

    def test_duplicate_repository_is_rejected(self):
        table, _ = builder.build_table(*self.paths)
        table["pairs"][1]["repo"] = table["pairs"][0]["repo"]
        with self.assertRaises(ValueError):
            builder._check_pairs(table["pairs"])

    def test_single_label_class_is_rejected(self):
        table, _ = builder.build_table(*self.paths)
        for pair in table["pairs"]:
            pair["label"] = "conflict"
        with self.assertRaises(ValueError):
            builder._check_pairs(table["pairs"])


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.table, _ = builder.build_table(*_fixture(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def test_scores_every_pair_without_task_text_in_output(self):
        with contextlib.redirect_stdout(io.StringIO()):
            results = runner.build_results(self.table)
        self.assertEqual(results["pairs"], 10)
        self.assertEqual(results["conflict"], 7)
        self.assertAlmostEqual(results["no_skill_ap"], 0.7)
        self.assertEqual(len(results["scores"]), 10)
        self.assertEqual(results["leakage_audit"], {"folds": 10, "passed": True})
        for score in results["scores"]:
            self.assertIsNotNone(score["tfidf"])
            self.assertIsNotNone(score["tfidf_paths_removed"])
            self.assertIsNotNone(score["logistic"])
            self.assertIn("cohort", score)
        rendered = json.dumps(results)
        self.assertNotIn("Add helper", rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_runner_rejects_tampered_table(self):
        self.table["pairs"][0]["task_a"] += " tampered"
        path = self.root / "tampered.json"
        path.write_text(json.dumps(self.table), encoding="utf-8")
        with self.assertRaises(ValueError):
            runner._load(path)

    def test_json_safe_replaces_nan(self):
        self.assertIsNone(runner._json_safe(float("nan")))
        self.assertEqual(runner._json_safe({"a": [float("nan")]}), {"a": [None]})


if __name__ == "__main__":
    unittest.main()
