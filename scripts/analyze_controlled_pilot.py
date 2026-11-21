#!/usr/bin/env python3
"""Post-hoc ordinary-Git-visible diagnostic for the controlled single-project pilot.

This is a separately named development analysis. It does not relabel the frozen
full-directory captures. For every existing pair it derives a tree from the
actual final source directory exactly as ordinary Git staging would: start from
the pinned tree, stage tracked/new/nonignored files with `git add -A` in a new
temporary Git directory, and write the index as a tree. Ignored pyc/pytest-cache
files therefore drop out mechanically, with no per-case or per-category choice.

The script never writes to a coding worktree: it only reads source files and
uses a separate --git-dir/--work-tree for staging. Generated patches are written
privately. Public output is an allowlisted JSON file with hashes, statuses,
paths and merge facts only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PROTOCOL_VERSION = "controlled-single-project-posthoc-git-visible-1"
METHOD_ID = "posthoc-ordinary-git-staging-v1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "data/private/research/controlled-single-project-v3"
DEFAULT_OBJECTS = ROOT / ".git/objects"
DEFAULT_OUT = ROOT / "data/controlled-single-project/posthoc-git-visible.json"
DEFAULT_PRIVATE = DEFAULT_EVIDENCE / "supplemental"
COMMAND_TIMEOUT = 60


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_producer_path(path: Path) -> str:
    """Name the producer relative to its repository, never by absolute path."""
    parent = path.parent.name
    return f"{parent}/{path.name}" if parent else path.name


ABSOLUTE_MARKER_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\s\\]+\\|(?<![\w.])/[^\s]+)")


def public_basename(value: str) -> str:
    """Return the last path component for POSIX and Windows paths."""
    return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def public_text(value: str) -> str:
    """Drop a log line that contains any absolute path marker."""
    return "<redacted>" if ABSOLUTE_MARKER_RE.search(value) else value


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sanitized_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_AUTHOR_NAME": "controlled-analysis",
            "GIT_AUTHOR_EMAIL": "controlled-analysis@local.invalid",
            "GIT_COMMITTER_NAME": "controlled-analysis",
            "GIT_COMMITTER_EMAIL": "controlled-analysis@local.invalid",
            "HOME": str(home),
            "LC_ALL": "C",
            "TZ": "UTC",
        }
    )
    return env


def run_cmd(argv, cwd, env, timeout=COMMAND_TIMEOUT) -> dict:
    started = utc_now()
    t0 = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            [str(x) for x in argv],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            timed_out = True
        returncode = proc.returncode
    except OSError as exc:  # command could not even start
        out, err = b"", str(exc).encode()
        returncode = None
    return {
        "argv": [str(x) for x in argv],
        "cwd": str(cwd),
        "started_at": started,
        "duration_seconds": round(time.monotonic() - t0, 3),
        "pid": locals().get("proc").pid if "proc" in locals() else None,
        "returncode": returncode,
        "stdout": out.decode("utf-8", "replace"),
        "stderr": err.decode("utf-8", "replace"),
        "stdout_sha256": sha256_bytes(out),
        "stderr_sha256": sha256_bytes(err),
        "timed_out": timed_out,
    }


def git(git_dir: Path, args, work_tree: Path | None, cwd: Path, env, timeout=COMMAND_TIMEOUT) -> dict:
    argv = ["git", f"--git-dir={git_dir}"]
    if work_tree is not None:
        argv.append(f"--work-tree={work_tree}")
    return run_cmd(argv + list(args), cwd, env, timeout)


def init_temp_git(path: Path, alternates: Path | None, env) -> dict:
    path.mkdir(parents=True, exist_ok=False)
    result = run_cmd(["git", "init", "-q", "--bare", str(path)], path, env)
    if alternates is not None:
        (path / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (path / "objects" / "info" / "alternates").write_text(str(alternates) + "\n")
    return result


def add_alternates(path: Path, object_dirs) -> None:
    info = path / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    lines = []
    existing = info / "alternates"
    if existing.exists():
        lines = [line for line in existing.read_text().splitlines() if line.strip()]
    for directory in object_dirs:
        text = str(directory)
        if text not in lines:
            lines.append(text)
    existing.write_text("\n".join(lines) + "\n")


def ls_tree(git_dir: Path, tree: str, env) -> tuple[dict, dict]:
    result = git(git_dir, ["ls-tree", "-r", "-z", "--full-tree", tree], None, git_dir, env)
    entries = {}
    if result["returncode"] != 0:
        return entries, result
    for record in result["stdout"].split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, obj_type, obj_id = meta.split()
        entries[path] = {"mode": mode, "type": obj_type, "blob": obj_id}
    return entries, result


def path_blob(git_dir: Path, path: Path, mode: str) -> str:
    if mode == "120000":
        data = os.readlink(path).encode()
    else:
        data = path.read_bytes()
    return git_blob_sha1(data)


def derive_tree(git_dir: Path, work_tree: Path, base_tree: str, env, timeout) -> dict:
    """Stage normal Git-visible files from work_tree on top of base_tree."""
    commands = {}
    commands["read_tree"] = git(git_dir, ["read-tree", base_tree], None, git_dir, env, timeout)
    if commands["read_tree"]["returncode"] != 0:
        return {"ok": False, "commands": commands, "error": "read-tree failed"}
    commands["add"] = git(git_dir, ["add", "-A", "."], work_tree, work_tree, env, timeout)
    if commands["add"]["returncode"] != 0:
        return {"ok": False, "commands": commands, "error": "add failed"}
    commands["write_tree"] = git(git_dir, ["write-tree"], None, git_dir, env, timeout)
    if commands["write_tree"]["returncode"] != 0:
        return {"ok": False, "commands": commands, "error": "write-tree failed"}
    return {
        "ok": True,
        "tree": commands["write_tree"]["stdout"].strip(),
        "commands": commands,
    }


def validate_derived(git_dir, derived_tree, captured_tree, work_tree, env) -> dict:
    """Every staged file must byte-match the frozen capture, and no later file may appear."""
    derived, dcmd = ls_tree(git_dir, derived_tree, env)
    captured, ccmd = ls_tree(git_dir, captured_tree, env)
    issues = []
    if dcmd["returncode"] != 0 or ccmd["returncode"] != 0:
        return {"ok": False, "issues": ["ls-tree failed"], "derived_paths": len(derived)}
    absent_from_capture = sorted(set(derived) - set(captured))
    for path in absent_from_capture:
        issues.append(f"not_in_capture:{path}")
    for path, meta in sorted(derived.items()):
        if path not in captured:
            continue
        if captured[path]["blob"] != meta["blob"]:
            issues.append(f"content_mismatch:{path}")
        if captured[path]["mode"] != meta["mode"]:
            issues.append(f"mode_mismatch:{path}")
    excluded = sorted(set(captured) - set(derived))
    return {
        "ok": not issues,
        "issues": issues,
        "derived_paths": len(derived),
        "captured_paths": len(captured),
        "included_all_present_in_capture": not absent_from_capture,
        "content_matches_capture": not any(
            i.startswith(("content_mismatch", "unreadable", "mode_mismatch")) for i in issues
        ),
        "excluded_paths": excluded,
        "excluded_count": len(excluded),
    }


def tree_changes(git_dir, base_tree, derived_tree, env) -> list:
    result = git(
        git_dir,
        ["diff-tree", "-r", "-z", "--no-commit-id", "--name-status", base_tree, derived_tree],
        None,
        git_dir,
        env,
    )
    changes = []
    if result["returncode"] != 0:
        return changes
    fields = [f for f in result["stdout"].split("\0") if f]
    i = 0
    while i + 1 < len(fields):
        changes.append({"status": fields[i], "path": fields[i + 1]})
        i += 2
    return changes


def patch_and_replay(git_dir, base_tree, derived_tree, patch_path: Path, env, timeout) -> dict:
    diff = git(
        git_dir,
        ["diff", "--binary", "--full-index", "--no-color", "--no-ext-diff", "--no-textconv",
         base_tree, derived_tree],
        None,
        git_dir,
        env,
        timeout,
    )
    if diff["returncode"] != 0:
        return {"ok": False, "diff": diff, "error": "diff failed"}
    patch_bytes = diff["stdout"].encode()
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(patch_bytes)
    replay_dir = patch_path.parent / (patch_path.stem + "-replay-git")
    replay_work = patch_path.parent / (patch_path.stem + "-replay-work")
    for path in (replay_dir, replay_work):
        if path.exists():
            shutil.rmtree(path)
    init = init_temp_git(replay_dir, None, env)
    add_alternates(replay_dir, [git_dir / "objects"])
    replay_work.mkdir()
    replay = {"init": init}
    replay["read_tree"] = git(replay_dir, ["read-tree", base_tree], None, replay_dir, env, timeout)
    replay["checkout"] = git(
        replay_dir, ["checkout-index", "-a", "-f"], replay_work, replay_work, env, timeout
    )
    replay["apply"] = git(
        replay_dir, ["apply", "--binary", str(patch_path)], replay_work, replay_work, env, timeout
    )
    replay["add"] = git(replay_dir, ["add", "-A", "."], replay_work, replay_work, env, timeout)
    replay["write_tree"] = git(replay_dir, ["write-tree"], None, replay_dir, env, timeout)
    tree = replay["write_tree"]["stdout"].strip() if replay["write_tree"]["returncode"] == 0 else None
    ok = (
        replay["read_tree"]["returncode"] == 0
        and replay["checkout"]["returncode"] == 0
        and replay["apply"]["returncode"] == 0
        and replay["add"]["returncode"] == 0
        and replay["write_tree"]["returncode"] == 0
        and tree == derived_tree
    )
    return {
        "ok": ok,
        "patch_sha256": sha256_bytes(patch_bytes),
        "patch_bytes": len(patch_bytes),
        "patch_path": str(patch_path),
        "replayed_tree": tree,
        "commands": replay,
    }


def parse_conflicts(stdout: str) -> dict:
    conflicts, messages = [], []
    for line in stdout.splitlines():
        m = re.match(r"^(\d{6}) ([0-9a-f]+) (\d)\t(.+)$", line)
        if m:
            conflicts.append({"mode": m.group(1), "blob": m.group(2), "stage": int(m.group(3)),
                              "path": m.group(4)})
        elif line.startswith(("CONFLICT", "Auto-merging", "warning:")):
            messages.append(line)
    return {"entries": conflicts, "messages": messages}


def merge_trees(git_dir, base_tree, side_trees, env, timeout) -> dict:
    """Create base/side commits in a temp repo and run merge-tree twice."""
    commits = {"base_tree": base_tree, "side_trees": list(side_trees)}
    base_commit = git(git_dir, ["commit-tree", base_tree, "-m", "posthoc base"], None, git_dir, env, timeout)
    commits["base"] = base_commit
    side_commits = []
    for n, tree in enumerate(side_trees):
        side_commits.append(
            git(git_dir, ["commit-tree", tree, "-p", base_commit["stdout"].strip(),
                          "-m", f"posthoc side {n}"], None, git_dir, env, timeout)
        )
    commits["sides"] = side_commits
    if base_commit["returncode"] != 0 or any(c["returncode"] != 0 for c in side_commits):
        return {"status": "error", "error": "commit-tree failed", "commits": commits, "runs": []}
    argv = ["git", f"--git-dir={git_dir}", "merge-tree", "--write-tree",
            side_commits[0]["stdout"].strip(), side_commits[1]["stdout"].strip()]
    runs = [run_cmd(argv, git_dir, env, timeout) for _ in range(2)]
    identical = (
        runs[0]["returncode"] == runs[1]["returncode"]
        and runs[0]["stdout_sha256"] == runs[1]["stdout_sha256"]
    )
    codes = {r["returncode"] for r in runs}
    parsed = parse_conflicts(runs[0]["stdout"])
    first_line = runs[0]["stdout"].splitlines()[0].strip() if runs[0]["stdout"].strip() else None
    if not identical:
        status = "error"
        detail = "repeated merge-tree outputs differ"
    elif codes == {0}:
        status = "clean"
        detail = None
    elif codes == {1}:
        status = "conflict" if first_line and re.fullmatch(r"[0-9a-f]{40,64}", first_line) else "error"
        detail = None if status == "conflict" else "merge-tree exit 1 without a result tree"
    else:
        status = "error"
        detail = f"unexpected merge-tree exit codes {sorted(c for c in codes if c is not None)}"
    if not identical or runs[0]["timed_out"]:
        detail = "merge-tree was not repeatable or timed out"
    return {
        "status": status,
        "detail": detail,
        "identical_repeats": identical,
        "merge_tree": first_line,
        "conflicts": parsed["entries"],
        "messages": parsed["messages"],
        "commits": commits,
        "runs": runs,
    }


def tree_size(git_dir, tree, env) -> int:
    entries, _ = ls_tree(git_dir, tree, env)
    total = 0
    for path, meta in entries.items():
        if meta["type"] != "blob":
            continue
        obj = git(git_dir, ["cat-file", "-s", meta["blob"]], None, git_dir, env)
        if obj["returncode"] == 0:
            total += int(obj["stdout"].strip() or 0)
    return total


def load_replay_labels(evidence: Path) -> dict:
    labels = {}
    for path in sorted(evidence.glob("replay-*.log")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "pair_id" in record:
                labels.setdefault(record["pair_id"], {})[record.get("repo_id")] = record
    return labels


def load_test_audit(evidence: Path) -> dict:
    path = evidence / "root-job-audit.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    out = {}
    for task in data.get("tasks", []):
        jobs = []
        for job in task.get("test_jobs", []):
            tail = [line for line in job.get("stdout_tail", "").splitlines() if line.strip()]
            summary = tail[-1].strip() if tail else None
            jobs.append({
                "job_file": public_basename(job.get("file", "")),
                "returncode": job.get("returncode"),
                "summary_line": public_text(summary) if summary else None,
            })
        out[task["task_id"]] = {"repo_id": task.get("repo"), "jobs": jobs}
    return out


def analyze_task(record, capture, objects: Path, work_root: Path, private_root: Path,
                 env, timeout) -> dict:
    task_id = record["task_id"]
    source = Path(record["worktree"]) / capture["original_source"]["subtree_path_in_parent"]
    base_tree = capture["original_source"]["upstream_tree"]
    captured_tree = record["final_source_tree"]
    out = {
        "task_id": task_id,
        "repo_id": record["repo_id"],
        "source_directory": str(source),
        "source_prefix": capture["original_source"]["subtree_path_in_parent"],
        "source_present": source.is_dir(),
        "base_tree": base_tree,
        "captured_final_tree": captured_tree,
        "captured_at": capture.get("captured_at"),
        "collected_at": record.get("collected_at"),
        "recorded_final_status": record.get("final_status"),
        "recorded_final_inventory_sha256": record.get("final_inventory_sha256"),
        "before_inventory_sha256": None,
        "after_inventory_sha256": None,
    }
    if not source.is_dir():
        out.update({"status": "error", "detail": "source directory missing"})
        return out
    before = directory_inventory(source)
    out["before_inventory_sha256"] = before["sha256"]
    out["before_inventory_count"] = before["count"]

    git_dir = work_root / "derive-git" / task_id
    if git_dir.exists():
        shutil.rmtree(git_dir)
    out["init"] = init_temp_git(git_dir, objects, env)
    derived = derive_tree(git_dir, source, base_tree, env, timeout)
    out["derive"] = derived
    if not derived["ok"]:
        out["status"] = "error"
        out["detail"] = derived.get("error")
        out["after_inventory_sha256"] = directory_inventory(source)["sha256"]
        return out

    out["derived_tree"] = derived["tree"]
    out["derived_tree_size_bytes"] = tree_size(git_dir, derived["tree"], env)
    out["validation"] = validate_derived(git_dir, derived["tree"], captured_tree, source, env)
    out["changed_paths"] = tree_changes(git_dir, base_tree, derived["tree"], env)
    base_entries, _ = ls_tree(git_dir, base_tree, env)
    out["base_path_count"] = len(base_entries)
    out["derived_path_count"] = len(ls_tree(git_dir, derived["tree"], env)[0])

    patch = patch_and_replay(
        git_dir, base_tree, derived["tree"], private_root / "patches" / f"{task_id}.patch", env, timeout
    )
    out["patch"] = patch
    after = directory_inventory(source)
    out["after_inventory_sha256"] = after["sha256"]
    out["inventory_unchanged_during_analysis"] = (
        before["sha256"] == after["sha256"] and before["count"] == after["count"]
    )
    ok = (
        out["validation"]["ok"]
        and patch["ok"]
        and out["inventory_unchanged_during_analysis"]
    )
    out["status"] = "ok" if ok else "error"
    if not ok:
        reasons = []
        if not out["validation"]["ok"]:
            reasons.append("derived tree did not validate against frozen capture")
        if not patch["ok"]:
            reasons.append("patch replay tree mismatch")
        if not out["inventory_unchanged_during_analysis"]:
            reasons.append("source inventory changed during analysis")
        out["detail"] = "; ".join(reasons)
    # Private evidence may include command bodies; public projection strips them.
    out["_git_dir"] = str(git_dir)
    return out


def directory_inventory(root: Path) -> dict:
    rows = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                if path.is_symlink():
                    data = os.readlink(path).encode()
                    rows.append({"path": rel, "mode": "120000", "size": len(data),
                                 "sha256": sha256_bytes(data)})
                else:
                    data = path.read_bytes()
                    rows.append({"path": rel, "mode": oct(path.stat().st_mode & 0o777),
                                 "size": len(data), "sha256": sha256_bytes(data)})
            except OSError as exc:
                rows.append({"path": rel, "error": str(exc)})
    rows.sort(key=lambda r: r["path"])
    return {"count": len(rows), "rows": rows, "sha256": sha256_bytes(canonical_json(rows))}


def public_task(task: dict) -> dict:
    keep = [
        "task_id", "repo_id", "source_prefix", "source_present", "base_tree",
        "captured_final_tree", "derived_tree", "derived_path_count", "derived_tree_size_bytes",
        "captured_at", "collected_at", "before_inventory_sha256", "after_inventory_sha256",
        "inventory_unchanged_during_analysis", "status", "detail",
    ]
    out = {k: task.get(k) for k in keep}
    validation = task.get("validation") or {}
    out["validation"] = {
        "ok": validation.get("ok"),
        "issues": validation.get("issues", []),
        "derived_paths": validation.get("derived_paths"),
        "captured_paths": validation.get("captured_paths"),
        "content_matches_capture": validation.get("content_matches_capture"),
        "included_all_present_in_capture": validation.get("included_all_present_in_capture"),
        "excluded_count": validation.get("excluded_count"),
        "excluded_paths": validation.get("excluded_paths", []),
    }
    patch = task.get("patch") or {}
    out["patch_replay"] = {
        "ok": patch.get("ok"),
        "patch_sha256": patch.get("patch_sha256"),
        "patch_bytes": patch.get("patch_bytes"),
        "replayed_tree": patch.get("replayed_tree"),
    }
    out["changed_paths"] = task.get("changed_paths", [])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--private", type=Path, default=DEFAULT_PRIVATE)
    parser.add_argument("--work-root", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=COMMAND_TIMEOUT)
    parser.add_argument("--repos", default=None, help="optional comma-separated repo filter for a smoke run")
    args = parser.parse_args(argv)

    started = utc_now()
    t0 = time.monotonic()
    evidence = args.evidence_root
    plan = json.loads((evidence / "plan.json").read_text())
    summary = json.loads((evidence / "public-summary.json").read_text())
    pair_by_id = {p["pair_id"]: p for p in plan["pairs"]}
    raw_labels = load_replay_labels(evidence)
    test_audit = load_test_audit(evidence)
    repos = set(args.repos.split(",")) if args.repos else None

    work_root = args.work_root or Path(tempfile.mkdtemp(prefix="controlled-posthoc-"))
    work_root.mkdir(parents=True, exist_ok=True)
    home = work_root / "home"
    home.mkdir(exist_ok=True)
    env = sanitized_env(home)
    producer = Path(__file__).resolve()
    producer_sha = sha256_bytes(producer.read_bytes())
    args.private.mkdir(parents=True, exist_ok=True)

    task_records = {}
    for path in sorted((evidence / "outputs").glob("*/record.json")):
        record = json.loads(path.read_text())
        if record.get("status") not in (None, "collected"):
            continue
        task_records[record["task_id"]] = record

    pairs_out = []
    for pair in plan["pairs"]:
        if repos and pair["repo_id"] not in repos:
            continue
        pair_started = utc_now()
        pair_work = work_root / "pairs" / pair["pair_id"]
        pair_work.mkdir(parents=True, exist_ok=True)
        tasks = []
        for task_id in pair["task_ids"]:
            record = task_records.get(task_id)
            if record is None:
                tasks.append({"task_id": task_id, "status": "error",
                              "detail": "no collection record"})
                continue
            capture = json.loads((evidence / "captures" / f"{task_id}.json").read_text())
            task = analyze_task(record, capture, args.objects, pair_work,
                               args.private, env, args.timeout)
            tasks.append(task)
        pair_entry = {
            "pair_id": pair["pair_id"],
            "repo_id": pair["repo_id"],
            "task_ids": pair["task_ids"],
            "started_at": pair_started,
            "tasks": tasks,
        }
        if all(t.get("status") == "ok" for t in tasks) and len(tasks) == 2:
            merge_git = Path(tasks[0]["_git_dir"].split("derive-git")[0]) / "merge-git" / pair["pair_id"]
            merge_git = pair_work / "merge-git"
            if merge_git.exists():
                shutil.rmtree(merge_git)
            init_temp_git(merge_git, args.objects, env)
            add_alternates(merge_git, [Path(t["_git_dir"]) / "objects" for t in tasks])
            side_trees = [t["derived_tree"] for t in tasks]
            base_trees = {t["base_tree"] for t in tasks}
            if len(base_trees) == 1:
                merge = merge_trees(merge_git, next(iter(base_trees)), side_trees,
                                    env, args.timeout)
            else:
                merge = {"status": "error", "detail": "side base trees differ",
                         "identical_repeats": False, "conflicts": [], "runs": []}
            pair_entry["merge"] = merge
        else:
            pair_entry["merge"] = {"status": "error", "detail": "a side failed; merge not attempted",
                                   "identical_repeats": False, "conflicts": [], "runs": []}
        pair_entry["ended_at"] = utc_now()
        pair_entry["duration_seconds"] = round(time.monotonic() - t0, 3)
        pairs_out.append(pair_entry)

    # Public projection: no prompts, no patch bodies, no command stdout/stderr.
    public_pairs = []
    for pair in pairs_out:
        raw = raw_labels.get(pair["pair_id"], {}).get(pair["repo_id"], {})
        merge = pair.get("merge", {})
        public_pairs.append({
            "pair_id": pair["pair_id"],
            "repo_id": pair["repo_id"],
            "task_ids": pair["task_ids"],
            "raw_full_directory_capture": {
                "label": raw.get("label"),
                "starting_snapshots_equal": raw.get("starting_snapshots_equal"),
                "merge_repeats_identical": raw.get("merge_repeats_identical"),
                "final_source_trees": raw.get("final_source_trees"),
                "tasks": [
                    {"task_id": t.get("task_id"), "final_source_tree": t.get("captured_final_tree")}
                    for t in pair["tasks"]
                ],
            },
            "posthoc_git_visible": {
                "merge_status": merge.get("status"),
                "merge_detail": merge.get("detail"),
                "identical_repeats": merge.get("identical_repeats"),
                "merge_tree": merge.get("merge_tree"),
                "conflict_paths": sorted({c["path"] for c in merge.get("conflicts", [])}),
                "tasks": [public_task(t) for t in pair["tasks"]],
            },
        })

    public = {
        "protocol_version": PROTOCOL_VERSION,
        "method": {
            "id": METHOD_ID,
            "producer_path": public_producer_path(producer),
            "producer_sha256": producer_sha,
            "created_at": started,
            "git_version": run_cmd(["git", "--version"], work_root, env)["stdout"].strip(),
            "case_selection": "all five existing pairs; no case or file-category selection",
            "derivation": "new temporary --git-dir; read-tree pinned tree; "
                          "git --git-dir TEMP --work-tree ACTUAL add -A; write-tree",
            "config": "system/global configs disabled; hooks disabled by fresh Git dir; "
                      "external filters absent from these trees; ordinary committed and "
                      "generated .gitignore honored",
            "source_mutation": "none; only read access to the coding worktrees",
        },
        "method_separation": {
            "raw_full_directory_capture": {
                "frozen": True,
                "description": "scripts/controlled_single_project.py collected every source "
                               "directory file, including ignored pytest caches and pyc; those "
                               "raw labels are conflict and remain unchanged",
                "labels_reported_here_from": "replay-<repo>.log",
            },
            "posthoc_git_visible_development_diagnostic": {
                "frozen": False,
                "description": "separate post-hoc analysis of ordinary Git-staged files from the "
                               "same final source directories; it does not replace or relabel the "
                               "raw captures",
                "scratch_or_docs_or_binaries_included": "any nonignored file is included; no "
                                                        "source-only filtering",
            },
        },
        "original_preregistered_gate": {
            "status": summary.get("feasibility_gate", {}).get("status"),
            "passes": summary.get("feasibility_gate", {}).get("passes"),
            "qualifying_pairs": summary.get("feasibility_gate", {}).get("qualifying_pairs"),
            "qualifying_repositories": summary.get("feasibility_gate", {}).get("qualifying_repositories"),
            "raw_label_counts": summary.get("feasibility_gate", {}).get("label_counts"),
            "assessment": "formal provenance/replay gate passed, but the raw full-directory "
                          "target measures full-directory Git merge conflicts including generated files; "
                          "ordinary Git staging is a different, post-hoc development policy",
        },
        "claims": {
            "training_ready": False,
            "held_out": False,
            "generalization": False,
            "accuracy": False,
            "semantic_conflict_labels": False,
            "coding_correctness_proven": False,
            "all_five_repositories_are_development_controls": True,
        },
        "summary": {
            "pairs_analyzed": len(public_pairs),
            "posthoc_clean": sum(1 for p in public_pairs
                                 if p["posthoc_git_visible"]["merge_status"] == "clean"),
            "posthoc_conflict": sum(1 for p in public_pairs
                                    if p["posthoc_git_visible"]["merge_status"] == "conflict"),
            "posthoc_error": sum(1 for p in public_pairs
                                 if p["posthoc_git_visible"]["merge_status"] not in ("clean", "conflict")),
            "raw_full_directory_label_counts": {
                label: sum(1 for p in public_pairs
                           if p["raw_full_directory_capture"]["label"] == label)
                for label in sorted({p["raw_full_directory_capture"]["label"]
                                     for p in public_pairs})
            },
        },
        "pairs": public_pairs,
        "targeted_test_audit": test_audit,
        "limitations": [
            "All ten tasks are instruction-bound sibling isolation runs authored by the coordinator.",
            "One model (opencode-go/deepseek-v4.1-flash at variant max) supplied all outputs.",
            "The sample is small and purposive: five repositories, two tasks each.",
            "Click A ran its focused test file twice, both reported 22 passed.",
            "attrs A used the frozen -k fields_dict filter, which selected only one existing test "
            "and skipped its new test_instance and test_handler_non_attrs_instance tests; a "
            "separate direct sanity check ran.",
            "attrs B first test job exited 4 with no stdout, then a second job reported 4 passed.",
            "packaging B ran its focused selection twice, both reported 8 passed.",
            "dateutil B ran three times: a failed marker collection exited 3 with no tests, a "
            "second run reported 9 passed with the new cases skipped, and a third run after test "
            "renaming reported 16 passed.",
            "Repeated test, import and setup failures are retained, not corrected.",
            "dateutil used src-layout and SCM environment workarounds and did not run typing checks.",
            "Generated caches contribute raw conflicts; two pairs also conflict on repository content; "
            "artifact-conflict-audit.json is an imperfect post-hoc ignore scan and was not used to "
            "infer labels.",
            "This diagnostic does not prove coding correctness or semantic conflict labels.",
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
    (args.private / "posthoc-full.json").write_text(
        json.dumps({
            "protocol_version": PROTOCOL_VERSION,
            "method": METHOD_ID,
            "producer_sha256": producer_sha,
            "started_at": started,
            "ended_at": utc_now(),
            "pairs": pairs_out,
        }, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "out": str(args.out),
        "private": str(args.private),
        "summary": public["summary"],
        "elapsed_seconds": round(time.monotonic() - t0, 3),
    }, indent=2))
    return 0 if all(p["posthoc_git_visible"]["merge_status"] in ("clean", "conflict")
                    for p in public_pairs) else 2


if __name__ == "__main__":
    sys.exit(main())
