"""Build the ten-pair prediction table from the two constructed cohorts.

The task text is coordinator-authored and the pilot protocols keep prompts out
of the public repository. The full table therefore stays under data/private/.
The public summary reports counts, labels, input hashes and a table hash, with
no task text and no local paths.

    python3 scripts/build_controlled_prediction.py
    python3 scripts/build_controlled_prediction.py --check
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3_PLAN = ROOT / "data/private/research/controlled-single-project-v3/plan.json"
V3_RESULTS = ROOT / "data/controlled-single-project/posthoc-git-visible.json"
FRESH_PLAN = ROOT / "data/private/research/controlled-single-project-fresh-2026-11-20-v2/plan.json"
FRESH_RESULTS = ROOT / "data/controlled-fresh-2026-11/summary.json"
PRIVATE_OUT = ROOT / "data/private/research/controlled-prediction-10/table.json"
PUBLIC_OUT = ROOT / "data/controlled-prediction-10/summary.json"

PROTOCOL_VERSION = "controlled-prediction-table-1"
EXPECTED_PAIRS = 10


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def table_body_digest(table):
    """Digest the table content, excluding the timestamp and the digest field."""
    body = {key: value for key, value in table.items()
            if key not in ("table_sha256", "built_at")}
    return _sha256_bytes(_canonical_json(body))


def verify_table(table):
    """Reject a table whose saved digest does not match its current content."""
    expected = table.get("table_sha256")
    actual = table_body_digest(table)
    if expected != actual:
        raise ValueError(f"table digest mismatch: saved {expected}, computed {actual}")


def _check_plan_digest(plan):
    """Reproduce the producer's canonical plan digest."""
    digest = plan.get("plan_sha256")
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual = _sha256_bytes(_canonical_json(canonical))
    if digest != actual:
        raise ValueError(f"plan digest mismatch: saved {digest}, computed {actual}")


def _load(path):
    if not path.is_file():
        raise ValueError(f"missing input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _index_by_task(plan, plan_path):
    """Return the frozen task statements keyed by task id.

    Each statement is checked against the prompt bytes it was copied from. The
    acceptance text must appear verbatim in the prompt, and the prompt hash must
    match the frozen plan. This keeps harness instructions out of the table.
    """
    tasks = {}
    for task in plan["tasks"]:
        task_id = task["task_id"]
        if task_id in tasks:
            raise ValueError(f"duplicate task id {task_id}")
        acceptance = task["acceptance"].strip()
        if not acceptance:
            raise ValueError(f"{task_id}: empty acceptance text")
        prompt_path = plan_path.parent / task["prompt_file"]
        if _sha256_file(prompt_path) != task["prompt_sha256"]:
            raise ValueError(f"{task_id}: prompt hash does not match the frozen plan")
        if acceptance not in prompt_path.read_text(encoding="utf-8"):
            raise ValueError(f"{task_id}: acceptance text is not in its prompt")
        tasks[task_id] = {
            "task_id": task_id,
            "text": acceptance,
            "text_sha256": _sha256_bytes(acceptance.encode("utf-8")),
            "prompt_sha256": task["prompt_sha256"],
            "repo_id": task["repo_id"],
            "pair_id": task["pair_id"],
        }
    return tasks


def _repositories(plan):
    return {repo["repo_id"]: repo["canonical_name"] for repo in plan["repositories"]}


def _check_pair(pair_id, repo_id, task_ids, repositories, tasks):
    if len(task_ids) != 2 or task_ids[0] == task_ids[1]:
        raise ValueError(f"{pair_id}: need two distinct tasks")
    for task_id in task_ids:
        if task_id not in tasks:
            raise ValueError(f"{pair_id}: unknown task {task_id}")
        if tasks[task_id]["repo_id"] != repo_id:
            raise ValueError(f"{pair_id}: task {task_id} belongs to another repository")
        if tasks[task_id]["pair_id"] != pair_id:
            raise ValueError(f"{pair_id}: task {task_id} belongs to another pair")
    if repo_id not in repositories:
        raise ValueError(f"{pair_id}: unknown repository {repo_id}")


def _v3_pairs(plan, results, plan_path):
    repositories = _repositories(plan)
    tasks = _index_by_task(plan, plan_path)
    pairs = []
    for pair in results["pairs"]:
        pair_id = pair["pair_id"]
        repo_id = pair["repo_id"]
        task_ids = pair["task_ids"]
        _check_pair(pair_id, repo_id, task_ids, repositories, tasks)
        posthoc = pair["posthoc_git_visible"]
        raw = pair["raw_full_directory_capture"]
        if not raw["starting_snapshots_equal"] or not raw["merge_repeats_identical"]:
            raise ValueError(f"{pair_id}: raw snapshots or merge repeats differ")
        if not posthoc["identical_repeats"]:
            raise ValueError(f"{pair_id}: merge repeats differ")
        if any(task["status"] != "ok" for task in posthoc["tasks"]):
            raise ValueError(f"{pair_id}: a task capture did not complete")
        label = posthoc["merge_status"]
        if label not in ("clean", "conflict"):
            raise ValueError(f"{pair_id}: unexpected label {label!r}")
        by_task = {
            task["task_id"]: [entry["path"] for entry in task["changed_paths"]]
            for task in posthoc["tasks"]
        }
        if set(by_task) != set(task_ids):
            raise ValueError(f"{pair_id}: changed-path tasks do not match task ids")
        pairs.append(_record(pair_id, "controlled-v3", repo_id, repositories[repo_id],
                             task_ids, label, by_task, posthoc["conflict_paths"], tasks))
    return pairs


def _fresh_pairs(plan, results, plan_path):
    repositories = _repositories(plan)
    tasks = _index_by_task(plan, plan_path)
    task_records = {}
    for record in results.get("tasks", []):
        task_id = record["task_id"]
        if task_id in task_records:
            raise ValueError(f"duplicate task record {task_id}")
        task_records[task_id] = record
    if set(task_records) != set(tasks):
        raise ValueError("fresh task records do not match the frozen plan tasks")
    pairs = []
    for pair in results["pairs"]:
        pair_id = pair["pair_id"]
        repo_id = pair["repo_id"]
        task_ids = pair["task_ids"]
        _check_pair(pair_id, repo_id, task_ids, repositories, tasks)
        if not pair["starting_snapshots_equal"] or not pair["merge_repeats_identical"]:
            raise ValueError(f"{pair_id}: snapshots or merge repeats differ")
        label = pair["label"]
        if label not in ("clean", "conflict"):
            raise ValueError(f"{pair_id}: unexpected label {label!r}")
        by_task = {}
        for task_id in task_ids:
            record = task_records[task_id]
            if record["pair_id"] != pair_id or record["repo_id"] != repo_id:
                raise ValueError(f"{pair_id}: task record {task_id} belongs elsewhere")
            if not record.get("replay_ok"):
                raise ValueError(f"{pair_id}: task {task_id} did not replay")
            if record["prompt_sha256"] != tasks[task_id]["prompt_sha256"]:
                raise ValueError(f"{pair_id}: task {task_id} prompt hash differs")
            by_task[task_id] = record["changed_paths"]
        if sorted(tuple(paths) for paths in pair["changed_paths"]) != sorted(
                tuple(by_task[task_id]) for task_id in task_ids):
            raise ValueError(f"{pair_id}: pair and task changed paths disagree")
        pairs.append(_record(pair_id, "fresh-2026-11", repo_id, repositories[repo_id],
                             task_ids, label, by_task, pair["conflict_paths"], tasks))
    return pairs


def _record(pair_id, cohort, repo_id, repo, task_ids, label, by_task, conflict_paths, tasks):
    return {
        "instance_id": pair_id,
        "cohort": cohort,
        "repo": repo,
        "repo_id": repo_id,
        "task_a_id": task_ids[0],
        "task_b_id": task_ids[1],
        "task_a": tasks[task_ids[0]]["text"],
        "task_b": tasks[task_ids[1]]["text"],
        "label": label,
        "changed_paths_a": by_task[task_ids[0]],
        "changed_paths_b": by_task[task_ids[1]],
        "conflict_paths": list(conflict_paths),
    }


def _check_pairs(pairs):
    if len(pairs) != EXPECTED_PAIRS:
        raise ValueError(f"expected {EXPECTED_PAIRS} pairs, found {len(pairs)}")
    ids = [pair["instance_id"] for pair in pairs]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate pair ids")
    repos = [pair["repo"] for pair in pairs]
    if len(set(repos)) != len(repos):
        raise ValueError("each pair must use a distinct repository")
    task_ids = [task for pair in pairs for task in (pair["task_a_id"], pair["task_b_id"])]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("a task is reused across pairs")
    if {pair["label"] for pair in pairs} != {"clean", "conflict"}:
        raise ValueError("the table needs both label classes")
    for pair in pairs:
        if not pair["task_a"].strip() or not pair["task_b"].strip():
            raise ValueError(f"{pair['instance_id']}: empty task text")
        if pair["task_a"] == pair["task_b"]:
            raise ValueError(f"{pair['instance_id']}: both tasks have the same text")


def _source_record(label, plan_path, result_path, extra=None):
    record = {
        "cohort": label,
        "plan_file_sha256": _sha256_file(plan_path),
        "results_file_sha256": _sha256_file(result_path),
    }
    if extra:
        record.update(extra)
    return record


def build_table(v3_plan_path=V3_PLAN, v3_results_path=V3_RESULTS,
                fresh_plan_path=FRESH_PLAN, fresh_results_path=FRESH_RESULTS):
    """Return (table, public summary) built from the frozen inputs."""
    v3_plan = _load(v3_plan_path)
    v3_results = _load(v3_results_path)
    fresh_plan = _load(fresh_plan_path)
    fresh_results = _load(fresh_results_path)

    _check_plan_digest(v3_plan)
    _check_plan_digest(fresh_plan)
    if fresh_plan.get("plan_sha256") != fresh_results.get("plan_sha256"):
        raise ValueError("fresh plan hash does not match the published summary")
    if fresh_plan.get("run_id") != fresh_results.get("run_id"):
        raise ValueError("fresh run id does not match the published summary")

    pairs = (_v3_pairs(v3_plan, v3_results, v3_plan_path)
             + _fresh_pairs(fresh_plan, fresh_results, fresh_plan_path))
    _check_pairs(pairs)

    sources = [
        _source_record("controlled-v3", v3_plan_path, v3_results_path,
                       {"run_id": v3_plan.get("run_id"),
                        "plan_sha256": v3_plan.get("plan_sha256")}),
        _source_record("fresh-2026-11", fresh_plan_path, fresh_results_path,
                       {"run_id": fresh_plan.get("run_id"),
                        "plan_sha256": fresh_plan.get("plan_sha256"),
                        "capture_policy": fresh_results.get("capture_policy")}),
    ]
    body = {"protocol_version": PROTOCOL_VERSION, "sources": sources, "pairs": pairs}
    table_sha256 = _sha256_bytes(_canonical_json(body))
    table = dict(body, table_sha256=table_sha256)

    by_cohort = {}
    for pair in pairs:
        counts = by_cohort.setdefault(pair["cohort"], {"pairs": 0, "clean": 0, "conflict": 0,
                                                       "repositories": set()})
        counts["pairs"] += 1
        counts[pair["label"]] += 1
        counts["repositories"].add(pair["repo"])
    cohorts = []
    for source in sources:
        counts = by_cohort[source["cohort"]]
        cohorts.append(dict(source, pairs=counts["pairs"], clean=counts["clean"],
                            conflict=counts["conflict"],
                            repositories=sorted(counts["repositories"])))

    summary = {
        "protocol_version": PROTOCOL_VERSION,
        "pairs": len(pairs),
        "clean": sum(pair["label"] == "clean" for pair in pairs),
        "conflict": sum(pair["label"] == "conflict" for pair in pairs),
        "repositories": len({pair["repo"] for pair in pairs}),
        "cohorts": cohorts,
        "table_sha256": table_sha256,
        "task_text_public": False,
        "note": ("Full task text, changed paths and pair rows stay in the ignored "
                 "private data root. This summary carries counts, labels and hashes only."),
    }
    return table, summary


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="rebuild and compare with the saved table hash")
    args = parser.parse_args(argv)

    table, summary = build_table()
    table = dict(table, built_at=datetime.now(timezone.utc).isoformat())
    verify_table(table)
    if args.check:
        existing = _load(PRIVATE_OUT)
        verify_table(existing)
        if existing.get("table_sha256") != table["table_sha256"]:
            raise SystemExit("saved table does not match the frozen inputs")
        print(f"table matches: {table['table_sha256']}")
        return
    _write(PRIVATE_OUT, table)
    _write(PUBLIC_OUT, summary)
    print(f"wrote {PRIVATE_OUT.relative_to(ROOT)}")
    print(f"wrote {PUBLIC_OUT.relative_to(ROOT)}")
    print(f"pairs {summary['pairs']}, clean {summary['clean']}, conflict {summary['conflict']}")
    print(f"table sha256 {table['table_sha256']}")


if __name__ == "__main__":
    main()
