"""Replay a sample of natural-cohort labels with the source procedure.

The replication package labels each pair with `git merge-tree --write-tree`
over the two PR heads. This script repeats that procedure on a fixed sample of
pilot pairs and reports agreement. It is a reproducibility check, not a new
label source.

    python3 scripts/verify_natural_labels.py --sample 20
    python3 scripts/verify_natural_labels.py --check

Disagreements are written to the output with enough detail to investigate.
Temporary repositories live under /tmp and are removed after each pair.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
TABLE = PRIVATE / "table.json"
SELECTION = PRIVATE / "pilot-selection.json"
OUT = PRIVATE / "label-verification.jsonl"
WORK = Path("/tmp/opencode/natural-label-verify")
CONFLICT_RE = re.compile(r"Merge conflict in (.+)$", re.MULTILINE)


def _run(args, cwd, timeout=300, check=False):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, check=check)


def _fetch(work, repo, number, depth):
    return _run([
        "git", "-C", str(work), "fetch", "--no-tags", "--depth", str(depth),
        f"https://github.com/{repo}.git",
        f"refs/pull/{number}/head:refs/pr/{number}",
    ], WORK, timeout=600)


def _merge_base(work, first, second):
    result = _run(["git", "-C", str(work), "merge-base",
                   f"refs/pr/{first}", f"refs/pr/{second}"], WORK, timeout=120)
    return result.stdout.strip() if result.returncode == 0 else None


def _label(work, first, second):
    result = _run(["git", "-C", str(work), "merge-tree", "--write-tree",
                   f"refs/pr/{first}", f"refs/pr/{second}"], WORK, timeout=300)
    if result.returncode == 0:
        return "CLEAN", [], result.returncode
    if result.returncode == 1:
        paths = sorted(set(CONFLICT_RE.findall(result.stdout + "\n" + result.stderr)))
        return "CONFLICT", paths, result.returncode
    return None, [], result.returncode


def _already_done(path):
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["instance_id"]] = row
    return rows


def _append(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _select(table, sample):
    if not SELECTION.is_file():
        raise SystemExit(f"missing pilot selection: {SELECTION}")
    selected = set(json.loads(SELECTION.read_text(encoding="utf-8"))["instance_ids"])
    eligible = [pair for pair in table["pairs"]
                if pair["instance_id"] in selected
                and pair["title_a"].strip().casefold() != pair["title_b"].strip().casefold()]
    eligible.sort(key=lambda pair: pair["instance_id"])
    chosen = []
    per_label = sample // 2
    for label in ("clean", "conflict"):
        chosen.extend([pair for pair in eligible if pair["label"] == label][:per_label])
    return chosen


def verify_pair(pair):
    WORK.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pair-", dir=WORK))
    try:
        _run(["git", "init", "--bare", "-q", str(work)], WORK, check=True)
        for number in (pair["pr_a"], pair["pr_b"]):
            result = _fetch(work, pair["repo"], number, 80)
            if result.returncode != 0:
                return {"instance_id": pair["instance_id"], "repo": pair["repo"],
                        "source_label": pair["label"], "status": "fetch-failed",
                        "detail": result.stderr.strip()[:500]}
        base = _merge_base(work, pair["pr_a"], pair["pr_b"])
        if not base:
            for number in (pair["pr_a"], pair["pr_b"]):
                _fetch(work, pair["repo"], number, 600)
            base = _merge_base(work, pair["pr_a"], pair["pr_b"])
        if not base:
            return {"instance_id": pair["instance_id"], "repo": pair["repo"],
                    "source_label": pair["label"], "status": "no-base"}
        label, paths, code = _label(work, pair["pr_a"], pair["pr_b"])
        return {
            "instance_id": pair["instance_id"],
            "repo": pair["repo"],
            "pr_a": pair["pr_a"],
            "pr_b": pair["pr_b"],
            "source_label": pair["label"],
            "replayed_label": label.lower() if label else None,
            "agree": label is not None and label.lower() == pair["label"],
            "conflict_paths": paths,
            "returncode": code,
            "merge_base": base,
            "status": "ok" if label else "merge-tree-error",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    done = _already_done(args.out)
    if args.check:
        rows = list(done.values())
        ok = [row for row in rows if row.get("status") == "ok"]
        agree = sum(1 for row in ok if row.get("agree"))
        print(f"{len(rows)} rows; {len(ok)} replayed; {agree}/{len(ok)} agree")
        for row in rows:
            if row.get("status") != "ok" or not row.get("agree"):
                print("  mismatch:", row)
        return

    version = subprocess.run(["git", "--version"], capture_output=True, text=True)
    print(version.stdout.strip())
    if not SELECTION.is_file():
        raise SystemExit(f"missing pilot selection: {SELECTION}")
    table = json.loads(args.table.read_text(encoding="utf-8"))
    planned = _select(table, args.sample)
    pending = [pair for pair in planned if pair["instance_id"] not in done]
    print(f"planned {len(planned)}; {len(done)} done; {len(pending)} pending")
    for number, pair in enumerate(pending, 1):
        row = verify_pair(pair)
        _append(args.out, row)
        print(f"[{number}/{len(pending)}] {pair['repo']} {pair['pr_a']}/{pair['pr_b']} "
              f"source={pair['label']} replayed={row.get('replayed_label')} "
              f"{row['status']}", flush=True)
    rows = list(_already_done(args.out).values())
    ok = [row for row in rows if row.get("status") == "ok"]
    agree = sum(1 for row in ok if row.get("agree"))
    print(f"done: {agree}/{len(ok)} replayed labels agree; {args.out}")


if __name__ == "__main__":
    main()
