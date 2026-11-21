import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_controlled_pilot as analysis


class GitFixture:
    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "base-repo"
        self.repo.mkdir()
        self.env = analysis.sanitized_env(root / "home")
        (root / "home").mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write({"a.txt": "base a\n", "b.txt": "base b\n", ".gitignore": "cache/\n"},
                   name=".")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base_tree = self.git("rev-parse", "HEAD^{tree}")["stdout"].strip()
        self.objects = self.repo / ".git" / "objects"

    def git(self, *args, cwd=None):
        return analysis.run_cmd(["git"] + list(args), cwd or self.repo, self.env)

    def write(self, files: dict, name: str = "side") -> Path:
        side = self.root / name if name != "." else self.repo
        if name != "." and side.exists():
            shutil.rmtree(side)
        side.mkdir(exist_ok=(name == "."))
        for path, content in files.items():
            target = side / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content)
        return side

    def derive(self, name: str, files: dict, base_tree=None):
        side = self.write(files, name)
        git_dir = self.root / f"git-{name}"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        analysis.init_temp_git(git_dir, self.objects, self.env)
        result = analysis.derive_tree(git_dir, side, base_tree or self.base_tree, self.env, 30)
        return side, git_dir, result


class ControlledAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="controlled-test-"))
        self.fx = GitFixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_public_producer_path_is_repository_relative(self):
        absolute = Path("/home/example/Project/scripts/analyze_controlled_pilot.py")
        self.assertEqual(analysis.public_producer_path(absolute),
                         "scripts/analyze_controlled_pilot.py")
        self.assertEqual(analysis.public_producer_path(Path("analyze_controlled_pilot.py")),
                         "analyze_controlled_pilot.py")

    def test_public_text_redacts_absolute_paths(self):
        for value in [
            "see /home/example/repo/test.py:12",
            "see C:/Users/example/test.py",
            "see C:\\Users\\example\\test.py",
            "see \\\\server\\share\\test.py",
            "see /srv/builds/foo",
            'see "/home/example/my project/test.py"',
        ]:
            self.assertEqual(analysis.public_text(value), "<redacted>")
        self.assertEqual(analysis.public_text("1 passed in 0.1s"), "1 passed in 0.1s")

    def test_public_basename_handles_windows_and_posix(self):
        self.assertEqual(analysis.public_basename("C:\\Users\\example\\job.json"), "job.json")
        self.assertEqual(analysis.public_basename("\\\\server\\share\\job.json"), "job.json")
        self.assertEqual(analysis.public_basename("/home/example/job.json"), "job.json")

    def test_test_audit_sanitizes_absolute_paths(self):
        evidence = self.tmp / "evidence"
        evidence.mkdir()
        payload = {"tasks": [{"task_id": "t", "repo": "r", "test_jobs": [
            {"file": "C:\\Users\\example\\job.json", "returncode": 0,
             "stdout_tail": "setup from C:\\Users\\example\\repo\n1 passed in 0.1s\n"},
            {"file": "/home/example/job2.json", "returncode": 1,
             "stdout_tail": "FAILED /home/example/repo/tests/test_x.py\n"}]}]}
        (evidence / "root-job-audit.json").write_text(json.dumps(payload))
        audit = analysis.load_test_audit(evidence)
        self.assertEqual(audit["t"]["jobs"][0]["job_file"], "job.json")
        self.assertEqual(audit["t"]["jobs"][0]["summary_line"], "1 passed in 0.1s")
        self.assertEqual(audit["t"]["jobs"][1]["job_file"], "job2.json")
        self.assertEqual(audit["t"]["jobs"][1]["summary_line"], "<redacted>")
        rendered = json.dumps(audit)
        self.assertNotIn("C:\\\\", rendered)
        self.assertNotIn("/home/", rendered)

    def test_ignored_cache_differences_leave_independent_source_clean(self):
        _, git_a, a = self.fx.derive("a", {"a.txt": "A\n", "b.txt": "base b\n",
                                           ".gitignore": "cache/\n", "cache/junk": "A cache\n"})
        _, git_b, b = self.fx.derive("b", {"a.txt": "base a\n", "b.txt": "B\n",
                                           ".gitignore": "cache/\n", "cache/junk": "B cache\n"})
        self.assertTrue(a["ok"] and b["ok"])
        tree_a, tree_b = a["tree"], b["tree"]
        paths_a = analysis.ls_tree(git_a, tree_a, self.fx.env)[0]
        self.assertNotIn("cache/junk", paths_a)
        merge_git = self.tmp / "merge"
        analysis.init_temp_git(merge_git, self.fx.objects, self.fx.env)
        analysis.add_alternates(merge_git, [git_a / "objects", git_b / "objects"])
        merge = analysis.merge_trees(merge_git, self.fx.base_tree, [tree_a, tree_b],
                                     self.fx.env, 30)
        self.assertEqual(merge["status"], "clean")
        self.assertTrue(merge["identical_repeats"])

    def test_genuine_tracked_conflict_is_reported(self):
        _, git_a, a = self.fx.derive("a", {"a.txt": "side A\n"})
        _, git_b, b = self.fx.derive("b", {"a.txt": "side B\n"})
        merge_git = self.tmp / "merge"
        analysis.init_temp_git(merge_git, self.fx.objects, self.fx.env)
        analysis.add_alternates(merge_git, [git_a / "objects", git_b / "objects"])
        merge = analysis.merge_trees(merge_git, self.fx.base_tree, [a["tree"], b["tree"]],
                                     self.fx.env, 30)
        self.assertEqual(merge["status"], "conflict")
        self.assertIn("a.txt", {c["path"] for c in merge["conflicts"]})

    def test_binary_new_file_survives_patch_replay(self):
        side, git_dir, derived = self.fx.derive(
            "a", {"a.txt": "base a\n", "b.txt": "base b\n", ".gitignore": "cache/\n",
                  "bin/new.dat": b"\x00\x01\x02\xffbinary"})
        patch = analysis.patch_and_replay(
            git_dir, self.fx.base_tree, derived["tree"], self.tmp / "patch" / "a.patch",
            self.fx.env, 30)
        self.assertTrue(patch["ok"])
        self.assertEqual(patch["replayed_tree"], derived["tree"])
        self.assertIn("bin/new.dat", analysis.ls_tree(git_dir, derived["tree"], self.fx.env)[0])

    def test_validation_rejects_later_file_and_unknown_merge_is_not_clean(self):
        side, git_dir, derived = self.fx.derive("a", {"a.txt": "A\n"})
        captured, _ = analysis.ls_tree(git_dir, self.fx.base_tree, self.fx.env)
        (side / "later.txt").write_text("added after capture\n")
        analysis.git(git_dir, ["read-tree", self.fx.base_tree], None, git_dir, self.fx.env)
        analysis.git(git_dir, ["add", "-A", "."], side, side, self.fx.env)
        later_tree = analysis.git(git_dir, ["write-tree"], None, git_dir, self.fx.env)["stdout"].strip()
        validation = analysis.validate_derived(git_dir, later_tree, self.fx.base_tree,
                                               side, self.fx.env)
        self.assertFalse(validation["ok"])
        self.assertTrue(any(i.startswith("not_in_capture:later.txt") for i in validation["issues"]))
        merge_git = self.tmp / "merge"
        analysis.init_temp_git(merge_git, self.fx.objects, self.fx.env)
        merge = analysis.merge_trees(merge_git, "0" * 40, [self.fx.base_tree, self.fx.base_tree],
                                     self.fx.env, 30)
        self.assertEqual(merge["status"], "error")
        self.assertNotEqual(merge["status"], "clean")

    def test_directory_inventory_is_read_only_and_stable(self):
        side, _, _ = self.fx.derive("a", {"a.txt": "A\n"})
        first = analysis.directory_inventory(side)
        second = analysis.directory_inventory(side)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertGreaterEqual(first["count"], 1)


if __name__ == "__main__":
    unittest.main()
