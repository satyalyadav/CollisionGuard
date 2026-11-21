"""Fetch repository trees and changed-file lists for the natural-mix cohort.

The replication package gives pair-level merge labels. This script adds the
inputs a pre-start predictor may use:

- the repository tree at the pair's common base commit
- each PR's changed paths (for footprint recall and overlap checks)

Output is resumable JSONL under the ignored private root. A pair is appended
only after every request succeeds. Rerunning skips completed pairs.

    python3 scripts/fetch_natural_repo_data.py --sample 80
    python3 scripts/fetch_natural_repo_data.py --all

Only GitHub's public REST API is used. The token comes from `gh auth token`
or GITHUB_TOKEN. Rate-limit responses stop the run cleanly; rerun later.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
TABLE = PRIVATE / "table.json"
OUT = PRIVATE / "repo-data.jsonl"
SELECTION = PRIVATE / "pilot-selection.json"
API = "https://api.github.com"
SEED = 20261121
USER_AGENT = "CollisionGuard-natural-cohort/0.1"


def _token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    try:
        result = subprocess.run(["gh", "auth", "token"], check=True,
                                capture_output=True, text=True, timeout=20)
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        raise SystemExit("no GitHub token: set GITHUB_TOKEN or run gh auth login") from exc


class GitHub:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        })
        self.calls = 0

    def get(self, path, params=None, *, allow_404=False, allow_422=False, attempts=4):
        url = path if path.startswith("https://") else API + path
        for attempt in range(attempts):
            response = self.session.get(url, params=params, timeout=60)
            self.calls += 1
            if response.status_code == 404 and allow_404:
                return None
            if response.status_code == 422 and allow_422:
                return None
            if response.status_code in (403, 429):
                remaining = response.headers.get("X-RateLimit-Remaining")
                retry_after = response.headers.get("Retry-After")
                if remaining == "0" or response.status_code == 429:
                    raise RateLimited(response.headers.get("X-RateLimit-Reset"))
                if attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
                    continue
            if 500 <= response.status_code < 600 and attempt + 1 < attempts:
                time.sleep(2 ** attempt)
                continue
            if response.status_code != 200:
                raise RuntimeError(f"GET {response.url} -> {response.status_code}: "
                                   f"{response.text[:300]}")
            return response.json()
        raise RuntimeError(f"GET {url} failed after {attempts} attempts")


class RateLimited(RuntimeError):
    def __init__(self, reset):
        self.reset = int(reset) if reset and reset.isdigit() else None
        super().__init__("GitHub rate limit reached")


def _language_group(language):
    if not language:
        return "other"
    value = language.casefold()
    if value == "python":
        return "python"
    if value in ("typescript", "javascript"):
        return "js_ts"
    return "other"


def _select(table, sample, all_pairs=False):
    pairs = [pair for pair in table["pairs"]
             if pair["title_a"].strip().casefold() != pair["title_b"].strip().casefold()]
    if all_pairs:
        return sorted(pairs, key=lambda p: p["instance_id"])
    by_repo = {}
    for pair in pairs:
        by_repo.setdefault(pair["repo"].casefold(), []).append(pair)
    unique = [min(group, key=lambda p: (p["pr_a"], p["pr_b"]))
              for group in by_repo.values()]
    rng = random.Random(SEED)
    buckets = {}
    for pair in unique:
        key = (pair["label"], _language_group(pair.get("language")))
        buckets.setdefault(key, []).append(pair)
    for key in buckets:
        buckets[key].sort(key=lambda p: p["instance_id"])
        rng.shuffle(buckets[key])
    if sample >= len(unique):
        chosen = list(unique)
    else:
        quota = max(1, sample // 2)
        chosen, seen = [], set()
        for label in ("clean", "conflict"):
            language = {key[1]: list(value) for key, value in buckets.items()
                        if key[0] == label}
            taken = 0
            while taken < quota and any(language.values()):
                for language_name in sorted(language):
                    if taken >= quota:
                        break
                    if language[language_name]:
                        pair = language[language_name].pop()
                        chosen.append(pair)
                        seen.add(pair["instance_id"])
                        taken += 1
        if len(chosen) < sample:
            rest = [pair for pair in unique
                    if pair["instance_id"] not in seen]
            rest.sort(key=lambda p: p["instance_id"])
            chosen.extend(rest[:sample - len(chosen)])
        chosen = chosen[:sample]
    chosen.sort(key=lambda p: p["instance_id"])
    return chosen


def _already_done(path):
    done = {}
    if not path.is_file():
        return done
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            done[row["instance_id"]] = row
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid checkpoint line") from exc
    return done


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _pull(api, repo, number):
    return api.get(f"/repos/{repo}/pulls/{number}", allow_404=True)


def _files(api, repo, number, cap=300):
    rows, page = [], 1
    while len(rows) < cap:
        batch = api.get(f"/repos/{repo}/pulls/{number}/files",
                        params={"per_page": 100, "page": page}, allow_404=True)
        if not isinstance(batch, list):
            return None, False
        rows.extend(batch)
        if len(batch) < 100:
            return rows[:cap], False
        page += 1
    return rows[:cap], True


def _tree(api, repo, sha):
    data = api.get(f"/repos/{repo}/git/trees/{sha}",
                   params={"recursive": "1"}, allow_404=True)
    if data is None:
        return None, False
    paths = []
    for entry in data.get("tree", []):
        if entry["type"] == "blob":
            paths.append(entry["path"])
    return paths, bool(data.get("truncated"))


def _merge_base(api, repo, pull_a, pull_b):
    head_a = pull_a["head"]["sha"]
    head_b = pull_b["head"]["sha"]
    data = api.get(f"/repos/{repo}/compare/{head_a}...{head_b}",
                   allow_404=True, allow_422=True)
    if not data:
        return None, "compare-failed"
    merge_base = data.get("merge_base_commit") or {}
    sha = merge_base.get("sha")
    return sha, "compare-merge-base" if sha else "compare-no-base"


def _local_pair_data(repo, pr_a, pr_b):
    """Fetch both PR heads and derive the tree and changed paths locally."""
    import tempfile
    base_dir = Path("/tmp/opencode/natural-git")
    base_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pair-", dir=base_dir))
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        def run(args, timeout=600):
            return subprocess.run(args, cwd=work, capture_output=True,
                                  text=True, timeout=timeout, env=env)

        run(["git", "init", "--bare", "-q", str(work)], timeout=60)
        for number in (pr_a, pr_b):
            ok = False
            for depth in (80, 600):
                result = run(["git", "-C", str(work), "fetch", "--no-tags",
                              "--depth", str(depth),
                              f"https://github.com/{repo}.git",
                              f"refs/pull/{number}/head:refs/pr/{number}"])
                if result.returncode == 0:
                    ok = True
                    break
            if not ok:
                return None
        result = run(["git", "-C", str(work), "merge-base",
                      f"refs/pr/{pr_a}", f"refs/pr/{pr_b}"], timeout=120)
        if result.returncode != 0:
            for number in (pr_a, pr_b):
                run(["git", "-C", str(work), "fetch", "--no-tags", "--depth", "600",
                     f"https://github.com/{repo}.git",
                     f"refs/pull/{number}/head:refs/pr/{number}"])
            result = run(["git", "-C", str(work), "merge-base",
                          f"refs/pr/{pr_a}", f"refs/pr/{pr_b}"], timeout=120)
            if result.returncode != 0:
                return None
        base = result.stdout.strip()
        tree = run(["git", "-C", str(work), "ls-tree", "-r", "--name-only", base])
        if tree.returncode != 0:
            return None
        paths = [line for line in tree.stdout.splitlines() if line]
        changed = {}
        for side, number in (("a", pr_a), ("b", pr_b)):
            diff = run(["git", "-C", str(work), "diff", "--name-only", "-z",
                        base, f"refs/pr/{number}"])
            if diff.returncode != 0:
                return None
            changed[side] = [part for part in diff.stdout.split("\0") if part]
        return {"base_sha": base, "tree_paths": paths,
                "files_a": changed["a"], "files_b": changed["b"]}
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def fetch_pair(api, pair):
    repo = pair["repo"]
    pull_a = _pull(api, repo, pair["pr_a"])
    pull_b = _pull(api, repo, pair["pr_b"])
    if pull_a is None or pull_b is None:
        return {"instance_id": pair["instance_id"], "status": "unavailable",
                "missing": [side for side, value in (("a", pull_a), ("b", pull_b))
                            if value is None]}
    files_a, trunc_a = _files(api, repo, pair["pr_a"])
    files_b, trunc_b = _files(api, repo, pair["pr_b"])
    if files_a is None or files_b is None:
        return {"instance_id": pair["instance_id"], "status": "unavailable",
                "missing": [side for side, value in (("a", files_a), ("b", files_b))
                            if value is None]}
    base_sha, base_source = _merge_base(api, repo, pull_a, pull_b)
    local = None
    if not base_sha:
        local = _local_pair_data(repo, pair["pr_a"], pair["pr_b"])
        if not local:
            return {"instance_id": pair["instance_id"], "status": "no-base",
                    "base_source": base_source}
        base_sha = local["base_sha"]
        base_source = "local-git"
        tree_paths, tree_truncated = local["tree_paths"], False
        files_a = [{"path": path, "status": "changed", "additions": 0, "deletions": 0}
                   for path in local["files_a"]]
        files_b = [{"path": path, "status": "changed", "additions": 0, "deletions": 0}
                   for path in local["files_b"]]
        trunc_a = trunc_b = False
    else:
        tree_paths, tree_truncated = _tree(api, repo, base_sha)
        if tree_paths is None:
            return {"instance_id": pair["instance_id"], "status": "no-tree",
                    "base_sha": base_sha}
    return {
        "instance_id": pair["instance_id"],
        "status": "ok",
        "repo": repo,
        "pr_a": pair["pr_a"],
        "pr_b": pair["pr_b"],
        "label": pair["label"],
        "stratum": pair["stratum"],
        "base_sha": base_sha,
        "base_source": base_source,
        "head_a": pull_a["head"]["sha"],
        "head_b": pull_b["head"]["sha"],
        "files_a": [{"path": row.get("filename") or row.get("path"),
                     "status": row.get("status", "changed"),
                     "additions": row.get("additions", 0),
                     "deletions": row.get("deletions", 0)}
                    for row in files_a if (row.get("filename") or row.get("path"))],
        "files_b": [{"path": row.get("filename") or row.get("path"),
                     "status": row.get("status", "changed"),
                     "additions": row.get("additions", 0),
                     "deletions": row.get("deletions", 0)}
                    for row in files_b if (row.get("filename") or row.get("path"))],
        "files_truncated": bool(trunc_a or trunc_b),
        "tree_paths": tree_paths,
        "tree_truncated": tree_truncated,
        "conflict_paths": pair.get("conflict_paths", []),
        "conflict_types": pair.get("conflict_types", []),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "github-rest",
    }


def refresh_files_local(pair, row):
    local = _local_pair_data(pair["repo"], pair["pr_a"], pair["pr_b"])
    if not local:
        return {**row, "files_refresh": "failed"}
    return {**row, "base_sha": local["base_sha"], "base_source": "local-git",
            "tree_paths": local["tree_paths"], "tree_truncated": False,
            "files_a": [{"path": path, "status": "changed",
                         "additions": 0, "deletions": 0}
                        for path in local["files_a"]],
            "files_b": [{"path": path, "status": "changed",
                         "additions": 0, "deletions": 0}
                        for path in local["files_b"]],
            "files_truncated": False,
            "files_refresh": "local-git",
            "refreshed_at": datetime.now(timezone.utc).isoformat()}


def refresh_row(api, pair, row):
    """Recompute the true merge base and tree for one stored row."""
    repo = pair["repo"]
    pull_a = _pull(api, repo, pair["pr_a"])
    pull_b = _pull(api, repo, pair["pr_b"])
    if pull_a is None or pull_b is None:
        return {**row, "status": "refresh-unavailable"}
    base_sha, base_source = _merge_base(api, repo, pull_a, pull_b)
    if base_sha:
        tree_paths, tree_truncated = _tree(api, repo, base_sha)
        if tree_paths is not None:
            return {**row, "base_sha": base_sha, "base_source": base_source,
                    "tree_paths": tree_paths, "tree_truncated": tree_truncated,
                    "refreshed_at": datetime.now(timezone.utc).isoformat()}
    local = _local_pair_data(repo, pair["pr_a"], pair["pr_b"])
    if local:
        return {**row, "base_sha": local["base_sha"], "base_source": "local-git",
                "tree_paths": local["tree_paths"], "tree_truncated": False,
                "files_a": [{"path": path, "status": "changed",
                             "additions": 0, "deletions": 0}
                            for path in local["files_a"]],
                "files_b": [{"path": path, "status": "changed",
                             "additions": 0, "deletions": 0}
                            for path in local["files_b"]],
                "files_truncated": False,
                "refreshed_at": datetime.now(timezone.utc).isoformat()}
    return {**row, "status": "refresh-failed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=80,
                        help="balanced pilot size; ignored with --all")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--refresh-empty-files", action="store_true",
                        help="recompute changed paths locally when a side is empty")
    parser.add_argument("--retry-errors", action="store_true",
                        help="refetch pairs whose last checkpoint row is not ok")
    parser.add_argument("--refresh-bases", action="store_true",
                        help="recompute the base and tree for rows stored with "
                             "the old equal-base shortcut")
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--selection", type=Path, default=SELECTION)
    args = parser.parse_args(argv)

    table = json.loads(args.table.read_text(encoding="utf-8"))
    chosen = _select(table, 0, all_pairs=True) if args.all else _select(table, args.sample)
    args.selection.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed": SEED,
        "requested": "all" if args.all else args.sample,
        "eligible_pairs": len(table["pairs"]),
        "selected": len(chosen),
        "rule": ("one pair per repository, lowest PR numbers; PR titles must differ; "
                 "balanced by label and language group when sampling"),
        "instance_ids": [pair["instance_id"] for pair in chosen],
    }
    args.selection.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")

    done = _already_done(args.out)
    if args.retry_errors:
        done = {key: value for key, value in done.items()
                if value.get("status") == "ok"}
    api = GitHub()
    if args.refresh_empty_files:
        table_pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
        targets = [row for row in done.values()
                   if row.get("status") == "ok"
                   and (not row.get("files_a") or not row.get("files_b"))]
        print(f"refreshing {len(targets)} rows with an empty changed-file side",
              flush=True)
        for number, row in enumerate(targets, 1):
            pair = table_pairs.get(row["instance_id"])
            if pair is None:
                continue
            refreshed = refresh_files_local(pair, row)
            _append(args.out, refreshed)
            print(f"[{number}/{len(targets)}] {row['repo']} "
                  f"{len(refreshed.get('files_a', []))}/"
                  f"{len(refreshed.get('files_b', []))} "
                  f"{refreshed.get('files_refresh')}", flush=True)
        return

    if args.refresh_bases:
        table_pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
        targets = [row for row in done.values()
                   if row.get("status") == "ok"
                   and row.get("base_source") == "shared-base"]
        print(f"refreshing {len(targets)} rows stored with the equal-base shortcut",
              flush=True)
        for number, row in enumerate(targets, 1):
            pair = table_pairs.get(row["instance_id"])
            if pair is None:
                continue
            refreshed = refresh_row(api, pair, row)
            _append(args.out, refreshed)
            print(f"[{number}/{len(targets)}] {row['repo']} "
                  f"{row.get('base_sha', '')[:8]} -> "
                  f"{refreshed.get('base_sha', '')[:8]} "
                  f"{refreshed.get('base_source')} {refreshed.get('status')}",
                  flush=True)
        print(f"refresh done: {api.calls} API calls", flush=True)
        return

    pending = [pair for pair in chosen if pair["instance_id"] not in done]
    print(f"selected {len(chosen)} pairs; {len(done)} already checkpointed; "
          f"{len(pending)} pending", flush=True)
    started = time.time()
    for number, pair in enumerate(pending, 1):
        try:
            row = fetch_pair(api, pair)
        except RateLimited:
            print(f"rate limit reached after {api.calls} calls; rerun later")
            break
        except Exception as exc:  # keep one bad response from stopping the batch
            row = {"instance_id": pair["instance_id"], "status": "error",
                   "detail": f"{type(exc).__name__}: {exc}"}
        _append(args.out, row)
        status = row["status"]
        print(f"[{number}/{len(pending)}] {pair['repo']} {pair['pr_a']}/{pair['pr_b']} "
              f"{pair['label']} -> {status} ({api.calls} calls, "
              f"{time.time() - started:.0f}s)", flush=True)
        if number % 25 == 0:
            print(f"progress {number}/{len(pending)}", flush=True)
    print(f"done: {api.calls} API calls, {time.time() - started:.0f}s, {args.out}")


if __name__ == "__main__":
    main()
