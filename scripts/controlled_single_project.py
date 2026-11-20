#!/usr/bin/env python3
"""Recorder for the controlled single-project source-subtree pilot.

The parent commit is a CollisionGuard snapshot. Each assigned upstream source
lives at ``controlled_sources/<repo_id>/`` and must equal a pinned upstream
tree. This recorder captures starts, collects complete source-relative changes,
replays each patch against the pinned tree, and labels pairs from two identical
merge-tree runs. It never works around a dirty or out-of-scope worktree.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
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
from pathlib import Path
from typing import Any, Iterable

PROTOCOL_VERSION = "controlled-single-project-2"
SOURCE_ROOT = "controlled_sources"
HELPER_PATH = "scripts/controlled_single_project.py"
DEFAULT_EVIDENCE_ROOT = Path(
    os.environ.get(
        "CSP_CANONICAL_EVIDENCE_ROOT",
        "/home/satyal/cse-572/Project/data/private/research/controlled-single-project-fresh-2026-11-20",
    )
)
CAPTURE_POLICIES = {
    "full-directory-v3": {
        "method": "git add --all --force",
        "ordinary_git_staging": False,
        "description": (
            "Stage every file in the final worktree, including ignored caches, bytecode and "
            "virtual environments. This reproduces the frozen v3 full-directory target."
        ),
    },
    "ordinary-git-staging-v1": {
        "method": "git read-tree, then git add --all without --force",
        "ordinary_git_staging": True,
        "description": (
            "Derive each final source tree from its pinned tree with ordinary Git staging. "
            "The repository's committed ignore rules decide which paths enter the tree."
        ),
    },
}
DEFAULT_CAPTURE_POLICY = "full-directory-v3"
TEST_LIMIT_SECONDS = 180
DEPENDENCY_LIMIT_SECONDS = 300
TASK_BUDGET_SECONDS = 480
SETUP_LIMIT_SECONDS = 300
GIT_PIN = "git version 2.43.0"
STARTED_STATUSES = {
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
}
CODING_MODEL = {
    "provider": "opencode",
    "provider_instance_id": "opencode",
    "model": "opencode-go/deepseek-v4.1-flash",
    "display": "opencode/opencode-go/deepseek-v4.1-flash",
    "options": [{"id": "variant", "value": "max"}],
    "reasoning_effort": "max",
    "service_tier": "default",
    "fast": False,
    "priority": False,
}
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
    "node_modules",
}
TASK_PAIR_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class PilotError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def event(root: Path, kind: str, **fields: Any) -> None:
    path = root / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now(), "kind": kind, **fields}
    with path.open("ab") as stream:
        stream.write((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def namespace_problem(root: Path, namespace: str, canonical: Path | None = None) -> str | None:
    """Return why this evidence root cannot carry this namespace, or None."""
    canonical = (canonical or DEFAULT_EVIDENCE_ROOT).resolve()
    resolved = root.resolve()
    if namespace not in {"real", "fixture"}:
        return f"unknown evidence namespace: {namespace}"
    if namespace == "real" and resolved != canonical:
        return f"real evidence must stay at {canonical}, not {resolved}"
    if namespace == "fixture" and resolved == canonical:
        return "fixture evidence may not use the real evidence root"
    return None


def evidence_root(path: Path, namespace: str, *, create: bool) -> Path:
    problem = namespace_problem(path, namespace)
    if problem:
        raise PilotError(problem)
    root = path.resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
        marker = root / "namespace.json"
        desired = {"namespace": namespace, "protocol_version": PROTOCOL_VERSION}
        if marker.exists():
            existing = load_json(marker)
            if existing.get("namespace") != namespace or existing.get(
                "protocol_version"
            ) != PROTOCOL_VERSION:
                raise PilotError(f"evidence namespace marker disagrees: {existing}")
        else:
            dump_json(marker, {**desired, "created_at": now()})
    return root


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    max_output: int = 4_000_000,
) -> dict[str, Any]:
    """Run argv with a process-group deadline and retain exact output hashes."""
    if timeout < 1 or timeout > SETUP_LIMIT_SECONDS:
        raise PilotError(f"command timeout must be between 1 and {SETUP_LIMIT_SECONDS}s")
    started = now()
    started_monotonic = time.monotonic()
    child_env = os.environ.copy()
    child_env.update(
        {
            "GIT_AUTHOR_NAME": "controlled-single-project",
            "GIT_AUTHOR_EMAIL": "controlled-single-project@example.invalid",
            "GIT_COMMITTER_NAME": "controlled-single-project",
            "GIT_COMMITTER_EMAIL": "controlled-single-project@example.invalid",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "gc.auto",
            "GIT_CONFIG_VALUE_0": "0",
            "GIT_CONFIG_KEY_1": "maintenance.auto",
            "GIT_CONFIG_VALUE_1": "false",
        }
    )
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
    return {
        "argv": argv,
        "cwd": str(cwd.resolve()) if cwd else None,
        "pid": proc.pid,
        "started_at": started,
        "deadline_at": (dt.datetime.fromisoformat(started.replace("Z", "+00:00")) + dt.timedelta(seconds=timeout))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "ended_at": ended,
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout[:max_output].decode("utf-8", "replace"),
        "stderr": stderr[:max_output].decode("utf-8", "replace"),
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_sha256": sha256(stdout),
        "stderr_sha256": sha256(stderr),
        "stdout_truncated": len(stdout) > max_output,
        "stderr_truncated": len(stderr) > max_output,
    }


def _must(result: dict[str, Any], action: str) -> str:
    if result["returncode"] != 0 or result["timed_out"]:
        raise PilotError(
            f"{action} failed (exit {result['returncode']}, timeout={result['timed_out']}): "
            f"{result['stderr'][:1000]}"
        )
    return result["stdout"].strip()


def _git(
    repo: Path,
    *args: str,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> dict[str, Any]:
    return _run(
        ["git", "-C", str(repo), *args],
        cwd=repo,
        timeout=timeout,
        env=env,
        input_bytes=input_bytes,
    )


def _git_text(
    repo: Path, *args: str, timeout: int = 60, env: dict[str, str] | None = None
) -> str:
    return _must(
        _git(repo, *args, timeout=timeout, env=env), "git " + " ".join(args)
    )


def _nul_paths(raw: str) -> list[str]:
    return sorted(p for p in raw.split("\0") if p)


def _diff_entries(raw: str) -> list[dict[str, str]]:
    tokens = raw.split("\0")
    rows: list[dict[str, str]] = []
    index = 0
    while index + 1 < len(tokens):
        status = tokens[index]
        if not status:
            index += 1
            continue
        if status[0] not in "AMDRCTU":
            raise PilotError(f"unexpected diff status: {status!r}")
        rows.append({"status": status, "path": tokens[index + 1]})
        index += 2
    return rows


def under_prefix(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def validate_source_prefix(prefix: str) -> str:
    cleaned = prefix.strip("/")
    parts = cleaned.split("/")
    if len(parts) != 2 or parts[0] != SOURCE_ROOT or not parts[1]:
        raise PilotError(
            f"source prefix must be {SOURCE_ROOT}/<repo_id>, got {prefix!r}"
        )
    return cleaned


def validate_task_id(task_id: str) -> str:
    if not task_id.startswith("csp-task-") or not TASK_PAIR_DIGEST_PATTERN.match(
        task_id.removeprefix("csp-task-")
    ):
        raise PilotError(f"invalid controlled task id: {task_id!r}")
    return task_id


def _tree_entries(repo: Path, tree: str) -> list[dict[str, Any]]:
    raw = _git_text(repo, "ls-tree", "-r", "-l", "-z", tree)
    entries = []
    for token in raw.split("\0"):
        if not token:
            continue
        meta, path = token.split("\t", 1)
        mode, kind, blob, size = meta.split()
        entries.append(
            {
                "path": path,
                "mode": mode,
                "type": kind,
                "blob": blob,
                "size": int(size) if size.isdigit() else None,
            }
        )
    entries.sort(key=lambda row: row["path"])
    return entries


def fs_inventory(root: Path, *, hash_files: bool) -> list[dict[str, Any]]:
    """Full filesystem inventory, excluding Git metadata, with optional SHA-256."""
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append(
                    {"path": rel, "mode": "120000", "type": "symlink", "target": os.readlink(path)}
                )
            else:
                stat = path.stat()
                row = {
                    "path": rel,
                    "mode": "100755" if stat.st_mode & 0o111 else "100644",
                    "type": "file",
                    "size": stat.st_size,
                }
                if hash_files:
                    row["sha256"] = sha256(path.read_bytes())
                entries.append(row)
    entries.sort(key=lambda row: row["path"])
    return entries


def inventory_digest(entries: Iterable[dict[str, Any]]) -> str:
    return sha256(canonical_json(list(entries)))


def inventory_mismatch(
    tree_rows: list[dict[str, Any]], fs_rows: list[dict[str, Any]], *, allow_fs_only: bool = False
) -> list[str]:
    """Compare Git tree paths, modes and types with a filesystem listing."""
    def shape(row: dict[str, Any]) -> tuple[str, str]:
        if row["mode"] == "120000":
            return row["mode"], "symlink"
        if row["type"] == "blob":
            return row["mode"], "file"
        return row["mode"], row["type"]

    tree = {row["path"]: shape(row) for row in tree_rows}
    disk = {row["path"]: shape(row) for row in fs_rows}
    problems = []
    for path in sorted(set(tree) | set(disk)):
        if path not in tree:
            if not allow_fs_only:
                problems.append(f"filesystem-only path: {path}")
        elif path not in disk:
            problems.append(f"missing on disk: {path}")
        elif tree[path] != disk[path]:
            problems.append(f"mode or type differs: {path} tree={tree[path]} disk={disk[path]}")
    return problems


def empty_dirs_outside(repo: Path, prefix: str) -> list[str]:
    """Find empty directories outside the assigned prefix. Git tracks no empty dirs."""
    found = []
    for dirpath, dirnames, filenames in os.walk(repo.resolve(), followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        rel = Path(dirpath).resolve().relative_to(repo.resolve()).as_posix()
        if rel == ".":
            continue
        if not dirnames and not filenames and not under_prefix(rel, prefix):
            found.append(rel)
    return sorted(found)


def worktree_state(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    if not repo.is_dir():
        raise PilotError(f"worktree does not exist: {repo}")
    commands: dict[str, dict[str, Any]] = {}
    for key, args in {
        "head": ("rev-parse", "HEAD"),
        "head_tree": ("rev-parse", "HEAD^{tree}"),
        "index_tree": ("write-tree",),
        "branch": ("branch", "--show-current"),
        "status": (
            "status",
            "--porcelain=v2",
            "--branch",
            "--untracked-files=all",
            "--ignored=matching",
        ),
        "untracked": ("ls-files", "--others", "--exclude-standard", "--full-name", "-z"),
        "ignored": ("ls-files", "--others", "--ignored", "--exclude-standard", "--full-name", "-z"),
        "tracked": ("ls-files", "--stage", "-z"),
        "changed": ("diff", "--name-only", "-z", "HEAD"),
        "staged": ("diff", "--cached", "--name-only", "-z", "HEAD"),
    }.items():
        commands[key] = _git(repo, *args)
    values = {
        key: _must(commands[key], f"snapshot {key}")
        for key in ("head", "head_tree", "index_tree")
    }
    status_raw = commands["status"]["stdout"]
    status_entries = [line for line in status_raw.splitlines() if line and not line.startswith("# ")]
    untracked = _nul_paths(commands["untracked"]["stdout"])
    ignored = _nul_paths(commands["ignored"]["stdout"])
    changed = sorted(
        set(_nul_paths(commands["changed"]["stdout"]))
        | set(_nul_paths(commands["staged"]["stdout"]))
    )
    common = Path(_git_text(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    return {
        "repo_path": str(repo),
        "git_dir": _git_text(repo, "rev-parse", "--absolute-git-dir"),
        "git_common_dir": str(common),
        "branch": commands["branch"]["stdout"].strip(),
        "head": values["head"],
        "head_tree": values["head_tree"],
        "index_tree": values["index_tree"],
        "status": status_raw,
        "status_entries": status_entries,
        "untracked": untracked,
        "ignored": ignored,
        "changed": changed,
        "tracked_index": commands["tracked"]["stdout"],
        "clean": not status_entries
        and not untracked
        and values["index_tree"] == values["head_tree"],
        "commands": commands,
        "captured_at": now(),
    }


def _run_record_path(root: Path) -> Path:
    return root / "run.json"


def load_run_record(root: Path) -> dict[str, Any]:
    path = _run_record_path(root)
    if not path.is_file():
        raise PilotError(f"frozen run record is missing: {path}")
    return load_json(path)


def capture_path(root: Path, task_id: str) -> Path:
    return root / "captures" / f"{task_id}.json"


def output_path(root: Path, task_id: str) -> Path:
    return root / "outputs" / task_id


def run_path(root: Path, task_id: str) -> Path:
    return root / "runs" / f"{task_id}.json"


def replay_path(root: Path, pair_id: str) -> Path:
    return root / "replay" / f"{pair_id}.json"


def scratch_path(root: Path, *parts: str) -> Path:
    path = root / "scratch" / Path(*parts, f"{now().replace(':', '').replace('-', '')}")
    path.mkdir(parents=True, exist_ok=False)
    return path


def capture(
    task_id: str,
    worktree: Path,
    source_prefix: str,
    expected_source_tree: str,
    upstream_commit: str,
    root: Path,
    namespace: str,
    phase: str = "first_child_action_before_edits",
) -> dict[str, Any]:
    """Record the parent snapshot and the assigned source subtree before edits."""
    validate_task_id(task_id)
    prefix = validate_source_prefix(source_prefix)
    root = evidence_root(root, namespace, create=True)
    repo = worktree.resolve()
    state = worktree_state(repo)
    run = load_run_record(root)
    if run.get("namespace") != namespace:
        raise PilotError("run record namespace differs from the evidence namespace")

    subtree = _git(repo, "rev-parse", f"{state['head_tree']}:{prefix}")
    problems: list[str] = []
    parent_pin = run.get("anchor", {})
    if parent_pin.get("commit") and state["head"] != parent_pin["commit"]:
        problems.append("parent HEAD is not the prepared anchor commit")
    if parent_pin.get("tree") and state["head_tree"] != parent_pin["tree"]:
        problems.append("parent tree is not the prepared anchor tree")
    if subtree["returncode"] != 0:
        problems.append(f"assigned source subtree is missing: {prefix}")
        actual_tree = None
    else:
        actual_tree = subtree["stdout"].strip()
        if actual_tree != expected_source_tree:
            problems.append("assigned source subtree differs from the pinned upstream tree")
    if not state["clean"]:
        problems.append("worktree start is dirty or the index differs from HEAD")

    outside = sorted(
        {
            path
            for path in state["changed"] + state["untracked"]
            if path and not under_prefix(path, prefix)
        }
    )
    outside_dirs = empty_dirs_outside(repo, prefix)
    if outside:
        problems.append("changes outside the assigned source prefix exist at start")
    if outside_dirs:
        problems.append("untracked empty directories exist outside the assigned source prefix")
    if state["index_tree"] != state["head_tree"]:
        outside_index = _index_paths_outside(repo, state["head_tree"], prefix)
        if outside_index:
            problems.append("index differs from HEAD outside the assigned source prefix")

    upstream_tree_check = _git(repo, "rev-parse", f"{upstream_commit}^{{tree}}")
    upstream_tree_value = (
        upstream_tree_check["stdout"].strip()
        if upstream_tree_check["returncode"] == 0
        else None
    )
    if upstream_tree_value != expected_source_tree:
        problems.append(
            "the expected source tree does not match the recorded upstream commit tree"
        )

    inventory = _tree_entries(repo, actual_tree) if actual_tree else []
    disk = fs_inventory(repo / prefix, hash_files=True) if (repo / prefix).is_dir() else []
    if actual_tree:
        inventory_problems = inventory_mismatch(inventory, disk)
        if inventory_problems:
            problems.extend(inventory_problems[:20])
    extra_source = sorted(path for path in state["untracked"] if under_prefix(path, prefix))
    if extra_source:
        problems.append("untracked files exist inside the assigned source prefix at start")

    record = {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": run.get("run_id"),
        "evidence_namespace": namespace,
        "task_id": task_id,
        "phase": phase,
        "captured_at": now(),
        "source_prefix": prefix,
        "capture_policy": run.get("capture_policy", DEFAULT_CAPTURE_POLICY),
        "parent_snapshot": {
            "head": state["head"],
            "tree": state["head_tree"],
            "index_tree": state["index_tree"],
            "branch": state["branch"],
            "clean": state["clean"],
            "repo_path": state["repo_path"],
            "git_dir": state["git_dir"],
            "git_common_dir": state["git_common_dir"],
            "status": state["status"],
            "status_entries": state["status_entries"],
            "untracked": state["untracked"],
            "ignored": state["ignored"],
            "changed": state["changed"],
            "tracked_index": state["tracked_index"],
            "is_anchor": state["head"] == parent_pin.get("commit"),
            "anchor_ref": parent_pin.get("ref"),
            "note": "This is a CollisionGuard parent snapshot, not an upstream commit.",
        },
        "original_source": {
            "upstream_commit": upstream_commit,
            "upstream_tree": expected_source_tree,
            "upstream_commit_tree": upstream_tree_value,
            "upstream_commit_matches_tree": upstream_tree_value == expected_source_tree,
            "subtree_path_in_parent": prefix,
            "actual_subtree_tree": actual_tree,
            "subtree_matches_upstream": actual_tree == expected_source_tree,
            "inventory": inventory,
            "inventory_sha256": inventory_digest(inventory),
            "filesystem_inventory": disk,
            "filesystem_inventory_sha256": inventory_digest(disk),
        },
        "parent_versus_upstream": {
            "parent_head": state["head"],
            "parent_tree": state["head_tree"],
            "upstream_commit": upstream_commit,
            "upstream_tree": expected_source_tree,
            "distinct_ids": state["head"] != upstream_commit
            or state["head_tree"] != expected_source_tree,
        },
        "scope": {
            "prefix": prefix,
            "untracked_inside_prefix": extra_source,
            "changes_outside_prefix": outside,
            "empty_dirs_outside_prefix": outside_dirs,
        },
        "verdict": {"ok": not problems, "problems": problems, "label_blocked": bool(problems)},
        "commands": {"subtree": subtree},
    }
    target = capture_path(root, task_id)
    if target.exists():
        old = load_json(target)
        comparable = ("task_id", "source_prefix")
        same_parent = old.get("parent_snapshot", {}).get("head") == state["head"]
        same_source = (
            old.get("original_source", {}).get("actual_subtree_tree") == actual_tree
        )
        if (
            any(old.get(key) != record[key] for key in comparable)
            or not same_parent
            or not same_source
        ):
            raise PilotError("an immutable capture already exists and differs")
        event(root, "capture_reused", task_id=task_id, ok=old["verdict"]["ok"])
        return old
    dump_json(target, record)
    event(
        root,
        "capture_recorded",
        task_id=task_id,
        source_prefix=prefix,
        ok=record["verdict"]["ok"],
        problems=problems,
        parent_head=state["head"],
        source_tree=actual_tree,
    )
    return record


def _status_path(line: str) -> str:
    # porcelain=v2 lines: "1 XY sub mH mI mW hH hI path" and "? path".
    if line.startswith("? "):
        return line[2:]
    parts = line.split(" ", 8)
    return parts[8] if len(parts) == 9 else line


def _index_paths_outside(repo: Path, base_tree: str, prefix: str) -> list[str]:
    tree = _git_text(repo, "write-tree")
    diff = _git(repo, "diff", "--name-status", "--no-renames", "-z", base_tree, tree)
    _must(diff, "index scope diff")
    return [row["path"] for row in _diff_entries(diff["stdout"]) if not under_prefix(row["path"], prefix)]


def _commit_env(timestamp: str | None = None) -> dict[str, str]:
    env = {
        "GIT_AUTHOR_NAME": "controlled-single-project",
        "GIT_AUTHOR_EMAIL": "controlled-single-project@example.invalid",
        "GIT_COMMITTER_NAME": "controlled-single-project",
        "GIT_COMMITTER_EMAIL": "controlled-single-project@example.invalid",
    }
    if timestamp:
        env["GIT_AUTHOR_DATE"] = timestamp
        env["GIT_COMMITTER_DATE"] = timestamp
    return env


def replay_patch(
    patch_bytes: bytes,
    base_tree: str,
    objects_dir: Path,
    scratch: Path,
    name: str,
) -> dict[str, Any]:
    """Apply one complete source patch to the pinned tree in a fresh repository."""
    dest = scratch / name
    dest.mkdir(parents=True, exist_ok=False)
    init = _run(["git", "init", "-q", str(dest)], cwd=dest)
    if init["returncode"] != 0:
        return {"ok": False, "init": init, "error": "git init failed"}
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str(objects_dir.resolve()) + "\n", encoding="utf-8")
    read = _run(["git", "-C", str(dest), "read-tree", base_tree], cwd=dest)
    if read["returncode"] != 0:
        return {"ok": False, "init": init, "read_tree": read, "error": "read-tree failed"}
    checkout = _run(["git", "-C", str(dest), "checkout-index", "-a", "-f"], cwd=dest)
    if checkout["returncode"] != 0:
        return {
            "ok": False,
            "init": init,
            "read_tree": read,
            "checkout": checkout,
            "error": "checkout-index failed",
        }
    # read-tree plus checkout-index leaves a stale stat cache; apply --index
    # rejects even byte-identical files until the index is refreshed.
    refresh = _run(["git", "-C", str(dest), "update-index", "--refresh"], cwd=dest)
    if refresh["returncode"] != 0:
        return {
            "ok": False,
            "init": init,
            "read_tree": read,
            "checkout": checkout,
            "refresh": refresh,
            "error": "update-index --refresh failed",
        }
    patch_file = scratch / f"{name}.patch"
    patch_file.write_bytes(patch_bytes)
    if not patch_bytes:
        tree = _run(["git", "-C", str(dest), "write-tree"], cwd=dest)
        if tree["returncode"] != 0:
            return {
                "ok": False,
                "init": init,
                "read_tree": read,
                "checkout": checkout,
                "refresh": refresh,
                "write_tree": tree,
                "error": "write-tree failed for the empty patch",
            }
        return {
            "ok": True,
            "empty_patch": True,
            "init": init,
            "read_tree": read,
            "checkout": checkout,
            "refresh": refresh,
            "tree": tree["stdout"].strip(),
            "repo_path": str(dest),
            "patch_path": str(patch_file),
        }
    apply = _run(
        ["git", "-C", str(dest), "apply", "--index", "--binary", str(patch_file)],
        cwd=dest,
    )
    if apply["returncode"] != 0 or apply["timed_out"]:
        return {
            "ok": False,
            "init": init,
            "read_tree": read,
            "checkout": checkout,
            "refresh": refresh,
            "apply": apply,
            "error": "patch did not apply",
        }
    tree = _run(["git", "-C", str(dest), "write-tree"], cwd=dest)
    if tree["returncode"] != 0:
        return {
            "ok": False,
            "init": init,
            "read_tree": read,
            "checkout": checkout,
            "refresh": refresh,
            "apply": apply,
            "write_tree": tree,
            "error": "write-tree failed",
        }
    return {
        "ok": True,
        "init": init,
        "read_tree": read,
        "checkout": checkout,
        "refresh": refresh,
        "apply": apply,
        "write_tree": tree,
        "tree": tree["stdout"].strip(),
        "repo_path": str(dest),
        "patch_path": str(patch_file),
    }


def capture_policy(name: str) -> dict[str, Any]:
    """Return the frozen policy definition, or refuse an unknown policy."""
    try:
        return {"name": name, **CAPTURE_POLICIES[name]}
    except KeyError:
        raise PilotError(f"unknown capture policy: {name!r}") from None


def stage_worktree(
    repo: Path, base_tree: str, scratch: Path, *, ordinary_git_staging: bool
) -> tuple[dict[str, Any], str]:
    """Stage the final worktree with the frozen policy and return its tree.

    The alternate index starts from the parent tree, so tracked paths stay
    tracked even when an ignore rule also matches them.
    """
    index_file = scratch / "final.index"
    env = {"GIT_INDEX_FILE": str(index_file)}
    read = _git(repo, "read-tree", base_tree, env=env)
    _must(read, "read-tree before final staging")
    args = ["add", "--all"]
    if not ordinary_git_staging:
        args.append("--force")
    args.extend(["--", "."])
    add = _git(repo, *args, env=env)
    if add["returncode"] != 0 or add["timed_out"]:
        raise PilotError(f"staging the final worktree failed: {add['stderr'][:800]}")
    tree = _git_text(repo, "write-tree", env=env)
    return {"read_tree": read, "add": add}, tree


def ordinary_source_tree(
    repo: Path,
    expected_tree: str,
    source_dir: Path,
    scratch: Path,
    label: str,
) -> dict[str, Any]:
    """Derive one source tree from its pinned tree with ordinary Git staging.

    A fresh Git directory receives the parent object database as a read-only
    alternate. ``read-tree`` seeds tracked paths so a committed file that matches
    an ignore rule stays tracked. ``git add --all`` then applies the source
    repository's own ignore rules, without ``--force``.
    """
    dest = scratch / f"ordinary-{label}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    init = _run(["git", "init", "--quiet", "--template=", str(dest)], cwd=dest)
    _must(init, "git init for ordinary staging")
    git_dir = dest / ".git"
    objects = Path(_git_text(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "objects"
    alternates = git_dir / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str(objects) + "\n", encoding="utf-8")
    env = {
        "GIT_DIR": str(git_dir),
        "GIT_WORK_TREE": str(source_dir),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    read_tree = _run(["git", "read-tree", expected_tree], cwd=source_dir, env=env)
    _must(read_tree, "git read-tree for ordinary staging")
    add = _run(["git", "add", "--all", "--", "."], cwd=source_dir, env=env)
    _must(add, "git add for ordinary staging")
    write_tree = _run(["git", "write-tree"], cwd=source_dir, env=env)
    _must(write_tree, "git write-tree for ordinary staging")
    return {
        "ok": True,
        "tree": write_tree["stdout"].strip(),
        "git_dir": str(git_dir),
        "work_tree": str(source_dir),
        "init": init,
        "read_tree": read_tree,
        "add": add,
        "write_tree": write_tree,
    }


def collect(
    task_id: str,
    worktree: Path,
    root: Path,
    namespace: str,
) -> dict[str, Any]:
    """Capture the complete final tree, extract the source subtree, and replay it."""
    validate_task_id(task_id)
    root = evidence_root(root, namespace, create=True)
    cap_path = capture_path(root, task_id)
    if not cap_path.is_file():
        raise PilotError("start capture is missing; the task cannot be collected")
    cap = load_json(cap_path)
    if cap.get("evidence_namespace") != namespace:
        raise PilotError("capture namespace differs from the collection namespace")
    if not cap.get("verdict", {}).get("ok"):
        raise PilotError("start capture was not valid; labels stay blocked")

    prefix = cap["source_prefix"]
    base_tree = cap["parent_snapshot"]["tree"]
    expected_source = cap["original_source"]["upstream_tree"]
    repo = worktree.resolve()
    state = worktree_state(repo)
    problems: list[str] = []
    if state["head"] != cap["parent_snapshot"]["head"]:
        problems.append("HEAD moved after the start capture")

    scratch = scratch_path(root, "collect", task_id)
    policy = capture_policy(cap.get("capture_policy", DEFAULT_CAPTURE_POLICY))
    add, final_tree = stage_worktree(
        repo, base_tree, scratch, ordinary_git_staging=policy["ordinary_git_staging"]
    )

    changed_result = _git(repo, "diff", "--name-status", "--no-renames", "-z", base_tree, final_tree)
    _must(changed_result, "final tree scope diff")
    changed = _diff_entries(changed_result["stdout"])
    outside = [row for row in changed if not under_prefix(row["path"], prefix)]
    outside_dirs = empty_dirs_outside(repo, prefix)
    if outside:
        problems.append("changes outside the assigned source prefix exist")
    if outside_dirs:
        problems.append("untracked empty directories exist outside the assigned source prefix")
    inside_deleted_prefix = any(
        row["path"] == prefix or row["path"].startswith(prefix + "/") for row in changed if row["status"][0] == "D"
    )

    final_subtree_result = _git(repo, "rev-parse", f"{final_tree}:{prefix}")
    worktree_subtree = (
        final_subtree_result["stdout"].strip() if final_subtree_result["returncode"] == 0 else None
    )
    ordinary_derivations: list[dict[str, Any]] = []
    derived_trees: list[str] = []
    if policy["ordinary_git_staging"]:
        source_dir = repo / prefix
        if source_dir.is_dir():
            for repeat in ("repeat-1", "repeat-2"):
                ordinary_derivations.append(
                    ordinary_source_tree(
                        repo, expected_source, source_dir, scratch, repeat
                    )
                )
            derived_trees = [row["tree"] for row in ordinary_derivations]
            if len(set(derived_trees)) != 1:
                problems.append("ordinary staging repeats derived different source trees")
            final_subtree = derived_trees[0]
        else:
            final_subtree = None
    else:
        final_subtree = worktree_subtree
    if final_subtree is None or inside_deleted_prefix:
        problems.append("assigned source subtree is missing or deleted in the final tree")
        final_subtree = None

    diff = _git(
        repo,
        "diff",
        "--binary",
        "--full-index",
        "--no-renames",
        expected_source,
        final_subtree or expected_source,
    )
    _must(diff, "source-relative binary diff")
    patch = base64.b64decode(diff["stdout_base64"])
    summary = _git(repo, "diff", "--summary", "--no-renames", expected_source, final_subtree or expected_source)
    _must(summary, "source diff summary")
    relative_changes = _git(
        repo,
        "diff",
        "--name-status",
        "--no-renames",
        "-z",
        expected_source,
        final_subtree or expected_source,
    )
    _must(relative_changes, "source changed paths")
    relative_rows = _diff_entries(relative_changes["stdout"])
    relative_paths = [row["path"] for row in relative_rows]

    output_dir = output_path(root, task_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    patch_file = output_dir / "source.patch"
    patch_file.write_bytes(patch)

    final_inventory = _tree_entries(repo, final_subtree) if final_subtree else []
    disk = fs_inventory(repo / prefix, hash_files=True) if (repo / prefix).is_dir() else []
    inventory_problems = (
        inventory_mismatch(
            final_inventory,
            disk,
            allow_fs_only=policy["ordinary_git_staging"],
        )
        if final_subtree
        else ["no source subtree"]
    )
    if inventory_problems:
        problems.append("final source filesystem differs from the captured source tree")
    tree_paths = {row["path"] for row in final_inventory}
    filesystem_only = sorted(row["path"] for row in disk if row["path"] not in tree_paths)

    objects_dir = Path(state["git_common_dir"]) / "objects"
    replays = []
    if final_subtree:
        for repeat in ("repeat-1", "repeat-2"):
            replays.append(
                replay_patch(patch, expected_source, objects_dir, scratch, repeat)
            )
    replay_trees = [row.get("tree") for row in replays]
    replay_ok = (
        bool(replays)
        and all(row.get("ok") for row in replays)
        and all(tree == final_subtree for tree in replay_trees)
    )
    if not replay_ok:
        problems.append("source patch did not independently recreate the captured source tree")

    git_version = _must(_run(["git", "--version"], timeout=10), "git --version")
    if git_version != GIT_PIN:
        problems.append(f"replay Git is {git_version}, not {GIT_PIN}")

    artifacts = sorted(path for path in relative_paths if is_artifact(path))
    record = {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": cap.get("run_id"),
        "evidence_namespace": namespace,
        "task_id": task_id,
        "pair_id": cap.get("pair_id"),
        "repo_id": prefix.split("/", 1)[1],
        "collected_at": now(),
        "worktree": str(repo),
        "parent_snapshot": {
            "head": state["head"],
            "tree": base_tree,
            "head_unchanged": state["head"] == cap["parent_snapshot"]["head"],
        },
        "start_source_tree": expected_source,
        "final_source_tree": final_subtree,
        "source_tree_unchanged": final_subtree == expected_source,
        "final_full_tree": final_tree,
        "final_index_tree": state["index_tree"],
        "final_status": state["status"],
        "capture_policy": {
            "name": policy["name"],
            "method": policy["method"],
            "ordinary_git_staging": policy["ordinary_git_staging"],
            "description": policy["description"],
        },
        "staging": {
            "worktree_full_tree": final_tree,
            "worktree_prefix_tree": worktree_subtree,
            "derived_source_trees": derived_trees,
            "derived_source_tree": final_subtree,
            "ordinary_derivations": ordinary_derivations,
            "filesystem_only_paths": filesystem_only,
            "filesystem_only_count": len(filesystem_only),
        },
        "changed_paths_outside_prefix": [row["path"] for row in outside],
        "empty_dirs_outside_prefix": outside_dirs,
        "all_changed_paths_in_parent": [row["path"] for row in changed],
        "changed_paths": relative_paths,
        "change_status": relative_rows,
        "diff_summary": summary["stdout"],
        "artifacts": artifacts,
        "nonempty": bool(patch),
        "patch_bytes": len(patch),
        "patch_sha256": sha256(patch),
        "patch_file": str(patch_file.relative_to(root)),
        "patch_sha256_on_disk": sha256(patch_file.read_bytes()),
        "final_inventory": final_inventory,
        "final_inventory_sha256": inventory_digest(final_inventory),
        "filesystem_inventory_sha256": inventory_digest(disk),
        "replays": replays,
        "replay_trees": replay_trees,
        "replay_ok": replay_ok,
        "git_version": git_version,
        "verdict": {
            "ok": not problems,
            "problems": problems,
            "label_blocked": bool(problems),
        },
        "commands": {
            "stage": add,
            "changed": changed_result,
            "final_subtree": final_subtree_result,
            "diff": diff,
            "summary": summary,
            "relative_changes": relative_changes,
        },
        "scratch": str(scratch),
    }
    target = output_dir / "record.json"
    if target.exists():
        old = load_json(target)
        if old.get("final_full_tree") != final_tree or old.get("final_source_tree") != final_subtree:
            raise PilotError("an output record already exists and the final tree differs")
        event(root, "collect_reused", task_id=task_id)
        return old
    dump_json(target, record)
    event(
        root,
        "collected",
        task_id=task_id,
        ok=record["verdict"]["ok"],
        problems=problems,
        patch_sha256=record["patch_sha256"],
        nonempty=record["nonempty"],
        replay_ok=replay_ok,
    )
    return record


def is_artifact(path: str) -> bool:
    p = Path(path)
    return any(part in ARTIFACT_PARTS for part in p.parts) or p.suffix in {".pyc", ".pyo", ".coverage"}


def validate_plan(plan: dict[str, Any], root: Path) -> None:
    repos = plan.get("repositories", [])
    pairs = plan.get("pairs", [])
    tasks = plan.get("tasks", [])
    if len(repos) != 5 or len(pairs) != 5 or len(tasks) != 10:
        raise PilotError("the frozen plan must contain five repositories, five pairs, and ten tasks")
    if plan.get("coding_selection") != CODING_MODEL:
        raise PilotError("the frozen plan does not use the DeepSeek V4.1 Flash selection")
    if plan.get("capture_policy") not in CAPTURE_POLICIES:
        raise PilotError("the frozen plan does not name a known capture policy")
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
        if pair.get("task_ids") != sorted(task["task_id"] for task in members):
            raise PilotError(f"pair {pair['pair_id']} task ids disagree with its tasks")
    for task in tasks:
        if task.get("repo_id") not in repo_ids or task.get("pair_id") not in pair_ids:
            raise PilotError(f"task {task['task_id']} has an unknown source or pair")
        prompt = root / task["prompt_file"]
        if not prompt.is_file() or sha256(prompt.read_bytes()) != task.get("prompt_sha256"):
            raise PilotError(f"frozen prompt hash mismatch for {task['task_id']}")
        prefix = validate_source_prefix(task["source_prefix"])
        if prefix.split("/", 1)[1] != task["repo_id"]:
            raise PilotError(f"task {task['task_id']} prefix does not name its repository")
    digest = plan.get("plan_sha256")
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if digest != sha256(canonical_json(canonical)):
        raise PilotError("frozen plan digest mismatch")


def load_plan(root: Path) -> dict[str, Any]:
    path = root / "plan.json"
    if not path.is_file():
        raise PilotError(f"frozen plan is missing: {path}")
    plan = load_json(path)
    validate_plan(plan, root)
    return plan


def tasks_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["task_id"]: task for task in plan.get("tasks", [])}


def source_starts_match(first: dict[str, Any], second: dict[str, Any]) -> tuple[bool, list[str]]:
    fields = (
        ("original_source", "upstream_tree"),
        ("original_source", "actual_subtree_tree"),
        ("original_source", "inventory_sha256"),
        ("parent_snapshot", "head"),
        ("parent_snapshot", "tree"),
    )
    differences = []
    for group, key in fields:
        if first.get(group, {}).get(key) != second.get(group, {}).get(key):
            differences.append(f"{group}.{key}")
    return not differences, differences


def label_from_repeats(
    repeats: list[dict[str, Any]],
    *,
    starts_equal: bool,
    nonempty: list[bool],
    outputs_distinct: bool,
    replay_ok: bool,
    within_limits: bool,
    provenance_ok: bool,
) -> str | None:
    if not (
        starts_equal
        and all(nonempty)
        and outputs_distinct
        and replay_ok
        and within_limits
        and provenance_ok
        and len(repeats) == 2
    ):
        return None
    if any(row.get("timed_out") or row.get("returncode") not in (0, 1) for row in repeats):
        return None
    first = repeats[0]
    if any(
        (row.get("returncode"), row.get("stdout"), row.get("stderr"))
        != (first.get("returncode"), first.get("stdout"), first.get("stderr"))
        for row in repeats[1:]
    ):
        return None
    if first.get("returncode") == 0:
        return "clean"
    if first.get("returncode") == 1 and "CONFLICT" in first.get("stdout", ""):
        return "conflict"
    return None


def _merge_replay(
    commits: list[str], objects_dir: Path, scratch: Path
) -> tuple[list[dict[str, Any]], bool, str | None]:
    dest = scratch / "merge-repo"
    dest.mkdir(parents=True, exist_ok=False)
    init = _run(["git", "init", "-q", str(dest)], cwd=dest)
    if init["returncode"] != 0:
        return [], False, "merge replay repository could not be created"
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str(objects_dir.resolve()) + "\n", encoding="utf-8")
    repeats = []
    for run_no in (1, 2):
        result = _run(
            ["git", "-C", str(dest), "merge-tree", "--write-tree", commits[0], commits[1]],
            cwd=dest,
        )
        repeats.append({"merge_run": run_no, **result})
    identical = all(
        (row["returncode"], row["stdout"], row["stderr"], row["timed_out"])
        == (repeats[0]["returncode"], repeats[0]["stdout"], repeats[0]["stderr"], repeats[0]["timed_out"])
        for row in repeats[1:]
    )
    return repeats, identical, None


def record_run(task_id: str, live: dict[str, Any], root: Path, namespace: str) -> dict[str, Any]:
    """Record a launch from returned live task metadata, not from file existence."""
    validate_task_id(task_id)
    root = evidence_root(root, namespace, create=True)
    plan = load_plan(root)
    task = tasks_by_id(plan).get(task_id)
    if task is None:
        raise PilotError(f"unknown task id: {task_id}")
    cap_file = capture_path(root, task_id)
    cap = load_json(cap_file) if cap_file.is_file() else None
    raw = canonical_json(live)
    status = str(live.get("status") or live.get("threadStatus") or "unknown")
    run_id = live.get("runId") or live.get("run_id")
    provider = str(
        live.get("providerInstanceId") or live.get("provider_instance_id") or live.get("provider") or ""
    )
    model = str(live.get("model") or "")
    options = live.get("options") or []
    if isinstance(options, dict):
        options = [{"id": key, "value": value} for key, value in sorted(options.items())]
    variant = next((row.get("value") for row in options if row.get("id") == "variant"), None)
    fast = bool(live.get("fast") or live.get("fastMode") or False)
    priority = bool(live.get("priority") or False)
    selection_ok = (
        provider == CODING_MODEL["provider_instance_id"]
        and model == CODING_MODEL["model"]
        and variant == "max"
        and not fast
        and not priority
    )
    started_at = live.get("createdAt") or live.get("startedAt")
    ended_at = live.get("completedAt") or live.get("endedAt")
    duration = None
    if started_at:
        try:
            start = dt.datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            end = (
                dt.datetime.fromisoformat(str(ended_at).replace("Z", "+00:00"))
                if ended_at
                else dt.datetime.now(dt.timezone.utc)
            )
            duration = max(0.0, (end - start).total_seconds())
        except ValueError:
            duration = None
    within_limits = duration is not None and duration <= TASK_BUDGET_SECONDS
    coding_started = bool(run_id) and status in STARTED_STATUSES
    provenance_ok = bool(
        selection_ok
        and coding_started
        and cap
        and cap.get("verdict", {}).get("ok")
        and cap.get("original_source", {}).get("upstream_tree") == task["upstream_tree"]
        and cap.get("source_prefix") == task["source_prefix"]
    )
    record = {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": plan.get("run_id"),
        "evidence_namespace": namespace,
        "task_id": task_id,
        "pair_id": task["pair_id"],
        "repo_id": task["repo_id"],
        "recorded_at": now(),
        "live_metadata": live,
        "live_metadata_sha256": sha256(raw),
        "status": status,
        "thread_run_id": run_id,
        "provider_instance_id": provider,
        "model": model,
        "options": options,
        "variant": variant,
        "fast": fast,
        "priority": priority,
        "selection_ok": selection_ok,
        "coding_started": coding_started,
        "duration_seconds": duration,
        "within_limits": within_limits,
        "start_capture_ok": bool(cap and cap.get("verdict", {}).get("ok")),
        "prompt_sha256": task["prompt_sha256"],
        "prompt_hash_matches_plan": sha256(
            (root / task["prompt_file"]).read_bytes()
        ) == task["prompt_sha256"],
        "anchor_ok": bool(
            cap and cap.get("parent_snapshot", {}).get("head") == plan.get("anchor", {}).get("commit")
        ),
        "provenance_ok": provenance_ok,
    }
    target = run_path(root, task_id)
    if target.exists():
        old = load_json(target)
        if old.get("live_metadata_sha256") != record["live_metadata_sha256"]:
            raise PilotError("a different run record already exists for this task")
        event(root, "run_reused", task_id=task_id)
        return old
    dump_json(target, record)
    event(
        root,
        "run_recorded",
        task_id=task_id,
        status=status,
        coding_started=coding_started,
        selection_ok=selection_ok,
        duration_seconds=duration,
    )
    return record


def replay_pair(pair_id: str, root: Path) -> dict[str, Any]:
    root = root.resolve()
    plan = load_plan(root)
    pair = next((row for row in plan["pairs"] if row["pair_id"] == pair_id), None)
    if pair is None:
        raise PilotError(f"unknown pair id: {pair_id}")
    task_rows = [task for task in plan["tasks"] if task["pair_id"] == pair_id]
    if len(task_rows) != 2:
        raise PilotError("pair does not have exactly two frozen tasks")
    caps = []
    outputs = []
    runs = []
    for task in task_rows:
        cap_file = capture_path(root, task["task_id"])
        out_file = output_path(root, task["task_id"]) / "record.json"
        run_file = run_path(root, task["task_id"])
        caps.append(load_json(cap_file) if cap_file.is_file() else None)
        outputs.append(load_json(out_file) if out_file.is_file() else None)
        runs.append(load_json(run_file) if run_file.is_file() else None)
    attempted = all(run and run.get("coding_started") is True for run in runs)
    missing = [task["task_id"] for task, output in zip(task_rows, outputs) if output is None]
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": plan.get("run_id"),
        "pair_id": pair_id,
        "repo_id": pair["repo_id"],
        "replayed_at": now(),
        "git_version": _must(_run(["git", "--version"], timeout=10), "git --version"),
        "attempted": attempted,
        "missing_output_task_ids": missing,
        "exclusion_reasons": [],
        "label": None,
        "qualifies": False,
    }
    checks: list[tuple[bool, str]] = []
    if missing:
        checks.append((False, "one or more task outputs were not collected"))
    if not attempted:
        checks.append((False, "both coding runs were not confirmed started"))
    starts_equal = False
    if all(caps):
        starts_equal, differences = source_starts_match(caps[0], caps[1])
        result["starting_snapshot_differences"] = differences
        checks.append((starts_equal, "paired starts do not share the same original source tree"))
        checks.append(
            (
                all(cap.get("verdict", {}).get("ok") for cap in caps),
                "one or more start captures were not valid",
            )
        )
    else:
        checks.append((False, "one or more start captures are missing"))
        result["starting_snapshot_differences"] = ["capture missing"]
    result["starting_snapshots_equal"] = starts_equal
    if all(outputs) and all(caps):
        result["patches_nonempty"] = [row["nonempty"] for row in outputs]
        first_sha = outputs[0]["patch_sha256"]
        second_sha = outputs[1]["patch_sha256"]
        distinct = first_sha != second_sha
        replay_ok = all(row.get("replay_ok") for row in outputs)
        heads_ok = all(row.get("parent_snapshot", {}).get("head_unchanged") for row in outputs)
        source_unchanged = [row.get("source_tree_unchanged") for row in outputs]
        checks.extend(
            [
                (all(result["patches_nonempty"]), "at least one output is empty"),
                (distinct, "outputs are byte-identical"),
                (replay_ok, "a source patch did not recreate its captured source tree"),
                (heads_ok, "a child moved HEAD"),
                (not any(source_unchanged), "a task made no change to its source tree"),
            ]
        )
        result.update(
            {
                "patches_distinct": distinct,
                "patch_sha256": [first_sha, second_sha],
                "changed_paths": [row.get("changed_paths", []) for row in outputs],
                "artifacts": [row.get("artifacts", []) for row in outputs],
                "final_source_trees": [row.get("final_source_tree") for row in outputs],
            }
        )
    else:
        result["patches_nonempty"] = [row["nonempty"] if row else None for row in outputs]
        result["patches_distinct"] = False
    result.update(
        {
            "task_run_records": [str(run_path(root, task["task_id"]).relative_to(root)) for task in task_rows],
            "task_capture_records": [str(capture_path(root, task["task_id"]).relative_to(root)) for task in task_rows],
            "within_limits": [bool(run and run.get("within_limits")) for run in runs],
            "provenance_ok": [bool(run and run.get("provenance_ok")) for run in runs],
            "merge_repeats_identical": False,
        }
    )
    checks.extend(
        [
            (all(result["within_limits"]), "one or more runs exceeded or did not prove the time budget"),
            (all(result["provenance_ok"]), "one or more runs have missing or contradictory provenance"),
            (result["git_version"] == GIT_PIN, f"{GIT_PIN} is unavailable"),
        ]
    )

    if all(outputs) and all(caps) and not missing:
        scratch = scratch_path(root, "replay", pair_id)
        common_text = caps[0]["parent_snapshot"]["git_common_dir"]
        objects_dir = Path(common_text) / "objects"
        commits: list[str | None] = []
        for index, output in enumerate(outputs):
            tree = output.get("final_source_tree")
            if not tree:
                commits.append(None)
                continue
            upstream = caps[index]["original_source"]["upstream_commit"]
            upstream_ok = _git(
                Path(caps[index]["parent_snapshot"]["repo_path"]),
                "cat-file",
                "-e",
                upstream,
            )
            parents = ["-p", upstream] if upstream_ok["returncode"] == 0 else []
            commit = _git(
                Path(caps[index]["parent_snapshot"]["repo_path"]),
                "commit-tree",
                tree,
                *parents,
                "-m",
                f"controlled-single-project side {index}",
                env=_commit_env(),
            )
            commits.append(commit["stdout"].strip() if commit["returncode"] == 0 else None)
            result.setdefault("side_commits", []).append(commit)
        if all(commits):
            repeats, identical, error = _merge_replay(commits, objects_dir, scratch)  # type: ignore[arg-type]
            result["repeat_runs"] = repeats
            result["merge_repeats_identical"] = identical
            if error:
                checks.append((False, error))
            if not identical:
                checks.append((False, "the two full-tree merge replays differ"))
            result["label"] = label_from_repeats(
                repeats,
                starts_equal=starts_equal,
                nonempty=result.get("patches_nonempty", [False, False]),
                outputs_distinct=result.get("patches_distinct", False),
                replay_ok=all(row.get("replay_ok") for row in outputs),
                within_limits=all(result["within_limits"]),
                provenance_ok=all(result["provenance_ok"]),
            )
            if result["label"] is None:
                checks.append((False, "merge-tree returned an error or unknown result"))
        else:
            checks.append((False, "could not construct both replay commits"))
    result["exclusion_reasons"] = [message for ok, message in checks if not ok]
    if result["exclusion_reasons"]:
        result["label"] = None
    result["qualifies"] = result["label"] in {"clean", "conflict"} and not result["exclusion_reasons"]
    target = replay_path(root, pair_id)
    dump_json(target, result)
    event(
        root,
        "pair_replayed",
        pair_id=pair_id,
        label=result["label"],
        qualifies=result["qualifies"],
        reasons=result["exclusion_reasons"],
    )
    return result


def pair_rows(plan: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    rows = []
    for pair in plan["pairs"]:
        path = replay_path(root, pair["pair_id"])
        if path.is_file():
            rows.append(load_json(path))
            continue
        task_rows = [task for task in plan["tasks"] if task["pair_id"] == pair["pair_id"]]
        runs = [
            load_json(run_path(root, task["task_id"]))
            if run_path(root, task["task_id"]).is_file()
            else None
            for task in task_rows
        ]
        outputs = [
            load_json(output_path(root, task["task_id"]) / "record.json")
            if (output_path(root, task["task_id"]) / "record.json").is_file()
            else None
            for task in task_rows
        ]
        caps = [
            load_json(capture_path(root, task["task_id"]))
            if capture_path(root, task["task_id"]).is_file()
            else None
            for task in task_rows
        ]
        attempted = all(run and run.get("coding_started") is True for run in runs)
        starts_equal = False
        if all(caps):
            starts_equal = source_starts_match(caps[0], caps[1])[0]  # type: ignore[arg-type]
        rows.append(
            {
                "pair_id": pair["pair_id"],
                "repo_id": pair["repo_id"],
                "attempted": attempted,
                "label": None,
                "qualifies": False,
                "starting_snapshots_equal": starts_equal,
                "patches_nonempty": [row.get("nonempty") if row else None for row in outputs],
                "patches_distinct": bool(
                    all(outputs)
                    and outputs[0]["patch_sha256"] != outputs[1]["patch_sha256"]
                ),
                "patch_sha256": [row.get("patch_sha256") if row else None for row in outputs],
                "merge_repeats_identical": False,
                "exclusion_reasons": ["pair replay was not completed"],
                "artifacts": [row.get("artifacts", []) if row else [] for row in outputs],
            }
        )
    return rows


def feasibility(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_attempted = len(rows) == len(plan.get("pairs", [])) and all(
        row.get("attempted") is True for row in rows
    )
    eligible = [row for row in rows if row.get("qualifies")]
    repos = sorted({row["repo_id"] for row in eligible})
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


def summarize(root: Path, write: bool) -> dict[str, Any]:
    root = root.resolve()
    plan = load_plan(root)
    rows = pair_rows(plan, root)
    summary = {
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": now(),
        "run_id": plan["run_id"],
        "plan_sha256": plan["plan_sha256"],
        "producer_sha256": plan["producer_sha256"],
        "anchor": plan["anchor"],
        "repositories": [
            {
                key: repo[key]
                for key in (
                    "repo_id",
                    "canonical_name",
                    "upstream_commit",
                    "upstream_tree",
                    "source_prefix",
                    "subtree_matches",
                    "license_spdx",
                )
            }
            for repo in plan["repositories"]
        ],
        "tasks": [
            {
                "task_id": task["task_id"],
                "pair_id": task["pair_id"],
                "repo_id": task["repo_id"],
                "prompt_sha256": task["prompt_sha256"],
                "coding_started": bool(
                    run_path(root, task["task_id"]).is_file()
                    and load_json(run_path(root, task["task_id"])).get("coding_started")
                ),
                "collected": (output_path(root, task["task_id"]) / "record.json").is_file(),
            }
            for task in plan["tasks"]
        ],
        "pairs": [
            {
                key: row.get(key)
                for key in (
                    "pair_id",
                    "repo_id",
                    "attempted",
                    "label",
                    "qualifies",
                    "exclusion_reasons",
                    "starting_snapshots_equal",
                    "patches_nonempty",
                    "patches_distinct",
                    "patch_sha256",
                    "merge_repeats_identical",
                    "artifacts",
                )
            }
            for row in rows
        ],
        "feasibility_gate": feasibility(plan, rows),
    }
    if write:
        dump_json(root / "public-summary.json", summary)
        event(root, "summary_written", gate=summary["feasibility_gate"])
    return summary


def build_anchor(
    parent_repo: Path,
    pins_file: Path,
    ref: str,
    root: Path,
    namespace: str,
) -> dict[str, Any]:
    """Import pinned source trees into a private parent commit without switching."""
    root = evidence_root(root, namespace, create=True)
    repo = parent_repo.resolve()
    if not git_ref(ref):
        raise PilotError(f"invalid anchor ref: {ref!r}")
    pins = load_json(pins_file)
    sources = pins.get("repositories", [])
    if not sources:
        raise PilotError("the pins file has no repositories")
    helper_source = (repo / pins.get("helper", HELPER_PATH)).resolve()
    if not helper_source.is_file():
        raise PilotError(f"helper source is missing: {helper_source}")

    before = worktree_state(repo)
    original = {
        "branch": before["branch"],
        "head": before["head"],
        "tree": before["head_tree"],
        "index_tree": before["index_tree"],
        "status_sha256": sha256(before["status"].encode()),
        "untracked": before["untracked"],
        "ignored": before["ignored"],
    }
    existing = _git(repo, "rev-parse", "--verify", ref)
    if existing["returncode"] == 0:
        raise PilotError(f"anchor ref already exists; refusing to overwrite: {ref}")
    prefix_present = _git(repo, "ls-tree", "--name-only", before["head_tree"], SOURCE_ROOT)
    if prefix_present["stdout"].strip():
        raise PilotError(f"parent HEAD already contains {SOURCE_ROOT}; refusing to overwrite")
    helper_present = _git(repo, "cat-file", "-e", f"{before['head_tree']}:{HELPER_PATH}")
    if helper_present["returncode"] == 0:
        parent_helper = _git_text(repo, "rev-parse", f"{before['head_tree']}:{HELPER_PATH}")
        source_helper = _git_text(repo, "hash-object", str(helper_source))
        if parent_helper != source_helper:
            raise PilotError(
                f"parent HEAD already contains a different {HELPER_PATH}; refusing to overwrite"
            )

    import_rows = []
    verified = []
    for source in sources:
        repo_id = source["repo_id"]
        path = Path(source["source_path"]).resolve()
        commit = source["commit"]
        tree = source["tree"]
        clone_head = _git_text(path, "rev-parse", "HEAD")
        clone_tree = _git_text(path, "rev-parse", "HEAD^{tree}")
        clone_status = _git_text(path, "status", "--porcelain")
        if clone_head != commit or clone_tree != tree or clone_status:
            raise PilotError(f"source clone {repo_id} is not at its clean pinned commit")
        fetch = _git(
            repo,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "--no-auto-gc",
            "--no-recurse-submodules",
            str(path),
            commit,
            timeout=180,
        )
        import_rows.append(
            {
                "repo_id": repo_id,
                "source_path": str(path),
                "fetch": fetch,
                "source_commit": commit,
                "source_tree": tree,
            }
        )
        imported_tree = _git(repo, "rev-parse", f"{commit}^{{tree}}")
        imported_commit = _git(repo, "cat-file", "-e", commit)
        if (
            fetch["returncode"] != 0
            or imported_tree["returncode"] != 0
            or imported_tree["stdout"].strip() != tree
            or imported_commit["returncode"] != 0
        ):
            raise PilotError(f"source object import failed for {repo_id}")
        verified.append(
            {
                "repo_id": repo_id,
                "source_prefix": f"{SOURCE_ROOT}/{repo_id}",
                "upstream_commit": commit,
                "upstream_tree": tree,
                "imported_tree": imported_tree["stdout"].strip(),
            }
        )

    scratch = scratch_path(root, "anchor")
    index_file = scratch / "anchor.index"
    env = {"GIT_INDEX_FILE": str(index_file)}
    read_base = _git(repo, "read-tree", before["head_tree"], env=env)
    _must(read_base, "read-tree parent HEAD")
    build_rows = [read_base]
    for row in verified:
        result = _git(
            repo,
            "read-tree",
            f"--prefix={row['source_prefix']}/",
            row["upstream_tree"],
            env=env,
        )
        _must(result, f"read-tree {row['repo_id']}")
        build_rows.append(result)
    blob = _git(repo, "hash-object", "-w", str(helper_source))
    helper_blob = _must(blob, "hash-object helper")
    add_helper = _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{helper_blob},{HELPER_PATH}",
        env=env,
    )
    _must(add_helper, "update-index helper")
    build_rows.extend([blob, add_helper])
    anchor_tree = _git_text(repo, "write-tree", timeout=60, env=env)

    subtree_rows = []
    for row in verified:
        actual = _git_text(repo, "rev-parse", f"{anchor_tree}:{row['source_prefix']}")
        if actual != row["upstream_tree"]:
            raise PilotError(f"anchor subtree for {row['repo_id']} does not equal its upstream tree")
        inventory = _tree_entries(repo, actual)
        subtree_rows.append(
            {
                **row,
                "anchor_subtree_tree": actual,
                "subtree_matches": True,
                "file_count": len(inventory),
                "inventory_sha256": inventory_digest(inventory),
            }
        )
    anchor_helper = _git_text(repo, "rev-parse", f"{anchor_tree}:{HELPER_PATH}")
    if anchor_helper != helper_blob:
        raise PilotError("anchor helper blob differs from the producer source")

    scope = _git(repo, "diff", "--name-status", "--no-renames", "-z", before["head_tree"], anchor_tree)
    _must(scope, "anchor scope diff")
    changed = _diff_entries(scope["stdout"])
    allowed_prefixes = tuple(row["source_prefix"] + "/" for row in verified)
    unexpected = [
        row["path"]
        for row in changed
        if row["path"] != HELPER_PATH
        and not any(row["path"].startswith(prefix) for prefix in allowed_prefixes)
    ]
    deletions = [row["path"] for row in changed if row["status"][0] == "D"]
    if unexpected or deletions:
        raise PilotError(
            f"anchor changed parent paths: unexpected={unexpected[:10]} deletions={deletions[:10]}"
        )

    commit_result = _git(
        repo,
        "commit-tree",
        anchor_tree,
        "-p",
        before["head"],
        "-m",
        "Controlled single-project source anchor",
        env=_commit_env(),
        timeout=60,
    )
    anchor_commit = _must(commit_result, "commit-tree anchor")
    update = _git(
        repo,
        "update-ref",
        ref,
        anchor_commit,
        "0" * 40,
        env={"GIT_CONFIG_COUNT": "0"},
    )
    _must(update, "update-ref anchor")
    after = worktree_state(repo)
    after_state = {
        "branch": after["branch"],
        "head": after["head"],
        "tree": after["head_tree"],
        "index_tree": after["index_tree"],
        "status_sha256": sha256(after["status"].encode()),
        "untracked": after["untracked"],
        "ignored": after["ignored"],
    }
    if after_state != original:
        raise PilotError("anchor build changed the original branch, HEAD, index, or status")

    provenance = {
        "protocol_version": PROTOCOL_VERSION,
        "evidence_namespace": namespace,
        "built_at": now(),
        "parent_repo": str(repo),
        "anchor": {
            "ref": ref,
            "commit": anchor_commit,
            "tree": anchor_tree,
            "parent_commit": before["head"],
            "parent_tree": before["head_tree"],
            "private_local_only": True,
        },
        "producer": {
            "path": HELPER_PATH,
            "source_path": str(helper_source),
            "sha256": sha256(helper_source.read_bytes()),
            "blob": helper_blob,
        },
        "original_state_before": original,
        "original_state_after": after_state,
        "original_state_preserved": True,
        "sources": subtree_rows,
        "imports": import_rows,
        "commands": {
            "read_base": read_base,
            "build": build_rows,
            "scope": scope,
            "commit_tree": commit_result,
            "update_ref": update,
            "verify_ref": _git(repo, "rev-parse", ref),
        },
        "scope_changes": changed,
        "notes": [
            "The anchor commit is a CollisionGuard snapshot, not an upstream commit.",
            "Source objects live only in the local object database and private local ref.",
            "No push, worktree add, branch switch, or child checkout was performed.",
        ],
    }
    dump_json(root / "anchor" / "provenance.json", provenance)
    event(
        root,
        "anchor_built",
        ref=ref,
        commit=anchor_commit,
        tree=anchor_tree,
        parent=before["head"],
    )
    return provenance


def git_ref(ref: str) -> bool:
    return ref.startswith("refs/research/") and bool(re.fullmatch(r"[A-Za-z0-9._/-]+", ref))


def prompt_text(task: dict[str, Any], repo: dict[str, Any], run: dict[str, Any], evidence: Path) -> str:
    """Frozen worker prompt. It names only this task's source directory."""
    prefix = task["source_prefix"]
    import_path = task["import_path"]
    python_path = f"$PWD/{import_path}" if import_path != "." else "$PWD"
    return f"""You are a coding worker for a private research exercise, not an upstream contribution. Work inside this repository only in the assigned source directory below. Every other path is read-only harness material. Do not inspect other source directories, sibling prompts or outputs, private CollisionGuard materials, or unrelated directories. Do not delegate, commit, push, open a pull request, contact the project, change git remotes, or change global settings.

Assigned source directory: {prefix}
Upstream source identity: {repo['canonical_name']} commit {repo['upstream_commit']}, tree {repo['upstream_tree']}.
The parent commit is a CollisionGuard snapshot, not an upstream commit. Your changes are judged relative to {prefix}, whose tree must equal the pinned upstream tree before you edit.

Your first tool action must run exactly this command from the repository root before any other command or edit:
python3 {HELPER_PATH} capture --task-id {task['task_id']} --worktree "$PWD" --source-prefix {prefix} --expected-source-tree {task['upstream_tree']} --upstream-commit {task['upstream_commit']} --evidence-root {evidence} --run-id {run['run_id']} --namespace real
If it exits nonzero, stop without editing and report the exact output. Do not retry with different arguments.

Read contribution guidance only inside {prefix}. Make only the requested behavior and the tests and docs needed for it. Work only inside {prefix}. Do not modify any file outside it, including the parent repository's scripts/, docs/, and tests/ directories and the other controlled_sources entries. Inside {prefix}, docs and tests are part of your assigned source and may be edited when the task needs them. Do not clean, stage, commit, or remove generated files. Leave scratch and generated files in place; the coordinator captures them and flags them.

Create a task-specific virtual environment outside this repository at /tmp/controlled-single-project-venvs/{task['task_id']}. Run dependency preparation through the bounded recorder from the repository root:
python3 {HELPER_PATH} run --task-id {task['task_id']} --evidence-root {evidence} --run-id {run['run_id']} --namespace real --cwd <command-directory> --timeout-seconds 300 --purpose dependency-preparation -- <command>
Install only what is needed into that virtual environment. Never install globally and never use sudo.

Before testing, prove which source is imported. From inside {prefix}, run:
PYTHONPATH="{python_path}" python -c "import {task['import_name']}; print({task['import_name']}.__file__)"
Record that output through the bounded recorder with --timeout-seconds 30 --purpose dependency-preparation. The printed path must be inside {prefix}. Then run exactly one focused test command, from inside {prefix}, through the recorder with --timeout-seconds 180 --purpose targeted-test:
PYTHONPATH="{python_path}" {task['focused_test_command']}
Do not run tests from the repository root; root-level test caches would count as out-of-scope changes. If setup or tests fail, preserve the result and report it. Do not spend the task budget on unrelated checks. Keep your total task time within eight minutes. Do not call collect, replay, or summarize; the coordinator collects after your run.

Task-specific acceptance criteria follow:

{task['acceptance']}

Focused test target: {task['focused_test_target']}
"""


def _digest_id(prefix: str, run_id: str, old_id: str) -> str:
    return prefix + sha256(f"{run_id}|{old_id}".encode())[:16]


def prepare_plan(
    spec_file: Path,
    parent_repo: Path,
    root: Path,
    namespace: str,
    anchor_ref: str,
    anchor_commit: str,
) -> dict[str, Any]:
    """Freeze prompts, model selection, pins, and anchor ids before any launch."""
    root = evidence_root(root, namespace, create=True)
    repo = parent_repo.resolve()
    spec_bytes = spec_file.read_bytes()
    spec = json.loads(spec_bytes)
    if (
        len(spec.get("repositories", [])) != 5
        or len(spec.get("pairs", [])) != 5
        or len(spec.get("tasks", [])) != 10
    ):
        raise PilotError("the specification must contain five repositories, five pairs, and ten tasks")
    run_id = spec["run_id"]
    if not re.fullmatch(r"csp-run-[0-9]{8}-[0-9a-f]{6}", run_id):
        raise PilotError(f"invalid run id: {run_id!r}")
    if spec.get("coding_selection") != CODING_MODEL:
        raise PilotError("the specification does not use the DeepSeek V4.1 Flash selection")
    policy = spec.get("capture_policy", DEFAULT_CAPTURE_POLICY)
    if policy not in CAPTURE_POLICIES:
        raise PilotError(f"unknown capture policy: {policy!r}")
    anchor = _git(repo, "rev-parse", f"{anchor_ref}^{{commit}}")
    _must(anchor, "resolve anchor ref")
    if anchor["stdout"].strip() != anchor_commit:
        raise PilotError("anchor ref does not resolve to the prepared commit")
    anchor_tree = _git_text(repo, "rev-parse", f"{anchor_commit}^{{tree}}")
    parents = _git_text(repo, "rev-list", "--parents", "-n", "1", anchor_commit).split()
    if len(parents) != 2 or parents[1] != spec["parent_commit"]:
        raise PilotError("anchor commit does not have the frozen parent commit")
    helper_blob = _git_text(repo, "rev-parse", f"{anchor_tree}:{HELPER_PATH}")
    producer_sha = sha256((repo / HELPER_PATH).read_bytes())
    producer_git_blob = _git_text(repo, "hash-object", str(repo / HELPER_PATH))
    if helper_blob != producer_git_blob:
        raise PilotError("anchor helper blob differs from the current producer source")

    resources: list[dict[str, Any]] = []
    repo_rows = []
    for source in spec["repositories"]:
        actual = _git_text(repo, "rev-parse", f"{anchor_tree}:{SOURCE_ROOT}/{source['repo_id']}")
        if actual != source["upstream_tree"]:
            raise PilotError(f"anchor subtree differs from the pin for {source['repo_id']}")
        repo_rows.append(
            {
                **source,
                "source_prefix": f"{SOURCE_ROOT}/{source['repo_id']}",
                "subtree_matches": True,
                "license_notice": source["license_notice"],
            }
        )
        resources.append({"repo_id": source["repo_id"], "subtree": actual})

    tasks = []
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    staging = root / "prompts.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    run = {"run_id": run_id, "namespace": namespace, "anchor": {"ref": anchor_ref, "commit": anchor_commit, "tree": anchor_tree}}
    repo_by_id = {row["repo_id"]: row for row in repo_rows}
    for task_spec in spec["tasks"]:
        repo_row = repo_by_id[task_spec["repo_id"]]
        task_id = _digest_id("csp-task-", run_id, task_spec["old_task_id"])
        pair_id = _digest_id("csp-pair-", run_id, task_spec["old_pair_id"])
        task = {
            "task_id": task_id,
            "pair_id": pair_id,
            "repo_id": task_spec["repo_id"],
            "arm": task_spec["arm"],
            "source_prefix": repo_row["source_prefix"],
            "upstream_commit": repo_row["upstream_commit"],
            "upstream_tree": repo_row["upstream_tree"],
            "acceptance": task_spec["acceptance"],
            "focused_test_target": task_spec["focused_test_target"],
            "focused_test_command": task_spec["focused_test_command"],
            "import_name": task_spec["import_name"],
            "import_path": task_spec["import_path"],
            "prompt_file": f"prompts/{task_id}.txt",
        }
        text = prompt_text(task, repo_row, run, root)
        digest = sha256(text.encode())
        (staging / f"{task_id}.txt").write_text(text, encoding="utf-8")
        task["prompt_sha256"] = digest
        tasks.append(task)
    for task in tasks:
        final = root / task["prompt_file"]
        if final.exists() and sha256(final.read_bytes()) != task["prompt_sha256"]:
            raise PilotError(f"an existing prompt differs: {final}")
    for staged in sorted(staging.glob("*.txt")):
        os.replace(staged, prompts_dir / staged.name)
    staging.rmdir()

    pairs = []
    for pair_spec in spec["pairs"]:
        members = [task for task in tasks if task["pair_id"] == _digest_id("csp-pair-", run_id, pair_spec["old_pair_id"])]
        pairs.append(
            {
                "pair_id": members[0]["pair_id"],
                "repo_id": pair_spec["repo_id"],
                "task_ids": sorted(task["task_id"] for task in members),
                "authored_before_any_coding_output": True,
            }
        )
    plan = {
        "protocol_version": PROTOCOL_VERSION,
        "run_id": run_id,
        "frozen_at": now(),
        "spec_sha256": sha256(spec_bytes),
        "capture_policy": policy,
        "producer_sha256": producer_sha,
        "producer_git_blob": producer_git_blob,
        "producer_path": HELPER_PATH,
        "coding_selection": CODING_MODEL,
        "coordinator": "root coding-worker launches and review",
        "anchor": {
            "ref": anchor_ref,
            "commit": anchor_commit,
            "tree": anchor_tree,
            "parent_commit": spec["parent_commit"],
            "private_local_only": True,
            "helper_path": HELPER_PATH,
            "helper_blob": helper_blob,
        },
        "repositories": repo_rows,
        "pairs": pairs,
        "tasks": tasks,
        "budgets": {
            "task_budget_seconds": TASK_BUDGET_SECONDS,
            "targeted_test_limit_seconds": TEST_LIMIT_SECONDS,
            "dependency_preparation_limit_seconds": DEPENDENCY_LIMIT_SECONDS,
            "workers_at_a_time": 1,
        },
        "evidence_root": str(root),
        "instructions": spec["instructions"],
    }
    plan["plan_sha256"] = sha256(
        canonical_json({k: v for k, v in plan.items() if k != "plan_sha256"})
    )
    run.update(
        {
            "protocol_version": PROTOCOL_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "spec_sha256": plan["spec_sha256"],
            "namespace": namespace,
            "capture_policy": policy,
            "anchor": plan["anchor"],
            "coding_selection": CODING_MODEL,
            "frozen_at": plan["frozen_at"],
        }
    )
    plan_file = root / "plan.json"
    if plan_file.exists() and load_json(plan_file).get("plan_sha256") != plan["plan_sha256"]:
        raise PilotError("a different frozen plan already exists")
    dump_json(plan_file, plan)
    dump_json(_run_record_path(root), run)
    validate_plan(plan, root)
    event(root, "plan_frozen", plan_sha256=plan["plan_sha256"], anchor=anchor_commit)
    return plan


def status_report(root: Path) -> dict[str, Any]:
    root = root.resolve()
    plan = load_plan(root)
    rows = pair_rows(plan, root)
    return {
        "run_id": plan["run_id"],
        "plan_sha256": plan["plan_sha256"],
        "anchor": plan["anchor"],
        "pairs": rows,
        "feasibility_gate": feasibility(plan, rows),
    }


def jobs_dir(root: Path, task_id: str) -> Path:
    return output_path(root, task_id) / "jobs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_anchor = sub.add_parser("build-anchor", help="build the local private parent snapshot")
    p_anchor.add_argument("--repo", type=Path, required=True)
    p_anchor.add_argument("--pins", type=Path, required=True)
    p_anchor.add_argument("--ref", required=True)
    p_anchor.add_argument("--evidence-root", type=Path, required=True)
    p_anchor.add_argument("--namespace", choices=("real", "fixture"), required=True)

    p_prepare = sub.add_parser("prepare-plan", help="freeze prompts, plan, and run ids")
    p_prepare.add_argument("--spec", type=Path, required=True)
    p_prepare.add_argument("--repo", type=Path, required=True)
    p_prepare.add_argument("--evidence-root", type=Path, required=True)
    p_prepare.add_argument("--namespace", choices=("real", "fixture"), required=True)
    p_prepare.add_argument("--anchor-ref", required=True)
    p_prepare.add_argument("--anchor-commit", required=True)

    p_capture = sub.add_parser("capture", help="record the parent snapshot before edits")
    p_capture.add_argument("--task-id", required=True)
    p_capture.add_argument("--worktree", type=Path, default=Path.cwd())
    p_capture.add_argument("--source-prefix", required=True)
    p_capture.add_argument("--expected-source-tree", required=True)
    p_capture.add_argument("--upstream-commit", required=True)
    p_capture.add_argument("--evidence-root", type=Path, required=True)
    p_capture.add_argument("--run-id", required=True)
    p_capture.add_argument("--namespace", choices=("real", "fixture"), required=True)
    p_capture.add_argument("--phase", default="first_child_action_before_edits")

    p_collect = sub.add_parser("collect", help="capture and replay the final source tree")
    p_collect.add_argument("--task-id", required=True)
    p_collect.add_argument("--worktree", type=Path, default=Path.cwd())
    p_collect.add_argument("--evidence-root", type=Path, required=True)
    p_collect.add_argument("--namespace", choices=("real", "fixture"), required=True)

    p_run = sub.add_parser("run", help="run one bounded command and preserve its transcript")
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--evidence-root", type=Path, required=True)
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--namespace", choices=("real", "fixture"), required=True)
    p_run.add_argument("--cwd", type=Path, required=True)
    p_run.add_argument("--timeout-seconds", type=int, default=TEST_LIMIT_SECONDS)
    p_run.add_argument("--purpose", choices=("targeted-test", "dependency-preparation", "import-check"), default="targeted-test")
    p_run.add_argument("command_args", nargs=argparse.REMAINDER)

    p_record = sub.add_parser("record-run", help="record returned live task metadata")
    p_record.add_argument("--task-id", required=True)
    p_record.add_argument("--live-json", type=Path, required=True)
    p_record.add_argument("--evidence-root", type=Path, required=True)
    p_record.add_argument("--namespace", choices=("real", "fixture"), required=True)

    p_replay = sub.add_parser("replay", help="replay both outputs and label the pair")
    p_replay.add_argument("--pair-id", required=True)
    p_replay.add_argument("--evidence-root", type=Path, required=True)

    p_status = sub.add_parser("status", help="report all five pairs from frozen identifiers")
    p_status.add_argument("--evidence-root", type=Path, required=True)

    p_summary = sub.add_parser("summarize", help="write and print the public-safe summary")
    p_summary.add_argument("--evidence-root", type=Path, required=True)
    p_summary.add_argument("--write", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "build-anchor":
            result = build_anchor(args.repo, args.pins, args.ref, args.evidence_root, args.namespace)
            print(json.dumps(result, sort_keys=True))
        elif args.command == "prepare-plan":
            result = prepare_plan(
                args.spec, args.repo, args.evidence_root, args.namespace, args.anchor_ref, args.anchor_commit
            )
            print(json.dumps({"plan_sha256": result["plan_sha256"], "run_id": result["run_id"],
                              "task_ids": [task["task_id"] for task in result["tasks"]],
                              "prompt_sha256": {task["task_id"]: task["prompt_sha256"] for task in result["tasks"]}},
                             sort_keys=True))
        elif args.command == "capture":
            root = evidence_root(args.evidence_root, args.namespace, create=True)
            run = load_run_record(root)
            if run.get("run_id") != args.run_id:
                raise PilotError("run id does not match the frozen run record")
            record = capture(
                args.task_id,
                args.worktree,
                args.source_prefix,
                args.expected_source_tree,
                args.upstream_commit,
                root,
                args.namespace,
                args.phase,
            )
            print(json.dumps({"task_id": args.task_id, "ok": record["verdict"]["ok"],
                              "problems": record["verdict"]["problems"],
                              "parent_head": record["parent_snapshot"]["head"],
                              "source_tree": record["original_source"]["actual_subtree_tree"],
                              "captured_at": record["captured_at"]}, sort_keys=True))
            if not record["verdict"]["ok"]:
                return 2
        elif args.command == "collect":
            record = collect(args.task_id, args.worktree, args.evidence_root, args.namespace)
            print(json.dumps({"task_id": args.task_id, "ok": record["verdict"]["ok"],
                              "problems": record["verdict"]["problems"],
                              "patch_sha256": record["patch_sha256"],
                              "nonempty": record["nonempty"],
                              "replay_ok": record["replay_ok"],
                              "changed_paths": record["changed_paths"]}, sort_keys=True))
            if not record["verdict"]["ok"]:
                return 2
        elif args.command == "run":
            if args.purpose == "targeted-test" and args.timeout_seconds > TEST_LIMIT_SECONDS:
                raise PilotError(f"targeted tests cannot exceed {TEST_LIMIT_SECONDS}s")
            if args.purpose == "dependency-preparation" and args.timeout_seconds > DEPENDENCY_LIMIT_SECONDS:
                raise PilotError(f"dependency preparation cannot exceed {DEPENDENCY_LIMIT_SECONDS}s")
            command_args = args.command_args[1:] if args.command_args[:1] == ["--"] else args.command_args
            if not command_args:
                raise PilotError("run needs a command after --")
            root = evidence_root(args.evidence_root, args.namespace, create=True)
            run_record = load_run_record(root)
            if run_record.get("run_id") != args.run_id:
                raise PilotError("run id does not match the frozen run record")
            result = _run(command_args, cwd=args.cwd.resolve(), timeout=args.timeout_seconds)
            log = jobs_dir(root, args.task_id) / f"{now().replace(':', '').replace('-', '')}.json"
            dump_json(
                log,
                {
                    "owner": args.task_id,
                    "purpose": args.purpose,
                    "checkpoint": None,
                    "deadline_seconds": args.timeout_seconds,
                    "evidence_namespace": args.namespace,
                    **result,
                },
            )
            event(root, "bounded_job", task_id=args.task_id, path=str(log),
                  returncode=result["returncode"], timed_out=result["timed_out"], pid=result["pid"])
            print(json.dumps({"log": str(log), **result}, sort_keys=True))
            return result["returncode"] if not result["timed_out"] else 124
        elif args.command == "record-run":
            result = record_run(args.task_id, load_json(args.live_json), args.evidence_root, args.namespace)
            print(json.dumps({"task_id": args.task_id, "coding_started": result["coding_started"],
                              "selection_ok": result["selection_ok"], "within_limits": result["within_limits"],
                              "provenance_ok": result["provenance_ok"]}, sort_keys=True))
        elif args.command == "replay":
            result = replay_pair(args.pair_id, args.evidence_root)
            print(json.dumps(result, sort_keys=True))
        elif args.command == "status":
            print(json.dumps(status_report(args.evidence_root), sort_keys=True))
        elif args.command == "summarize":
            print(json.dumps(summarize(args.evidence_root, args.write), sort_keys=True))
    except (PilotError, OSError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        print(f"controlled single project: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
