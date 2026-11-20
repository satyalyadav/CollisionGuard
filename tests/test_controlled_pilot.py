from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import controlled_pilot as pilot


MODEL = {
    "provider": "kiro",
    "model": "claude-haiku-5.5",
    "options": [{"id": "mode", "value": "vibe"}],
}


def run(argv: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def init_repo(root: Path) -> tuple[str, str]:
    root.mkdir()
    run(["git", "init", "-q", str(root)])
    run(["git", "-C", str(root), "config", "user.name", "Fixture"])
    run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"])
    (root / "sample.txt").write_text(
        "first\nsecond\nthird\nfourth\nfifth\nsixth\nseventh\neighth\nninth\n", encoding="utf-8"
    )
    run(["git", "-C", str(root), "add", "--all"])
    run(["git", "-C", str(root), "commit", "-qm", "base"])
    return run(["git", "-C", str(root), "rev-parse", "HEAD"]), run(
        ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"]
    )


def install_plan(private: Path, source: Path, commit: str, tree: str) -> dict:
    (private / "prompts").mkdir(parents=True)
    repos = []
    pairs = []
    tasks = []
    for i in range(5):
        repo_id = f"repo{i}"
        pair_id = f"pair{i}"
        repos.append({"repo_id": repo_id, "source_path": str(source), "commit": commit, "tree": tree,
                      "requested_name": repo_id, "canonical_name": repo_id, "visibility": "public",
                      "default_branch": "main", "stars_at_pin": 0, "license_spdx": "MIT",
                      "identity_resolution": None})
        pairs.append({"pair_id": pair_id, "repo_id": repo_id})
        for arm in ("a", "b"):
            task_id = f"{pair_id}-{arm}"
            text = f"Fixture task {task_id}.\n"
            prompt_file = f"prompts/{task_id}.txt"
            (private / prompt_file).write_text(text, encoding="utf-8")
            tasks.append({
                "task_id": task_id,
                "pair_id": pair_id,
                "repo_id": repo_id,
                "arm": arm,
                "prompt_file": prompt_file,
                "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "model": MODEL,
            })
    plan = {"protocol_version": pilot.PROTOCOL_VERSION, "producer_sha256": "fixture-producer",
            "repositories": repos, "pairs": pairs, "tasks": tasks}
    digest_source = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    plan["plan_sha256"] = hashlib.sha256(digest_source).hexdigest()
    (private / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan


def write_task_snapshot(private: Path, task: dict, source: Path, commit: str, tree: str) -> None:
    snap = pilot.snapshot(source)
    snap.update({"task_id": task["task_id"], "pair_id": task["pair_id"], "repo_id": task["repo_id"],
                 "expected_head": commit, "expected_tree": tree, "prompt_sha256": task["prompt_sha256"],
                 "phase": "fixture_before_mutation"})
    pilot.dump_json(pilot.snapshot_path(task["task_id"]), snap)


def write_output(private: Path, source: Path, task: dict, edit: str, conflict: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="pilot-side-") as d:
        side = Path(d) / "side"
        run(["git", "clone", "-q", "--local", str(source), str(side)])
        run(["git", "-C", str(side), "config", "user.name", "Fixture"])
        run(["git", "-C", str(side), "config", "user.email", "fixture@example.invalid"])
        lines = (side / "sample.txt").read_text(encoding="utf-8").splitlines(keepends=True)
        target_line = 1 if conflict or task["arm"] == "a" else 7
        lines[target_line] = edit + "\n"
        (side / "sample.txt").write_text("".join(lines), encoding="utf-8")
        if task["arm"] == "a":
            (side / "added.bin").write_bytes(b"\x00\x01fixture\xff")
            executable = side / "tool.sh"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        run(["git", "-C", str(side), "add", "--all"])
        tree = run(["git", "-C", str(side), "write-tree"])
        base_tree = run(["git", "-C", str(side), "rev-parse", "HEAD^{tree}"])
        patch_bytes = subprocess.run(
            ["git", "-C", str(side), "diff", "--binary", "--full-index", "--no-renames", base_tree, tree],
            check=True,
            capture_output=True,
        ).stdout
    out = pilot.output_path(task["task_id"])
    out.mkdir(parents=True)
    (out / "full-tree.patch").write_bytes(patch_bytes)
    pilot.dump_json(out / "record.json", {
        "task_id": task["task_id"], "pair_id": task["pair_id"], "repo_id": task["repo_id"],
        "final_working_tree": tree, "final_index_tree": tree,
        "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(), "patch_file": f"outputs/{task['task_id']}/full-tree.patch",
        "nonempty": bool(patch_bytes), "head_unchanged": True, "changed_paths": ["sample.txt"],
        "artifact_paths": [],
    })
    pilot.dump_json(pilot.task_run_path(task["task_id"]), {
        "task_id": task["task_id"], "pair_id": task["pair_id"], "repo_id": task["repo_id"],
        "prompt_sha256": task["prompt_sha256"], "requested_model": MODEL,
        "provider_instance_id": "kiro", "executed_model": "claude-haiku-5.5",
        "options": MODEL["options"], "coding_started": True, "within_limits": True, "provenance_ok": True,
    })


class PilotRecorderTests(unittest.TestCase):
    def test_capture_precedes_mutation_and_verify_detects_drift(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            source = base / "source"
            commit, tree = init_repo(source)
            private = base / "private"
            install_plan(private, source, commit, tree)
            with patch.object(pilot, "PRIVATE", private), patch.object(pilot, "PLAN", private / "plan.json"):
                task = pilot.tasks_by_id(pilot.load_plan())["pair0-a"]
                captured = pilot.capture(task["task_id"], source, "fixture_hook")
                self.assertEqual(captured["tree"], tree)
                self.assertTrue(captured["clean"])
                self.assertEqual(pilot.capture(task["task_id"], source, "retry"), captured)
                (source / "sample.txt").write_text("changed\n", encoding="utf-8")
                with self.assertRaisesRegex(pilot.PilotError, "drift"):
                    pilot.verify(task["task_id"], source)

    def test_collect_captures_ignored_binary_mode_and_resumes_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            source = base / "source"
            commit, tree = init_repo(source)
            private = base / "private"
            plan = install_plan(private, source, commit, tree)
            task = plan["tasks"][0]
            child = base / "child"
            run(["git", "clone", "-q", "--local", str(source), str(child)])
            with patch.object(pilot, "PRIVATE", private), patch.object(pilot, "PLAN", private / "plan.json"):
                pilot.capture(task["task_id"], child, "fixture_hook")
                (child / ".gitignore").write_text(".pytest_cache/\n", encoding="utf-8")
                (child / "sample.txt").write_text("changed\n", encoding="utf-8")
                (child / "payload.bin").write_bytes(b"\x00\xfe\xff")
                executable = child / "tool.sh"
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                executable.chmod(0o755)
                cache = child / ".pytest_cache" / "v" / "cache"
                cache.mkdir(parents=True)
                (cache / "lastfailed").write_text("{}", encoding="utf-8")
                run(["git", "-C", str(child), "add", "sample.txt", ".gitignore"])
                captured = pilot.collect(task["task_id"], child)
                repeated = pilot.collect(task["task_id"], child)
            self.assertEqual(captured, repeated)
            self.assertTrue({"payload.bin", "tool.sh", ".pytest_cache/v/cache/lastfailed"}.issubset(captured["changed_paths"]))
            self.assertIn(".pytest_cache/v/cache/lastfailed", captured["artifact_paths"])
            patch_bytes = (private / captured["patch_file"]).read_bytes()
            self.assertIn(b"GIT binary patch", patch_bytes)
            self.assertIn(b"new file mode 100755", patch_bytes)
            self.assertNotEqual(captured["final_index_tree"], captured["final_working_tree"])

    def test_plan_keeps_distinct_task_ids_and_prompt_joins(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            commit, tree = init_repo(source)
            private = Path(d) / "private"
            plan = install_plan(private, source, commit, tree)
            with patch.object(pilot, "PRIVATE", private):
                pilot.validate_plan(plan)
                self.assertEqual(len(pilot.tasks_by_id(plan)), 10)
                plan["tasks"][1]["task_id"] = plan["tasks"][0]["task_id"]
                with self.assertRaisesRegex(pilot.PilotError, "task ids"):
                    pilot.validate_plan(plan)

    def test_feasibility_gate_is_not_evaluated_before_all_five_pairs_are_attempted(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            commit, tree = init_repo(source)
            private = Path(d) / "private"
            plan = install_plan(private, source, commit, tree)
            gate = pilot.feasibility(plan, [])
        self.assertFalse(gate["all_five_pairs_attempted"])
        self.assertEqual(gate["status"], "not_evaluated")
        self.assertIsNone(gate["passes"])

    def test_full_tree_replay_records_binary_modes_and_clean_label(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            source = base / "source"
            commit, tree = init_repo(source)
            private = base / "private"
            plan = install_plan(private, source, commit, tree)
            pair_tasks = [t for t in plan["tasks"] if t["pair_id"] == "pair0"]
            with patch.object(pilot, "PRIVATE", private), patch.object(pilot, "PLAN", private / "plan.json"):
                for task, line in zip(pair_tasks, ("second-a", "second-b")):
                    write_task_snapshot(private, task, source, commit, tree)
                    write_output(private, source, task, line)
                result = pilot.replay_pair("pair0")
            self.assertTrue(result["qualifies"], result["exclusion_reasons"])
            self.assertEqual(result["label"], "clean")
            self.assertTrue(result["merge_repeats_identical"])
            patch_text = (private / "outputs" / pair_tasks[0]["task_id"] / "full-tree.patch").read_bytes()
            self.assertIn(b"GIT binary patch", patch_text)
            self.assertIn(b"new file mode 100755", patch_text)

    def test_conflict_and_error_or_empty_output_never_receive_clean_label(self):
        clean = [{"returncode": 0, "stdout": "tree\n", "stderr": "", "timed_out": False}] * 2
        self.assertIsNone(pilot.label_from_repeats(clean, snapshots_equal=True, nonempty=[False, True],
                                                   outputs_distinct=True, side_trees_match=[True, True],
                                                   within_limits=True, provenance_ok=True))
        error = [{"returncode": 2, "stdout": "", "stderr": "fatal", "timed_out": False}] * 2
        self.assertIsNone(pilot.label_from_repeats(error, snapshots_equal=True, nonempty=[True, True],
                                                   outputs_distinct=True, side_trees_match=[True, True],
                                                   within_limits=True, provenance_ok=True))
        conflict = [{"returncode": 1, "stdout": "CONFLICT (content)", "stderr": "", "timed_out": False}] * 2
        self.assertEqual(pilot.label_from_repeats(conflict, snapshots_equal=True, nonempty=[True, True],
                                                  outputs_distinct=True, side_trees_match=[True, True],
                                                  within_limits=True, provenance_ok=True), "conflict")

    def test_missing_output_is_an_unlabelled_attempt_and_stays_in_summary(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            source = base / "source"
            commit, tree = init_repo(source)
            private = base / "private"
            plan = install_plan(private, source, commit, tree)
            pair_tasks = [t for t in plan["tasks"] if t["pair_id"] == "pair0"]
            with patch.object(pilot, "PRIVATE", private), patch.object(pilot, "PLAN", private / "plan.json"):
                for task in pair_tasks:
                    write_task_snapshot(private, task, source, commit, tree)
                    write_output(private, source, task, task["task_id"])
                (pilot.output_path(pair_tasks[1]["task_id"]) / "record.json").unlink()
                row = pilot.replay_pair("pair0")
                self.assertTrue(row["attempted"])
                self.assertIsNone(row["label"])
                self.assertFalse(row["qualifies"])
                self.assertIn("one or more task outputs were not collected", row["exclusion_reasons"])
                summary = pilot.write_public_summary()
            self.assertEqual(len(summary["pairs"]), 5)
            self.assertTrue(summary["pairs"][0]["attempted"])
            self.assertIsNone(summary["pairs"][0]["label"])

    def test_artifacts_are_flagged_without_removing_them(self):
        paths = ["src/app.py", ".pytest_cache/v/cache/lastfailed", "pkg/__pycache__/app.pyc", "new.bin"]
        self.assertEqual(pilot.artifact_paths(paths), [".pytest_cache/v/cache/lastfailed", "pkg/__pycache__/app.pyc"])

    def test_bounded_job_log_keeps_owner_pid_deadline_and_exit(self):
        with tempfile.TemporaryDirectory() as d:
            private = Path(d)
            with patch.object(pilot, "PRIVATE", private):
                code = pilot.main(["run", "--task-id", "pair0-a", "--cwd", d, "--timeout-seconds", "5",
                                   "--", "python3", "-c", "raise SystemExit(7)"])
                self.assertEqual(code, 7)
                logs = list((private / "outputs" / "pair0-a" / "jobs").glob("*.json"))
                self.assertEqual(len(logs), 1)
                job = json.loads(logs[0].read_text(encoding="utf-8"))
                self.assertEqual((job["owner"], job["returncode"], job["timed_out"]), ("pair0-a", 7, False))
                self.assertGreater(job["pid"], 0)
                self.assertIn("deadline_at", job)


if __name__ == "__main__":
    unittest.main()
