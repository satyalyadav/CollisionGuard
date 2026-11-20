#!/usr/bin/env python3
"""Evidence recorder and full-tree replay for the controlled coding pilot."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data" / "controlled-pilot"
PRIVATE = ROOT / "data" / "private" / "research" / "controlled-pilot"
PLAN = PRIVATE / "plan.json"
EVENTS = PRIVATE / "logs" / "events.jsonl"
PROTOCOL_VERSION = "controlled-pilot-1"
TEST_LIMIT_SECONDS = 180
SETUP_LIMIT_SECONDS = 300
ARTIFACT_PARTS = {
    ".coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}


class PilotError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def event(kind: str, **fields: Any) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now(), "kind": kind, **fields}
    with EVENTS.open("ab") as stream:
        stream.write((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def load_plan() -> dict[str, Any]:
    if not PLAN.is_file():
        raise PilotError(f"frozen plan is missing: {PLAN}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    """Reject incomplete or mutable task joins before any child starts."""
    repos = plan.get("repositories", [])
    pairs = plan.get("pairs", [])
    tasks = plan.get("tasks", [])
    if len(repos) != 5 or len(pairs) != 5 or len(tasks) != 10:
        raise PilotError("the frozen plan must contain five repositories, five pairs, and ten tasks")
    repo_ids = {row.get("repo_id") for row in repos}
    if None in repo_ids or len(repo_ids) != 5:
        raise PilotError("repository ids must be unique and complete")
    pair_ids = [row.get("pair_id") for row in pairs]
    if None in pair_ids or len(set(pair_ids)) != 5:
        raise PilotError("pair ids must be unique and complete")
    task_ids = [row.get("task_id") for row in tasks]
    if None in task_ids or len(set(task_ids)) != 10:
        raise PilotError("task ids must be unique and complete")
    for pair in pairs:
        members = [task for task in tasks if task.get("pair_id") == pair["pair_id"]]
        if len(members) != 2 or any(task.get("repo_id") != pair.get("repo_id") for task in members):
            raise PilotError(f"pair {pair['pair_id']} must join exactly two tasks from its repository")
    for task in tasks:
        if task.get("repo_id") not in repo_ids or task.get("pair_id") not in pair_ids:
            raise PilotError(f"task {task['task_id']} has an unknown source or pair")
        if task.get("model") != {"provider": "kiro", "model": "claude-haiku-5.5", "options": [{"id": "mode", "value": "vibe"}]}:
            raise PilotError(f"task {task['task_id']} does not use the frozen Haiku-only selection")
        prompt = PRIVATE / task["prompt_file"]
        if not prompt.is_file() or sha256(prompt.read_bytes()) != task.get("prompt_sha256"):
            raise PilotError(f"frozen prompt hash mismatch for {task['task_id']}")
    digest = plan.get("plan_sha256")
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if digest != sha256(payload):
        raise PilotError("frozen plan digest mismatch")


def tasks_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["task_id"]: task for task in plan.get("tasks", [])}


def repo_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {repo["repo_id"]: repo for repo in plan.get("repositories", [])}


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Run argv with a process-group deadline and retain exact command output."""
    if timeout < 1 or timeout > SETUP_LIMIT_SECONDS:
        raise PilotError(f"command timeout must be between 1 and {SETUP_LIMIT_SECONDS}s")
    started = now()
    started_monotonic = time.monotonic()
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=child_env,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = started_monotonic + timeout
    try:
        stdout, stderr = proc.communicate(input=input_bytes, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
    ended = now()
    result = {
        "argv": argv,
        "cwd": str(cwd.resolve()) if cwd else None,
        "pid": proc.pid,
        "started_at": started,
        "deadline_at": dt.datetime.fromtimestamp(
            time.time() + max(0, deadline - time.monotonic()), dt.timezone.utc
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "ended_at": ended,
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace"),
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_sha256": sha256(stdout),
        "stderr_sha256": sha256(stderr),
    }
    return result


def _must(result: dict[str, Any], action: str) -> str:
    if result["returncode"] != 0 or result["timed_out"]:
        raise PilotError(
            f"{action} failed (exit {result['returncode']}, timeout={result['timed_out']}): "
            f"{result['stderr'][:1000]}"
        )
    return result["stdout"].strip()


def _git(repo: Path, *args: str, timeout: int = 60) -> dict[str, Any]:
    return _run(["git", "-C", str(repo), *args], cwd=repo, timeout=timeout)


def _git_text(repo: Path, *args: str, timeout: int = 60) -> str:
    return _must(_git(repo, *args, timeout=timeout), "git " + " ".join(args))


def _nul_paths(raw: str) -> list[str]:
    return sorted(p for p in raw.split("\0") if p)


def snapshot(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    if not repo.is_dir():
        raise PilotError(f"worktree does not exist: {repo}")
    gitdir = _git_text(repo, "rev-parse", "--absolute-git-dir")
    common = Path(_git_text(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    commands: dict[str, dict[str, Any]] = {}
    for key, args in {
        "head": ("rev-parse", "HEAD"),
        "tree": ("rev-parse", "HEAD^{tree}"),
        "index_tree": ("write-tree",),
        "status": ("status", "--porcelain=v2", "--branch", "--untracked-files=all", "--ignored=matching"),
        "untracked": ("ls-files", "--others", "--exclude-standard", "--full-name", "-z"),
        "ignored": ("ls-files", "--others", "--ignored", "--exclude-standard", "--full-name", "-z"),
        "tracked": ("ls-files", "--stage", "-z"),
    }.items():
        commands[key] = _git(repo, *args)
    values = {key: _must(commands[key], f"snapshot {key}") for key in ("head", "tree", "index_tree")}
    status_raw = commands["status"]["stdout"]
    status_entries = [line for line in status_raw.splitlines() if line and not line.startswith("# ")]
    untracked = _nul_paths(commands["untracked"]["stdout"])
    ignored = _nul_paths(commands["ignored"]["stdout"])
    return {
        "repo_path": str(repo),
        "git_dir": gitdir,
        "git_common_dir": str(common),
        "head": values["head"],
        "tree": values["tree"],
        "index_tree": values["index_tree"],
        "status": status_raw,
        "status_entries": status_entries,
        "untracked": untracked,
        "ignored": ignored,
        "tracked_index": commands["tracked"]["stdout"],
        "commands": commands,
        "clean": not status_entries and not untracked and values["index_tree"] == values["tree"],
        "captured_at": now(),
    }


def same_start(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, list[str]]:
    fields = ("head", "tree", "index_tree", "status_entries", "untracked", "ignored", "tracked_index")
    differences = [field for field in fields if a.get(field) != b.get(field)]
    return not differences, differences


def is_artifact(path: str) -> bool:
    p = Path(path)
    return any(part in ARTIFACT_PARTS for part in p.parts) or p.suffix in {".pyc", ".pyo", ".coverage"}


def artifact_paths(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if is_artifact(path))


def label_from_repeats(
    repeats: list[dict[str, Any]], *, snapshots_equal: bool, nonempty: list[bool],
    outputs_distinct: bool, side_trees_match: list[bool], within_limits: bool,
    provenance_ok: bool,
) -> str | None:
    """A merge label requires every declared evidence and limit check to pass."""
    if not (snapshots_equal and all(nonempty) and outputs_distinct and all(side_trees_match)
            and within_limits and provenance_ok and len(repeats) == 2):
        return None
    if any(row.get("timed_out") or row.get("returncode") not in (0, 1) for row in repeats):
        return None
    if any((row.get("returncode"), row.get("stdout"), row.get("stderr")) !=
           (repeats[0].get("returncode"), repeats[0].get("stdout"), repeats[0].get("stderr"))
           for row in repeats[1:]):
        return None
    code = repeats[0].get("returncode")
    if code == 0:
        return "clean"
    if code == 1 and "CONFLICT" in repeats[0].get("stdout", ""):
        return "conflict"
    return None


def snapshot_path(task_id: str) -> Path:
    return PRIVATE / "snapshots" / f"{task_id}.json"


def output_path(task_id: str) -> Path:
    return PRIVATE / "outputs" / f"{task_id}"


def task_run_path(task_id: str) -> Path:
    return PRIVATE / "provenance" / "runs" / f"{task_id}.json"


def capture(task_id: str, repo: Path, phase: str) -> dict[str, Any]:
    plan = load_plan()
    task = tasks_by_id(plan).get(task_id)
    if task is None:
        raise PilotError(f"unknown task id: {task_id}")
    snap = snapshot(repo)
    expected = repo_by_id(plan)[task["repo_id"]]
    snap.update({
        "task_id": task_id,
        "pair_id": task["pair_id"],
        "repo_id": task["repo_id"],
        "phase": phase,
        "expected_head": expected["commit"],
        "expected_tree": expected["tree"],
        "prompt_sha256": task["prompt_sha256"],
    })
    target = snapshot_path(task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        equal, differences = same_start(old, snap)
        if not equal or old.get("repo_path") != snap.get("repo_path"):
            raise PilotError(f"immutable capture already exists and differs: {differences}")
        event("snapshot_reused", task_id=task_id, path=str(target), phase=old["phase"])
        return old
    dump_json(target, snap)
    event("snapshot_captured", task_id=task_id, path=str(target), phase=phase,
          head=snap["head"], tree=snap["tree"], index_tree=snap["index_tree"], clean=snap["clean"])
    return snap


def verify(task_id: str, repo: Path, capture_if_missing: bool = False, allow_changes: bool = False) -> dict[str, Any]:
    plan = load_plan()
    task = tasks_by_id(plan).get(task_id)
    if task is None:
        raise PilotError(f"unknown task id: {task_id}")
    path = snapshot_path(task_id)
    if not path.exists():
        if not capture_if_missing:
            raise PilotError("pre-mutation worktree capture is missing")
        # This first-action fallback occurs after the model starts. It is not a host pre-start capture.
        capture(task_id, repo, "first_child_action_fallback_before_edits")
    saved = json.loads(path.read_text(encoding="utf-8"))
    current = snapshot(repo)
    expected = repo_by_id(plan)[task["repo_id"]]
    problems = []
    if current["head"] != expected["commit"]:
        problems.append("HEAD differs from pinned commit")
    if current["tree"] != expected["tree"]:
        problems.append("HEAD tree differs from pinned tree")
    equal, differences = same_start(saved, current)
    if not allow_changes and not equal:
        problems.append("worktree drift since capture: " + ",".join(differences))
    if not allow_changes and not current["clean"]:
        problems.append("worktree/index is not clean")
    if allow_changes and current["head"] != saved["head"]:
        problems.append("HEAD moved after the immutable capture")
    if saved["prompt_sha256"] != task["prompt_sha256"]:
        problems.append("captured prompt hash differs from frozen prompt")
    pair_snaps = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (PRIVATE / "snapshots").glob("*.json")
        if json.loads(p.read_text(encoding="utf-8")).get("pair_id") == task["pair_id"]
    ]
    for partner in pair_snaps:
        pair_equal, pair_diff = same_start(saved, partner)
        if not pair_equal:
            problems.append("paired starting snapshot differs: " + ",".join(pair_diff))
    result = {"ok": not problems, "task_id": task_id, "checked_at": now(), "problems": problems,
              "capture": str(path), "current": current}
    event("snapshot_verified", task_id=task_id, ok=result["ok"], problems=problems)
    if problems:
        raise PilotError("snapshot verification failed: " + "; ".join(problems))
    return result


def _common_objects(repo: Path) -> Path:
    common = Path(_git_text(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    return common / "objects"


def _make_temp_repo(repo: Path, parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="controlled-git-", dir=parent))
    init = _run(["git", "init", "-q", str(dest)], cwd=dest)
    _must(init, "git init")
    alternate = dest / ".git" / "objects" / "info" / "alternates"
    alternate.parent.mkdir(parents=True, exist_ok=True)
    alternate.write_text(str(_common_objects(repo).resolve()) + "\n", encoding="utf-8")
    return dest


def _copy_worktree_files(source: Path, target: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {".git"} & set(names)

    shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True, ignore=ignore)


def collect(task_id: str, repo: Path) -> dict[str, Any]:
    verify(task_id, repo, allow_changes=True)
    target = output_path(task_id)
    record_path = target / "record.json"
    if record_path.exists():
        old = json.loads(record_path.read_text(encoding="utf-8"))
        now_tree = _git_text(repo.resolve(), "write-tree")
        if old.get("final_index_tree") != now_tree:
            raise PilotError("output already exists and source worktree changed after collection")
        event("output_reused", task_id=task_id, output=str(target))
        return old
    plan = load_plan()
    task = tasks_by_id(plan)[task_id]
    base = repo.resolve()
    saved_snapshot = json.loads(snapshot_path(task_id).read_text(encoding="utf-8"))
    head = _git_text(base, "rev-parse", "HEAD")
    index_result = _git(base, "write-tree")
    index_tree = index_result["stdout"].strip() if index_result["returncode"] == 0 else None
    final_status = _git_text(base, "status", "--porcelain=v2", "--branch", "--untracked-files=all", "--ignored=matching")
    # Build a private scratch repository so additions, binaries, symlinks, and modes all enter the final tree.
    scratch = _make_temp_repo(base, PRIVATE / "replay" / "collect-scratch")
    _copy_worktree_files(base, scratch)
    add = _run(["git", "-C", str(scratch), "add", "--all", "--force"], cwd=scratch)
    _must(add, "stage scratch copy")
    final_tree = _git_text(scratch, "write-tree")
    base_tree = saved_snapshot["tree"]
    diff = _run(["git", "-C", str(scratch), "diff", "--binary", "--full-index", "--no-renames", base_tree, final_tree], cwd=scratch)
    _must(diff, "full-tree diff")
    name_status = _run(["git", "-C", str(scratch), "diff", "--name-status", "--no-renames", "-z", base_tree, final_tree], cwd=scratch)
    _must(name_status, "changed path inventory")
    tokens = name_status["stdout"].split("\0")
    changed_paths = [tokens[i + 1] for i, token in enumerate(tokens[:-1]) if token and token[0] in "AMDRCTU"]
    tracked = _run(["git", "-C", str(scratch), "ls-tree", "-r", "-l", final_tree], cwd=scratch)
    _must(tracked, "final tree inventory")
    patch = base64.b64decode(diff["stdout_base64"])
    target.mkdir(parents=True, exist_ok=True)
    (target / "full-tree.patch").write_bytes(patch)
    details = {
        "protocol_version": PROTOCOL_VERSION,
        "task_id": task_id,
        "pair_id": task["pair_id"],
        "repo_id": task["repo_id"],
        "collected_at": now(),
        "repo_path": str(base),
        "head": head,
        "base_tree": base_tree,
        "initial_index_tree": saved_snapshot["index_tree"],
        "final_index_tree": index_tree,
        "final_index_tree_command": index_result,
        "final_working_tree": final_tree,
        "final_status": final_status,
        "changed_paths": changed_paths,
        "final_tree_entries": tracked["stdout"],
        "artifact_paths": artifact_paths(changed_paths),
        "nonempty": bool(patch),
        "patch_bytes": len(patch),
        "patch_sha256": sha256(patch),
        "patch_file": str((target / "full-tree.patch").relative_to(PRIVATE)),
        "patch_sha256_on_disk": sha256((target / "full-tree.patch").read_bytes()),
        "copy_command": {"argv": ["python shutil.copytree", str(base), str(scratch), "exclude .git"], "returncode": 0},
        "stage_command": add,
        "diff_command": diff,
        "name_status_command": name_status,
        "tree_inventory_command": tracked,
        "head_unchanged": head == saved_snapshot["head"],
    }
    dump_json(record_path, details)
    event("output_collected", task_id=task_id, patch_sha256=details["patch_sha256"],
          nonempty=details["nonempty"], changed_paths=changed_paths, artifact_paths=details["artifact_paths"])
    shutil.rmtree(scratch, ignore_errors=True)
    return details


def replay_pair(pair_id: str) -> dict[str, Any]:
    plan = load_plan()
    pair = next((p for p in plan["pairs"] if p["pair_id"] == pair_id), None)
    if pair is None:
        raise PilotError(f"unknown pair id: {pair_id}")
    task_rows = [t for t in plan["tasks"] if t["pair_id"] == pair_id]
    if len(task_rows) != 2:
        raise PilotError("pair does not have exactly two frozen tasks")
    output_records = []
    run_records = []
    missing_outputs = []
    for task in task_rows:
        path = output_path(task["task_id"]) / "record.json"
        if not path.exists():
            missing_outputs.append(task["task_id"])
            output_records.append(None)
        else:
            output_records.append(json.loads(path.read_text(encoding="utf-8")))
        run_path = task_run_path(task["task_id"])
        run_records.append(json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else None)
    coding_attempted = all(run and run.get("coding_started") is True for run in run_records)
    if missing_outputs:
        snapshots = [
            json.loads(snapshot_path(task["task_id"]).read_text(encoding="utf-8"))
            for task in task_rows if snapshot_path(task["task_id"]).exists()
        ]
        equal = len(snapshots) == 2 and same_start(snapshots[0], snapshots[1])[0]
        result = {
            "protocol_version": PROTOCOL_VERSION,
            "pair_id": pair_id,
            "repo_id": task_rows[0]["repo_id"],
            "replayed_at": now(),
            "git_version": _must(_run(["git", "--version"]), "git --version"),
            "attempted": coding_attempted,
            "starting_snapshots_equal": equal,
            "starting_snapshot_differences": [],
            "patches_nonempty": [row["nonempty"] if row else None for row in output_records],
            "patches_distinct": False,
            "patch_sha256": [row["patch_sha256"] if row else None for row in output_records],
            "head_unchanged": [row["head_unchanged"] if row else None for row in output_records],
            "changed_paths": [row["changed_paths"] if row else [] for row in output_records],
            "artifact_paths": [row["artifact_paths"] if row else [] for row in output_records],
            "task_run_records": [str(task_run_path(t["task_id"]).relative_to(PRIVATE)) for t in task_rows],
            "repeat_runs": [],
            "merge_repeats_identical": False,
            "label": None,
            "qualifies": False,
            "exclusion_reasons": ["one or more task outputs were not collected"],
            "missing_output_task_ids": missing_outputs,
        }
        if not coding_attempted:
            result["exclusion_reasons"].append("both coding runs were not confirmed started")
        record_path = PRIVATE / "replay" / f"{pair_id}.json"
        dump_json(record_path, result)
        event("pair_replayed", pair_id=pair_id, label=None, qualifies=False,
              attempted=coding_attempted, reasons=result["exclusion_reasons"])
        return result
    snaps = [json.loads(snapshot_path(t["task_id"]).read_text(encoding="utf-8")) for t in task_rows]
    equal, differences = same_start(snaps[0], snaps[1])
    outputs_differ = output_records[0]["patch_sha256"] != output_records[1]["patch_sha256"]
    repo = repo_by_id(plan)[task_rows[0]["repo_id"]]
    git_version = _must(_run(["git", "--version"]), "git --version")
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "pair_id": pair_id,
        "repo_id": task_rows[0]["repo_id"],
        "replayed_at": now(),
        "git_version": git_version,
        "attempted": coding_attempted,
        "starting_snapshots_equal": equal,
        "starting_snapshot_differences": differences,
        "patches_nonempty": [r["nonempty"] for r in output_records],
        "patches_distinct": outputs_differ,
        "patch_sha256": [r["patch_sha256"] for r in output_records],
        "head_unchanged": [r["head_unchanged"] for r in output_records],
        "changed_paths": [r["changed_paths"] for r in output_records],
        "artifact_paths": [r["artifact_paths"] for r in output_records],
        "task_run_records": [str(task_run_path(t["task_id"]).relative_to(PRIVATE)) for t in task_rows],
        "repeat_runs": [],
        "label": None,
        "exclusion_reasons": [],
    }
    checks = [
        (equal, "paired original snapshots differ"),
        (all(result["patches_nonempty"]), "at least one output is empty"),
        (outputs_differ, "outputs are byte-identical"),
        (all(result["head_unchanged"]), "a child moved HEAD"),
        (git_version == "git version 2.43.0", "Git 2.43.0 is unavailable"),
        (all(run_records), "one or more task run records are missing"),
        (coding_attempted, "both coding runs were not confirmed started"),
        (all(run and run.get("within_limits") is True for run in run_records), "one or more task runs exceeded or did not prove the declared limits"),
        (all(run and run.get("provenance_ok") is True for run in run_records), "one or more task runs have missing or contradictory provenance"),
    ]
    result["exclusion_reasons"].extend(message for ok, message in checks if not ok)
    private_replay = PRIVATE / "replay" / pair_id
    private_replay.mkdir(parents=True, exist_ok=True)
    patch_paths = [PRIVATE / row["patch_file"] for row in output_records]
    # Build base and child commits in an isolated temporary repository with read-only object alternates.
    repo_path = Path(repo["source_path"])
    temp = _make_temp_repo(repo_path, private_replay)
    env = {
        "GIT_AUTHOR_NAME": "controlled-pilot",
        "GIT_AUTHOR_EMAIL": "controlled-pilot@example.invalid",
        "GIT_COMMITTER_NAME": "controlled-pilot",
        "GIT_COMMITTER_EMAIL": "controlled-pilot@example.invalid",
    }
    base_commit = repo["commit"]
    checkout = _run(["git", "-C", str(temp), "checkout", "--quiet", "--detach", base_commit], cwd=temp, env=env)
    result["checkout_base"] = checkout
    if checkout["returncode"] != 0:
        result["exclusion_reasons"].append("cannot check out pinned base in private replay")
    else:
        commits = []
        for idx, patch_path in enumerate(patch_paths):
            reset = _run(["git", "-C", str(temp), "reset", "--hard", base_commit], cwd=temp, env=env)
            apply = _run(["git", "-C", str(temp), "apply", "--index", "--binary", str(patch_path)], cwd=temp, env=env)
            tree = _run(["git", "-C", str(temp), "write-tree"], cwd=temp, env=env)
            if reset["returncode"] or apply["returncode"] or tree["returncode"]:
                result["exclusion_reasons"].append(f"output {idx} did not replay cleanly onto the recorded base")
                result["repeat_runs"].append({"side": idx, "reset": reset, "apply": apply, "tree": tree})
                commits.append(None)
                continue
            commit = _run(["git", "-C", str(temp), "commit-tree", tree["stdout"].strip(), "-p", base_commit], cwd=temp, env=env,
                          input_bytes=f"controlled-pilot side {idx}\n".encode())
            result["repeat_runs"].append({"side": idx, "reset": reset, "apply": apply, "tree": tree, "commit": commit})
            commits.append(commit["stdout"].strip() if commit["returncode"] == 0 else None)
        result["replay_side_trees"] = [x.get("tree", {}).get("stdout", "").strip() for x in result["repeat_runs"]]
        result["replay_sides_match_collected"] = [
            i < len(result["replay_side_trees"]) and result["replay_side_trees"][i] == output_records[i]["final_working_tree"]
            for i in range(2)
        ]
        if not all(result["replay_sides_match_collected"]):
            result["exclusion_reasons"].append("replayed side tree differs from captured full output tree")
        if len(commits) == 2 and all(commits):
            for run_no in (1, 2):
                merge = _run(["git", "-C", str(temp), "merge-tree", "--write-tree", commits[0], commits[1]], cwd=temp, env=env)
                result["repeat_runs"].append({"merge_run": run_no, **merge})
            merges = [x for x in result["repeat_runs"] if "merge_run" in x]
            result["merge_repeats_identical"] = len(merges) == 2 and all(
                (x["returncode"], x["stdout"], x["stderr"], x["timed_out"]) ==
                (merges[0]["returncode"], merges[0]["stdout"], merges[0]["stderr"], merges[0]["timed_out"])
                for x in merges[1:]
            )
            if not result["merge_repeats_identical"]:
                result["exclusion_reasons"].append("the two full-tree merge replays differ")
            result["label"] = label_from_repeats(
                merges,
                snapshots_equal=equal,
                nonempty=result["patches_nonempty"],
                outputs_distinct=outputs_differ,
                side_trees_match=result["replay_sides_match_collected"],
                within_limits=all(run and run.get("within_limits") is True for run in run_records),
                provenance_ok=all(run and run.get("provenance_ok") is True for run in run_records),
            )
            if result["label"] is None:
                result["exclusion_reasons"].append("merge-tree returned an error or unknown result")
        else:
            result["merge_repeats_identical"] = False
            result["exclusion_reasons"].append("could not construct both replay commits")
    if result.get("label") is None or result["exclusion_reasons"]:
        result["label"] = None
    result["qualifies"] = result["label"] in {"clean", "conflict"} and not result["exclusion_reasons"]
    record_path = PRIVATE / "replay" / f"{pair_id}.json"
    dump_json(record_path, result)
    event("pair_replayed", pair_id=pair_id, label=result["label"], qualifies=result["qualifies"],
          reasons=result["exclusion_reasons"])
    shutil.rmtree(temp, ignore_errors=True)
    return result


def feasibility(plan: dict[str, Any], replay_rows: list[dict[str, Any]]) -> dict[str, Any]:
    repo_names = repo_by_id(plan)
    rows_by_pair = {row.get("pair_id"): row for row in replay_rows}
    all_attempted = len(rows_by_pair) == len(plan.get("pairs", [])) and all(
        rows_by_pair.get(pair["pair_id"], {}).get("attempted") is True for pair in plan.get("pairs", [])
    )
    eligible = [row for row in replay_rows if row.get("qualifies")]
    repos = sorted({repo_names[row["repo_id"]]["repo_id"] for row in eligible})
    counts = {label: sum(row.get("label") == label for row in eligible) for label in ("clean", "conflict")}
    passes = len(eligible) >= 3 and len(repos) >= 3 if all_attempted else None
    return {
        "all_five_pairs_attempted": all_attempted,
        "qualifying_pairs": len(eligible),
        "qualifying_repositories": len(repos),
        "label_counts": counts,
        "status": "passed" if passes is True else "failed" if passes is False else "not_evaluated",
        "passes": passes,
    }


def write_public_summary() -> dict[str, Any]:
    plan = load_plan()
    rows = []
    for pair in plan["pairs"]:
        path = PRIVATE / "replay" / f"{pair['pair_id']}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            rows.append(row)
        else:
            pair_tasks = [task for task in plan["tasks"] if task["pair_id"] == pair["pair_id"]]
            run_records = [
                json.loads(task_run_path(task["task_id"]).read_text(encoding="utf-8"))
                if task_run_path(task["task_id"]).exists() else None
                for task in pair_tasks
            ]
            output_records = [
                json.loads((output_path(task["task_id"]) / "record.json").read_text(encoding="utf-8"))
                if (output_path(task["task_id"]) / "record.json").exists() else None
                for task in pair_tasks
            ]
            snapshots = [
                json.loads(snapshot_path(task["task_id"]).read_text(encoding="utf-8"))
                if snapshot_path(task["task_id"]).exists() else None
                for task in pair_tasks
            ]
            attempted = len(run_records) == 2 and all(run and run.get("coding_started") is True for run in run_records)
            starts_equal = len(snapshots) == 2 and all(snapshots) and same_start(snapshots[0], snapshots[1])[0]
            rows.append({
                "pair_id": pair["pair_id"], "repo_id": pair["repo_id"], "attempted": attempted,
                "label": None, "qualifies": False,
                "exclusion_reasons": ["pair replay was not completed"] if attempted else ["both coding runs were not confirmed started"],
                "starting_snapshots_equal": bool(starts_equal),
                "patches_nonempty": [output["nonempty"] if output else None for output in output_records],
                "patches_distinct": bool(all(output_records) and output_records[0]["patch_sha256"] != output_records[1]["patch_sha256"]),
                "patch_sha256": [output["patch_sha256"] if output else None for output in output_records],
                "merge_repeats_identical": False,
                "artifact_paths": [output["artifact_paths"] if output else [] for output in output_records],
            })
    gate = feasibility(plan, rows)
    public = {
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": now(),
        "plan_sha256": plan["plan_sha256"],
        "producer_sha256": plan["producer_sha256"],
        "repositories": [
            {key: repo[key] for key in ("repo_id", "requested_name", "canonical_name", "visibility", "default_branch",
                                       "stars_at_pin", "license_spdx", "commit", "tree", "identity_resolution")}
            for repo in plan["repositories"]
        ],
        "pairs": [
            {"pair_id": row["pair_id"], "repo_id": row["repo_id"], "attempted": row.get("attempted", False), "label": row["label"],
             "qualifies": row["qualifies"], "exclusion_reasons": row["exclusion_reasons"],
             "starting_snapshots_equal": row["starting_snapshots_equal"], "patches_nonempty": row["patches_nonempty"],
             "patches_distinct": row["patches_distinct"], "patch_sha256": row["patch_sha256"],
             "merge_repeats_identical": row.get("merge_repeats_identical"), "artifact_paths": row["artifact_paths"]}
            for row in rows
        ],
        "feasibility_gate": gate,
    }
    dump_json(PUBLIC / "results.json", public)
    # Private supervision has exact task IDs, prompts, changed paths, and labels.
    targets = []
    for row in rows:
        for idx, task in enumerate(t for t in plan["tasks"] if t["pair_id"] == row["pair_id"]):
            out = output_path(task["task_id"])
            output = json.loads((out / "record.json").read_text(encoding="utf-8")) if (out / "record.json").exists() else {}
            targets.append({"task_id": task["task_id"], "pair_id": row["pair_id"], "repo_id": task["repo_id"],
                            "prompt_sha256": task["prompt_sha256"], "patch_sha256": output.get("patch_sha256"),
                            "changed_paths": output.get("changed_paths", []), "artifact_paths": output.get("artifact_paths", []),
                            "pair_label": row["label"], "target_index": idx})
    dump_json(PRIVATE / "features-targets.json", {"plan_sha256": plan["plan_sha256"], "rows": targets})
    event("summary_written", gate=gate)
    return public


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_capture = sub.add_parser("capture", help="record a host-created worktree before coding")
    p_capture.add_argument("--task-id", required=True)
    p_capture.add_argument("--repo", type=Path, default=Path.cwd())
    p_capture.add_argument("--phase", default="host_worktree_create")
    p_verify = sub.add_parser("verify", help="verify the capture before any edits")
    p_verify.add_argument("--task-id", required=True)
    p_verify.add_argument("--repo", type=Path, default=Path.cwd())
    p_verify.add_argument("--capture-if-missing", action="store_true")
    p_collect = sub.add_parser("collect", help="preserve the complete final tree delta")
    p_collect.add_argument("--task-id", required=True)
    p_collect.add_argument("--repo", type=Path, default=Path.cwd())
    p_replay = sub.add_parser("replay", help="apply and merge both complete task outputs")
    p_replay.add_argument("--pair-id", required=True)
    p_summary = sub.add_parser("summarize", help="write public facts and private target joins")
    p_summary.add_argument("--write", action="store_true")
    p_run = sub.add_parser("run", help="run one bounded test command and preserve its transcript")
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--cwd", type=Path, required=True)
    p_run.add_argument("--timeout-seconds", type=int, default=TEST_LIMIT_SECONDS)
    p_run.add_argument("--purpose", choices=("targeted-test", "dependency-preparation"), default="targeted-test")
    p_run.add_argument("command_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            snap = capture(args.task_id, args.repo, args.phase)
            print(json.dumps({"captured": True, "task_id": args.task_id, "head": snap["head"],
                              "tree": snap["tree"], "index_tree": snap["index_tree"],
                              "clean": snap["clean"], "phase": snap["phase"]}, sort_keys=True))
        elif args.command == "verify":
            result = verify(args.task_id, args.repo, args.capture_if_missing)
            current = result["current"]
            print(json.dumps({"ok": result["ok"], "task_id": args.task_id,
                              "head": current["head"], "tree": current["tree"],
                              "index_tree": current["index_tree"], "clean": current["clean"],
                              "capture_verified": True, "checked_at": result["checked_at"]}, sort_keys=True))
        elif args.command == "collect":
            print(json.dumps(collect(args.task_id, args.repo), sort_keys=True))
        elif args.command == "replay":
            print(json.dumps(replay_pair(args.pair_id), sort_keys=True))
        elif args.command == "summarize":
            print(json.dumps(write_public_summary() if args.write else feasibility(load_plan(), []), sort_keys=True))
        elif args.command == "run":
            if args.purpose == "targeted-test" and args.timeout_seconds > TEST_LIMIT_SECONDS:
                raise PilotError(f"targeted tests cannot exceed {TEST_LIMIT_SECONDS}s")
            command_args = args.command_args[1:] if args.command_args[:1] == ["--"] else args.command_args
            if not command_args:
                raise PilotError("run needs a command after --")
            result = _run(command_args, cwd=args.cwd.resolve(), timeout=args.timeout_seconds)
            log = output_path(args.task_id) / "jobs" / f"{now().replace(':', '').replace('-', '')}.json"
            dump_json(log, {"owner": args.task_id, "purpose": args.purpose, "checkpoint": None,
                            "deadline_seconds": args.timeout_seconds, **result})
            event("bounded_job", task_id=args.task_id, path=str(log), returncode=result["returncode"],
                  timed_out=result["timed_out"], pid=result["pid"])
            print(json.dumps({"log": str(log), **result}, sort_keys=True))
            return result["returncode"] if not result["timed_out"] else 124
    except (PilotError, OSError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        print(f"controlled pilot: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
