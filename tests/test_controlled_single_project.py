from __future__ import annotations

import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import controlled_single_project as csp


HELPER = Path(__file__).resolve().parents[1] / "scripts" / "controlled_single_project.py"


def run(argv: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def init_repo(path: Path) -> None:
    path.mkdir()
    run(["git", "init", "-q", str(path)])
    run(["git", "-C", str(path), "config", "user.name", "Fixture"])
    run(["git", "-C", str(path), "config", "user.email", "fixture@example.invalid"])


def make_parent(base: Path) -> Path:
    parent = base / "parent"
    init_repo(parent)
    (parent / "README.md").write_text("CollisionGuard fixture\n", encoding="utf-8")
    (parent / "scripts").mkdir()
    (parent / "scripts" / "keep.py").write_text("VALUE = 1\n", encoding="utf-8")
    run(["git", "-C", str(parent), "add", "-A"])
    run(["git", "-C", str(parent), "commit", "-qm", "parent snapshot"])
    (parent / "scripts" / "controlled_single_project.py").write_text(
        HELPER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return parent


def make_source(base: Path, repo_id: str, body: str, *, dir_symlink: bool = False) -> dict:
    source = base / f"source-{repo_id}"
    init_repo(source)
    (source / "lib.py").write_text(body, encoding="utf-8")
    (source / "LICENSE").write_text(f"fixture license for {repo_id}\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_lib.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    if dir_symlink:
        (source / "real").mkdir()
        (source / "real" / "ca.crt").write_text("fixture certificate\n", encoding="utf-8")
        (source / "tests" / "ca").symlink_to("../real")
    run(["git", "-C", str(source), "add", "-A"])
    run(["git", "-C", str(source), "commit", "-qm", "pin"])
    return {
        "repo_id": repo_id,
        "source_path": str(source),
        "commit": run(["git", "-C", str(source), "rev-parse", "HEAD"]),
        "tree": run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]),
    }


def make_ignoring_source(base: Path, repo_id: str) -> dict:
    """A source repo with an ignore rule and one committed file that matches it."""
    source = base / f"source-{repo_id}"
    init_repo(source)
    (source / ".gitignore").write_text("*.log\n__pycache__/\n", encoding="utf-8")
    (source / "lib.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (source / "LICENSE").write_text(f"fixture license for {repo_id}\n", encoding="utf-8")
    (source / "tracked.log").write_text("committed before the ignore rule\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_lib.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    run(["git", "-C", str(source), "add", "-A"])
    run(["git", "-C", str(source), "add", "-f", "tracked.log"])
    run(["git", "-C", str(source), "commit", "-qm", "pin"])
    return {
        "repo_id": repo_id,
        "source_path": str(source),
        "commit": run(["git", "-C", str(source), "rev-parse", "HEAD"]),
        "tree": run(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"]),
    }


def build_anchor(base: Path, parent: Path, pins: list[dict], ref: str) -> tuple[Path, dict]:
    evidence = base / "evidence"
    pins_file = base / f"{ref.rsplit('/', 1)[-1]}-pins.json"
    pins_file.write_text(
        json.dumps({"helper": csp.HELPER_PATH, "repositories": pins}), encoding="utf-8"
    )
    provenance = csp.build_anchor(parent, pins_file, ref, evidence, "fixture")
    return evidence, provenance


def task_specs(pins: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    repositories, pairs, tasks = [], [], []
    for index, pin in enumerate(pins):
        repositories.append(
            {
                "repo_id": pin["repo_id"],
                "canonical_name": f"fixture/{pin['repo_id']}",
                "upstream_commit": pin["commit"],
                "upstream_tree": pin["tree"],
                "license_spdx": "MIT",
                "license_notice": f"LICENSE in {pin['repo_id']}",
            }
        )
        pairs.append({"old_pair_id": f"old-pair-{index}", "repo_id": pin["repo_id"]})
        for arm in ("A", "B"):
            tasks.append(
                {
                    "old_task_id": f"old-task-{index}-{arm}",
                    "old_pair_id": f"old-pair-{index}",
                    "repo_id": pin["repo_id"],
                    "arm": arm,
                    "acceptance": f"Fixture acceptance text for {index} arm {arm}.",
                    "focused_test_target": "tests/test_lib.py",
                    "focused_test_command": "true",
                    "import_name": "lib",
                    "import_path": ".",
                }
            )
    return repositories, pairs, tasks


def freeze_plan(
    base: Path,
    parent: Path,
    pins: list[dict],
    evidence: Path,
    anchor: dict,
    run_id: str = "csp-run-20261115-abcdef",
    selection: dict | None = None,
    capture_policy: str | None = None,
) -> dict:
    repositories, pairs, tasks = task_specs(pins)
    spec = {
        "run_id": run_id,
        "coding_selection": selection if selection is not None else csp.CODING_MODEL,
        "parent_commit": anchor["parent_commit"],
        "repositories": repositories,
        "pairs": pairs,
        "tasks": tasks,
        "instructions": ["fixture run"],
    }
    if capture_policy is not None:
        spec["capture_policy"] = capture_policy
    spec_file = base / f"{run_id}-spec.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    return csp.prepare_plan(
        spec_file,
        parent,
        evidence,
        "fixture",
        anchor["ref"],
        anchor["commit"],
    )


def add_worktree(parent: Path, base: Path, anchor_commit: str, name: str) -> Path:
    worktree = base / name
    run(["git", "-C", str(parent), "worktree", "add", "-q", "--detach", str(worktree), anchor_commit])
    return worktree


def live_metadata(
    run_id: str = "run-1",
    status: str = "completed",
    model: str = "opencode-go/deepseek-v4.1-flash",
    provider: str = "opencode",
    seconds: float = 30.0,
) -> dict:
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    end = dt.datetime.now(dt.timezone.utc)
    return {
        "runId": run_id,
        "status": status,
        "providerInstanceId": provider,
        "model": model,
        "options": [{"id": "variant", "value": "max"}],
        "fast": False,
        "priority": False,
        "createdAt": start.isoformat(),
        "completedAt": end.isoformat(),
    }


def change_line(worktree: Path, prefix: str, line_index: int, value: str) -> None:
    path = worktree / prefix / "lib.py"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[line_index] = value + "\n"
    path.write_text("".join(lines), encoding="utf-8")


def capture_for(task: dict, worktree: Path, root: Path) -> dict:
    return csp.capture(
        task["task_id"],
        worktree,
        task["source_prefix"],
        task["upstream_tree"],
        task["upstream_commit"],
        root,
        "fixture",
    )


def collect_for(task: dict, worktree: Path, root: Path) -> dict:
    return csp.collect(task["task_id"], worktree, root, "fixture")


def run_record(task: dict, root: Path, **kwargs) -> dict:
    return csp.record_run(task["task_id"], live_metadata(**kwargs), root, "fixture")


class AnchorBuildTests(unittest.TestCase):
    def test_anchor_matches_upstream_subtrees_and_preserves_parent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = make_parent(base)
            pins = [
                make_source(base, "alpha", "one\ntwo\nthree\n"),
                make_source(base, "beta", "red\ngreen\nblue\n"),
            ]
            before_head = run(["git", "-C", str(parent), "rev-parse", "HEAD"])
            before_branch = run(["git", "-C", str(parent), "branch", "--show-current"])
            before_index = run(["git", "-C", str(parent), "write-tree"])
            before_status = run(["git", "-C", str(parent), "status", "--porcelain=v2"])
            _, provenance = build_anchor(base, parent, pins, "refs/research/fixture-anchor")
            self.assertTrue(provenance["original_state_preserved"])
            self.assertEqual(run(["git", "-C", str(parent), "rev-parse", "HEAD"]), before_head)
            self.assertEqual(run(["git", "-C", str(parent), "branch", "--show-current"]), before_branch)
            self.assertEqual(run(["git", "-C", str(parent), "write-tree"]), before_index)
            self.assertEqual(run(["git", "-C", str(parent), "status", "--porcelain=v2"]), before_status)
            anchor_tree = provenance["anchor"]["tree"]
            for pin in pins:
                subtree = run(
                    ["git", "-C", str(parent), "rev-parse", f"{anchor_tree}:controlled_sources/{pin['repo_id']}"]
                )
                self.assertEqual(subtree, pin["tree"])
            self.assertEqual(
                run(["git", "-C", str(parent), "rev-parse", f"{anchor_tree}:{csp.HELPER_PATH}"]),
                run(["git", "-C", str(parent), "hash-object", str(HELPER)]),
            )
            self.assertEqual(provenance["anchor"]["parent_commit"], before_head)

    def test_parent_may_already_track_the_same_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = make_parent(base)
            run(["git", "-C", str(parent), "add", csp.HELPER_PATH])
            run(["git", "-C", str(parent), "commit", "-qm", "track the recorder"])
            pins = [make_source(base, "alpha", "one\ntwo\nthree\n")]
            _, provenance = build_anchor(base, parent, pins, "refs/research/fixture-helper")
            helper = run(
                ["git", "-C", str(parent), "rev-parse", f"{provenance['anchor']['tree']}:{csp.HELPER_PATH}"]
            )
            self.assertEqual(
                helper, run(["git", "-C", str(parent), "hash-object", str(HELPER)])
            )
            (parent / csp.HELPER_PATH).write_text("different helper\n", encoding="utf-8")
            with self.assertRaisesRegex(csp.PilotError, "different"):
                build_anchor(base, parent, pins, "refs/research/fixture-helper-2")

    def test_existing_anchor_ref_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = make_parent(base)
            pins = [make_source(base, "alpha", "one\ntwo\nthree\n")]
            _, provenance = build_anchor(base, parent, pins, "refs/research/fixture-collision")
            with self.assertRaisesRegex(csp.PilotError, "refusing to overwrite"):
                build_anchor(base, parent, pins, "refs/research/fixture-collision")
            self.assertEqual(
                run(["git", "-C", str(parent), "rev-parse", "refs/research/fixture-collision"]),
                provenance["anchor"]["commit"],
            )


class CaptureTests(unittest.TestCase):
    def make_fixture(self, base: Path) -> tuple[Path, dict, Path, dict]:
        parent = make_parent(base)
        pins = [make_source(base, "alpha", "one\ntwo\nthree\n")]
        evidence, provenance = build_anchor(base, parent, pins, "refs/research/fixture-capture")
        csp.dump_json(
            evidence / "run.json",
            {
                "run_id": "csp-run-20261115-abcdef",
                "namespace": "fixture",
                "anchor": provenance["anchor"],
            },
        )
        worktree = add_worktree(parent, base, provenance["anchor"]["commit"], "wt-capture")
        task = {
            "task_id": "csp-task-" + "a" * 16,
            "source_prefix": "controlled_sources/alpha",
            "upstream_tree": pins[0]["tree"],
            "upstream_commit": pins[0]["commit"],
        }
        return evidence, provenance, worktree, task

    def test_capture_records_full_source_inventory_and_parent_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, provenance, worktree, task = self.make_fixture(base)
            record = capture_for(task, worktree, evidence)
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            self.assertEqual(record["original_source"]["actual_subtree_tree"], task["upstream_tree"])
            self.assertEqual(record["original_source"]["inventory_sha256"], csp.inventory_digest(
                record["original_source"]["inventory"]
            ))
            self.assertEqual(record["parent_snapshot"]["head"], provenance["anchor"]["commit"])
            self.assertNotEqual(record["parent_snapshot"]["tree"], task["upstream_tree"])
            self.assertTrue(record["parent_versus_upstream"]["distinct_ids"])
            self.assertEqual(record["evidence_namespace"], "fixture")

    def test_dirty_start_and_out_of_prefix_files_block_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, _, worktree, task = self.make_fixture(base)
            (worktree / "stray.txt").write_text("outside the prefix\n", encoding="utf-8")
            record = capture_for(task, worktree, evidence)
            self.assertFalse(record["verdict"]["ok"])
            self.assertTrue(any("dirty" in problem for problem in record["verdict"]["problems"]))
            self.assertIn("stray.txt", record["scope"]["changes_outside_prefix"])

    def test_wrong_or_missing_source_subtree_blocks_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, _, worktree, task = self.make_fixture(base)
            wrong = dict(task, upstream_tree="0" * 40)
            record = capture_for(wrong, worktree, evidence)
            self.assertFalse(record["verdict"]["ok"])
            missing = dict(task, task_id="csp-task-" + "c" * 16, source_prefix="controlled_sources/absent")
            missing_record = capture_for(missing, worktree, evidence)
            self.assertFalse(missing_record["verdict"]["ok"])
            self.assertIn(
                "assigned source subtree is missing: controlled_sources/absent",
                missing_record["verdict"]["problems"],
            )
            capture_path = csp.capture_path(evidence, task["task_id"])
            self.assertFalse(json.loads(capture_path.read_text())["verdict"]["ok"])


class CollectTests(unittest.TestCase):
    def make_fixture(self, base: Path, *, dir_symlink: bool = False) -> tuple[Path, Path, dict]:
        parent = make_parent(base)
        pins = [make_source(base, "alpha", "one\ntwo\nthree\nfour\nfive\n", dir_symlink=dir_symlink)]
        evidence, provenance = build_anchor(base, parent, pins, "refs/research/fixture-collect")
        csp.dump_json(
            evidence / "run.json",
            {
                "run_id": "csp-run-20261115-abcdef",
                "namespace": "fixture",
                "anchor": provenance["anchor"],
            },
        )
        worktree = add_worktree(parent, base, provenance["anchor"]["commit"], "wt-collect")
        task = {
            "task_id": "csp-task-" + "b" * 16,
            "source_prefix": "controlled_sources/alpha",
            "upstream_tree": pins[0]["tree"],
            "upstream_commit": pins[0]["commit"],
        }
        self.assertTrue(capture_for(task, worktree, evidence)["verdict"]["ok"])
        return evidence, worktree, task

    def test_collect_captures_new_binary_exec_artifact_and_replays_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, worktree, task = self.make_fixture(base)
            prefix = worktree / task["source_prefix"]
            change_line(worktree, task["source_prefix"], 1, "TWO")
            (prefix / "payload.bin").write_bytes(b"\x00\xfe\xffbinary")
            tool = prefix / "tool.sh"
            tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
            cache = prefix / ".pytest_cache" / "v" / "cache"
            cache.mkdir(parents=True)
            (cache / "lastfailed").write_text("{}", encoding="utf-8")
            record = collect_for(task, worktree, evidence)
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            self.assertTrue(record["replay_ok"])
            self.assertEqual(len(set(record["replay_trees"])), 1)
            self.assertEqual(record["replay_trees"][0], record["final_source_tree"])
            self.assertTrue({"lib.py", "payload.bin", "tool.sh"}.issubset(record["changed_paths"]))
            self.assertIn(".pytest_cache/v/cache/lastfailed", record["artifacts"])
            patch = (evidence / record["patch_file"]).read_bytes()
            self.assertIn(b"GIT binary patch", patch)
            self.assertIn(b"new file mode 100755", patch)
            self.assertTrue(record["nonempty"])
            self.assertTrue(Path(record["scratch"]).is_dir())
            self.assertEqual(record["evidence_namespace"], "fixture")

    def test_out_of_prefix_edits_and_empty_dirs_block_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, worktree, task = self.make_fixture(base)
            (worktree / "README.md").write_text("changed outside\n", encoding="utf-8")
            (worktree / "scratch-dir").mkdir()
            record = collect_for(task, worktree, evidence)
            self.assertFalse(record["verdict"]["ok"])
            self.assertIn("README.md", record["changed_paths_outside_prefix"])
            self.assertIn("scratch-dir", record["empty_dirs_outside_prefix"])
            self.assertFalse(record["nonempty"])

    def test_an_untouched_source_tree_is_an_empty_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, worktree, task = self.make_fixture(base)
            record = collect_for(task, worktree, evidence)
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            self.assertFalse(record["nonempty"])
            self.assertTrue(record["source_tree_unchanged"])
            self.assertEqual(record["patch_bytes"], 0)
            self.assertTrue(record["replay_ok"])

    def test_directory_symlinks_are_inventoried_and_captured(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, worktree, task = self.make_fixture(base, dir_symlink=True)
            change_line(worktree, task["source_prefix"], 1, "TWO")
            record = collect_for(task, worktree, evidence)
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            rows = {row["path"]: row for row in record["final_inventory"]}
            self.assertIn("tests/ca", rows)
            self.assertEqual(rows["tests/ca"]["mode"], "120000")
            self.assertTrue(record["replay_ok"])

    def test_collection_refuses_an_invalid_start_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence, worktree, task = self.make_fixture(base)
            path = csp.capture_path(evidence, task["task_id"])
            saved = json.loads(path.read_text())
            saved["verdict"] = {"ok": False, "problems": ["fixture drift"], "label_blocked": True}
            csp.dump_json(path, saved)
            with self.assertRaisesRegex(csp.PilotError, "not valid"):
                collect_for(task, worktree, evidence)


class PlanAndReplayTests(unittest.TestCase):
    def make_fixture(self, base: Path) -> dict:
        parent = make_parent(base)
        pins = [
            make_source(base, f"repo{i}", f"one\n two\n three\n four\n five\n{i}\n") for i in range(5)
        ]
        evidence, provenance = build_anchor(base, parent, pins, "refs/research/fixture-plan")
        plan = freeze_plan(base, parent, pins, evidence, provenance["anchor"])
        return {"parent": parent, "pins": pins, "evidence": evidence,
                "provenance": provenance, "plan": plan}

    def launch(self, fixture: dict, task: dict, index: int, edit: int | None, **run_kwargs) -> dict:
        worktree = add_worktree(
            fixture["parent"], fixture["evidence"].parent, fixture["provenance"]["anchor"]["commit"],
            f"wt-{task['task_id']}",
        )
        cap = capture_for(task, worktree, fixture["evidence"])
        self.assertTrue(cap["verdict"]["ok"], cap["verdict"]["problems"])
        if edit is not None:
            change_line(worktree, task["source_prefix"], edit, f"changed-{index}")
        output = collect_for(task, worktree, fixture["evidence"])
        self.assertTrue(output["verdict"]["ok"], output["verdict"]["problems"])
        run = run_record(task, fixture["evidence"], run_id=f"run-{index}", **run_kwargs)
        return {"worktree": worktree, "capture": cap, "output": output, "run": run}

    def test_plan_freezes_ten_isolated_prompts_and_new_model_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = self.make_fixture(base)
            plan = fixture["plan"]
            evidence = fixture["evidence"]
            self.assertEqual(len(plan["tasks"]), 10)
            self.assertEqual(len(plan["pairs"]), 5)
            self.assertEqual(plan["coding_selection"]["model"], "opencode-go/deepseek-v4.1-flash")
            self.assertEqual(plan["coding_selection"]["options"], [{"id": "variant", "value": "max"}])
            csp.validate_plan(plan, evidence)
            all_task_ids = {task["task_id"] for task in plan["tasks"]}
            all_pair_ids = {pair["pair_id"] for pair in plan["pairs"]}
            for task in plan["tasks"]:
                text = (evidence / task["prompt_file"]).read_text(encoding="utf-8")
                self.assertIn(task["source_prefix"], text)
                self.assertIn(task["upstream_tree"], text)
                self.assertIn("scripts/controlled_single_project.py capture", text)
                other_tasks = all_task_ids - {task["task_id"]}
                self.assertFalse([task_id for task_id in other_tasks if task_id in text])
                self.assertFalse([pair_id for pair_id in all_pair_ids if pair_id in text])
                for other in plan["tasks"]:
                    if other["task_id"] != task["task_id"]:
                        self.assertNotIn(other["acceptance"], text)

    def test_plan_rejects_a_different_model_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = make_parent(base)
            pins = [make_source(base, f"repo{i}", "one\ntwo\n") for i in range(5)]
            evidence, provenance = build_anchor(base, parent, pins, "refs/research/fixture-model")
            bad = dict(csp.CODING_MODEL, model="claude-haiku-5.5")
            with self.assertRaisesRegex(csp.PilotError, "DeepSeek"):
                freeze_plan(base, parent, pins, evidence, provenance["anchor"], selection=bad)

    def test_clean_and_conflict_labels_from_real_merge_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = self.make_fixture(base)
            plan = fixture["plan"]
            clean_pair = plan["pairs"][0]
            clean_tasks = [task for task in plan["tasks"] if task["pair_id"] == clean_pair["pair_id"]]
            self.launch(fixture, clean_tasks[0], 0, 0)
            self.launch(fixture, clean_tasks[1], 1, 2)
            clean = csp.replay_pair(clean_pair["pair_id"], fixture["evidence"])
            self.assertEqual(clean["label"], "clean", clean["exclusion_reasons"])
            self.assertTrue(clean["merge_repeats_identical"])
            self.assertTrue(clean["qualifies"])

            conflict_pair = plan["pairs"][1]
            conflict_tasks = [task for task in plan["tasks"] if task["pair_id"] == conflict_pair["pair_id"]]
            self.launch(fixture, conflict_tasks[0], 2, 0)
            self.launch(fixture, conflict_tasks[1], 3, 0)
            conflict = csp.replay_pair(conflict_pair["pair_id"], fixture["evidence"])
            self.assertEqual(conflict["label"], "conflict", conflict["exclusion_reasons"])
            self.assertTrue(conflict["merge_repeats_identical"])

            empty_pair = plan["pairs"][2]
            empty_tasks = [task for task in plan["tasks"] if task["pair_id"] == empty_pair["pair_id"]]
            self.launch(fixture, empty_tasks[0], 4, 0)
            self.launch(fixture, empty_tasks[1], 5, None)
            empty = csp.replay_pair(empty_pair["pair_id"], fixture["evidence"])
            self.assertIsNone(empty["label"])
            self.assertFalse(empty["qualifies"])
            self.assertIn("at least one output is empty", empty["exclusion_reasons"])

            status = csp.status_report(fixture["evidence"])
            self.assertEqual(len(status["pairs"]), 5)
            summary = csp.summarize(fixture["evidence"], False)
            self.assertEqual(len(summary["pairs"]), 5)
            self.assertEqual(summary["feasibility_gate"]["status"], "not_evaluated")

    def test_unequal_starts_and_missing_outputs_block_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = self.make_fixture(base)
            plan = fixture["plan"]
            pair = plan["pairs"][3]
            tasks = [task for task in plan["tasks"] if task["pair_id"] == pair["pair_id"]]
            self.launch(fixture, tasks[0], 6, 0)
            missing = csp.replay_pair(pair["pair_id"], fixture["evidence"])
            self.assertFalse(missing["attempted"])
            self.assertIsNone(missing["label"])
            self.assertIn("one or more task outputs were not collected", missing["exclusion_reasons"])
            self.assertIn("both coding runs were not confirmed started", missing["exclusion_reasons"])

            second = self.launch(fixture, tasks[1], 7, 1)
            saved = json.loads(csp.capture_path(fixture["evidence"], tasks[1]["task_id"]).read_text())
            first = json.loads(csp.capture_path(fixture["evidence"], tasks[0]["task_id"]).read_text())
            saved["original_source"]["upstream_tree"] = "f" * 40
            csp.dump_json(csp.capture_path(fixture["evidence"], tasks[1]["task_id"]), saved)
            equal, differences = csp.source_starts_match(first, saved)
            self.assertFalse(equal)
            self.assertIn("original_source.upstream_tree", differences)
            blocked = csp.replay_pair(pair["pair_id"], fixture["evidence"])
            self.assertIsNone(blocked["label"])
            self.assertIn("paired starts do not share the same original source tree", blocked["exclusion_reasons"])
            self.assertTrue(second["run"]["coding_started"])

    def test_run_record_uses_live_status_and_rejects_wrong_model(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fixture = self.make_fixture(base)
            plan = fixture["plan"]
            tasks = [plan["tasks"][0], plan["tasks"][2], plan["tasks"][4]]
            worktrees = []
            for index, task in enumerate(tasks):
                worktree = add_worktree(
                    fixture["parent"], fixture["evidence"].parent,
                    fixture["provenance"]["anchor"]["commit"], f"wt-live-{index}",
                )
                self.assertTrue(capture_for(task, worktree, fixture["evidence"])["verdict"]["ok"])
                worktrees.append(worktree)
            queued = csp.record_run(
                tasks[0]["task_id"], live_metadata(status="queued"), fixture["evidence"], "fixture"
            )
            self.assertFalse(queued["coding_started"])
            self.assertFalse(queued["provenance_ok"])
            wrong = csp.record_run(
                tasks[1]["task_id"], live_metadata(status="running", model="claude-haiku-5.5"),
                fixture["evidence"], "fixture",
            )
            self.assertFalse(wrong["selection_ok"])
            self.assertFalse(wrong["provenance_ok"])
            good = csp.record_run(
                tasks[2]["task_id"], live_metadata(status="running"), fixture["evidence"], "fixture"
            )
            self.assertTrue(good["coding_started"])
            self.assertTrue(good["selection_ok"])
            self.assertTrue(good["within_limits"])
            self.assertTrue(good["provenance_ok"])
            with self.assertRaisesRegex(csp.PilotError, "different run record"):
                csp.record_run(
                    tasks[2]["task_id"], live_metadata(status="completed"), fixture["evidence"], "fixture"
                )


class CapturePolicyTests(unittest.TestCase):
    def make_fixture(self, base: Path, policy: str) -> dict:
        parent = make_parent(base)
        pins = [make_ignoring_source(base, f"repo{i}") for i in range(5)]
        evidence, provenance = build_anchor(
            base, parent, pins, f"refs/research/fixture-policy-{policy}"
        )
        plan = freeze_plan(
            base,
            parent,
            pins,
            evidence,
            provenance["anchor"],
            capture_policy=policy,
        )
        task = plan["tasks"][0]
        worktree = add_worktree(
            parent, base, provenance["anchor"]["commit"], f"wt-policy-{policy}"
        )
        cap = capture_for(task, worktree, evidence)
        self.assertTrue(cap["verdict"]["ok"], cap["verdict"]["problems"])
        return {
            "base": base,
            "parent": parent,
            "pins": pins,
            "evidence": evidence,
            "plan": plan,
            "task": task,
            "worktree": worktree,
        }

    def add_ignored_outputs(self, fixture: dict) -> None:
        prefix = fixture["worktree"] / fixture["task"]["source_prefix"]
        change_line(fixture["worktree"], fixture["task"]["source_prefix"], 1, "TWO")
        (prefix / "new.log").write_text("ignored output\n", encoding="utf-8")
        cache = prefix / "__pycache__"
        cache.mkdir()
        (cache / "lib.cpython-311.pyc").write_bytes(b"\x00cache")

    def test_ordinary_policy_drops_ignored_outputs_and_keeps_tracked_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory), "ordinary-git-staging-v1")
            self.assertEqual(fixture["plan"]["capture_policy"], "ordinary-git-staging-v1")
            self.add_ignored_outputs(fixture)
            record = collect_for(fixture["task"], fixture["worktree"], fixture["evidence"])
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            self.assertEqual(record["capture_policy"]["name"], "ordinary-git-staging-v1")
            self.assertTrue(record["capture_policy"]["ordinary_git_staging"])
            self.assertEqual(len(record["staging"]["derived_source_trees"]), 2)
            self.assertEqual(len(set(record["staging"]["derived_source_trees"])), 1)
            self.assertEqual(
                record["staging"]["derived_source_tree"], record["final_source_tree"]
            )
            self.assertIn("lib.py", record["changed_paths"])
            self.assertNotIn("new.log", record["changed_paths"])
            self.assertNotIn("__pycache__/lib.cpython-311.pyc", record["changed_paths"])
            self.assertIn("new.log", record["staging"]["filesystem_only_paths"])
            inventory_paths = {row["path"] for row in record["final_inventory"]}
            self.assertIn("tracked.log", inventory_paths)
            self.assertTrue(record["replay_ok"])
            self.assertEqual(record["replay_trees"][0], record["final_source_tree"])

    def test_legacy_policy_keeps_force_added_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory), "full-directory-v3")
            self.add_ignored_outputs(fixture)
            record = collect_for(fixture["task"], fixture["worktree"], fixture["evidence"])
            self.assertTrue(record["verdict"]["ok"], record["verdict"]["problems"])
            self.assertEqual(record["capture_policy"]["name"], "full-directory-v3")
            self.assertFalse(record["capture_policy"]["ordinary_git_staging"])
            self.assertEqual(record["staging"]["derived_source_trees"], [])
            self.assertIn("new.log", record["changed_paths"])
            self.assertIn("__pycache__/lib.cpython-311.pyc", record["changed_paths"])
            self.assertIn("__pycache__/lib.cpython-311.pyc", record["artifacts"])
            self.assertTrue(record["replay_ok"])

    def test_collection_refuses_an_unknown_capture_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory), "ordinary-git-staging-v1")
            path = csp.capture_path(fixture["evidence"], fixture["task"]["task_id"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved["capture_policy"] = "invented-policy"
            csp.dump_json(path, saved)
            with self.assertRaisesRegex(csp.PilotError, "unknown capture policy"):
                collect_for(fixture["task"], fixture["worktree"], fixture["evidence"])


class LabelAndNamespaceTests(unittest.TestCase):
    def test_empty_error_conflict_and_missing_checks(self):
        clean = [{"returncode": 0, "stdout": "tree\n", "stderr": "", "timed_out": False}] * 2
        self.assertIsNone(csp.label_from_repeats(
            clean, starts_equal=True, nonempty=[False, True], outputs_distinct=True,
            replay_ok=True, within_limits=True, provenance_ok=True))
        error = [{"returncode": 2, "stdout": "", "stderr": "fatal", "timed_out": False}] * 2
        self.assertIsNone(csp.label_from_repeats(
            error, starts_equal=True, nonempty=[True, True], outputs_distinct=True,
            replay_ok=True, within_limits=True, provenance_ok=True))
        conflict = [{"returncode": 1, "stdout": "CONFLICT (content)", "stderr": "", "timed_out": False}] * 2
        self.assertEqual(csp.label_from_repeats(
            conflict, starts_equal=True, nonempty=[True, True], outputs_distinct=True,
            replay_ok=True, within_limits=True, provenance_ok=True), "conflict")
        self.assertIsNone(csp.label_from_repeats(
            clean, starts_equal=False, nonempty=[True, True], outputs_distinct=True,
            replay_ok=True, within_limits=True, provenance_ok=True))
        self.assertIsNone(csp.label_from_repeats(
            clean, starts_equal=True, nonempty=[True, True], outputs_distinct=False,
            replay_ok=True, within_limits=True, provenance_ok=True))

    def test_fixture_namespace_cannot_touch_the_real_evidence_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIn("real evidence", csp.namespace_problem(root, "real"))
            self.assertIn("fixture evidence", csp.namespace_problem(csp.DEFAULT_EVIDENCE_ROOT, "fixture"))
            self.assertIn("unknown", csp.namespace_problem(root, "other"))
            self.assertIsNone(csp.namespace_problem(root, "fixture"))
            marker = csp.evidence_root(root, "fixture", create=True)
            self.assertEqual(marker, root.resolve())
            with self.assertRaisesRegex(csp.PilotError, "real evidence"):
                csp.evidence_root(root, "real", create=False)
            (root / "namespace.json").write_text(
                json.dumps({"namespace": "real", "protocol_version": csp.PROTOCOL_VERSION}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(csp.PilotError, "marker"):
                csp.evidence_root(root, "fixture", create=True)

    def test_bounded_run_keeps_owner_pid_deadline_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "evidence"
            csp.evidence_root(root, "fixture", create=True)
            csp.dump_json(
                root / "run.json",
                {"run_id": "csp-run-20261115-abcdef", "namespace": "fixture",
                 "anchor": {"commit": "0" * 40, "tree": "0" * 40}},
            )
            code = csp.main(
                [
                    "run", "--task-id", "csp-task-" + "c" * 16,
                    "--evidence-root", str(root), "--run-id", "csp-run-20261115-abcdef",
                    "--namespace", "fixture", "--cwd", str(base),
                    "--timeout-seconds", "5", "--", "python3", "-c", "raise SystemExit(7)",
                ]
            )
            self.assertEqual(code, 7)
            logs = list((root / "outputs" / ("csp-task-" + "c" * 16) / "jobs").glob("*.json"))
            self.assertEqual(len(logs), 1)
            job = json.loads(logs[0].read_text(encoding="utf-8"))
            self.assertEqual((job["owner"], job["returncode"], job["timed_out"]), ("csp-task-" + "c" * 16, 7, False))
            self.assertGreater(job["pid"], 0)
            self.assertIn("deadline_at", job)
            self.assertEqual(job["evidence_namespace"], "fixture")


if __name__ == "__main__":
    unittest.main()
