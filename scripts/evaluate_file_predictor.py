"""Evaluate the path-only file predictor on the ten constructed pairs.

The predictor ranks repository file paths by TF-IDF similarity to a task
description. This run asks three questions:

1. Does it find the files each task actually changed?
2. Does the overlap between its two top-k lists predict the merge label?
3. Does adding that overlap improve the task-text baseline?

Ten pairs cannot establish accuracy. The run is a construction check and a
baseline for a better file predictor.

    python3 scripts/evaluate_file_predictor.py
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_controlled_prediction import verify_table
from evaltools.metrics import average_precision, pr_auc_trapezoid
from file_predictor import predict_files_tfidf
from run_controlled_predictions import _strip_paths

TABLE = ROOT / "data/private/research/controlled-prediction-10/table.json"
TEXT_RESULTS = ROOT / "data/controlled-prediction-10/results.json"
V3_PLAN = ROOT / "data/private/research/controlled-single-project-v3/plan.json"
FRESH_PLAN = ROOT / "data/private/research/controlled-single-project-fresh-2026-11-20-v2/plan.json"
PRIVATE_OUT = ROOT / "data/private/research/controlled-prediction-10/file-predictor.json"
PUBLIC_OUT = ROOT / "data/controlled-prediction-10/file-predictor.json"
PROTOCOL_VERSION = "file-predictor-evaluation-1"


def _load(path):
    if not path.is_file():
        raise ValueError(f"missing input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _anchors():
    return {
        "controlled-v3": _load(V3_PLAN)["anchor"]["commit"],
        "fresh-2026-11": _load(FRESH_PLAN)["anchor"]["commit"],
    }


def git_files(anchor, repo_id):
    """List the files in a repository subtree at the frozen anchor commit."""
    spec = f"{anchor}:controlled_sources/{repo_id}"
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", spec],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot list {spec}: {result.stderr.strip()}")
    files = [line for line in result.stdout.splitlines() if line]
    if not files:
        raise ValueError(f"no files found in {spec}")
    return files


def jaccard(first, second):
    first, second = set(first), set(second)
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def rank_task(task, files, top_k=5, strip_paths=False):
    text = _strip_paths(task) if strip_paths else task
    return predict_files_tfidf(text, files, top_k=top_k)


def _recall(predicted, actual):
    actual = set(actual)
    return len(set(predicted) & actual) / len(actual) if actual else 0.0


def _conflict_recall(predicted_a, predicted_b, conflict_paths):
    conflict_paths = set(conflict_paths)
    if not conflict_paths:
        return None
    return len((set(predicted_a) | set(predicted_b)) & conflict_paths) / len(conflict_paths)


def pair_row(pair, files, text_scores, top_k=5, rank=rank_task):
    predicted_a = rank(pair["task_a"], files, top_k=top_k)
    predicted_b = rank(pair["task_b"], files, top_k=top_k)
    stripped_a = rank(pair["task_a"], files, top_k=top_k, strip_paths=True)
    stripped_b = rank(pair["task_b"], files, top_k=top_k, strip_paths=True)

    paths_a = [path for path, _ in predicted_a]
    paths_b = [path for path, _ in predicted_b]
    stripped_paths_a = [path for path, _ in stripped_a]
    stripped_paths_b = [path for path, _ in stripped_b]
    changed_a = pair["changed_paths_a"]
    changed_b = pair["changed_paths_b"]

    return {
        "instance_id": pair["instance_id"],
        "cohort": pair["cohort"],
        "repo": pair["repo"],
        "repo_id": pair["repo_id"],
        "label": pair["label"],
        "text_score": text_scores[pair["instance_id"]],
        "predicted_a": paths_a,
        "predicted_b": paths_b,
        "predicted_overlap": jaccard(paths_a, paths_b),
        "actual_overlap": jaccard(changed_a, changed_b),
        "recall_a": _recall(paths_a, changed_a),
        "recall_b": _recall(paths_b, changed_b),
        "recall_mean": (_recall(paths_a, changed_a) + _recall(paths_b, changed_b)) / 2,
        "conflict_recall": _conflict_recall(paths_a, paths_b, pair["conflict_paths"]),
        "stripped_predicted_a": stripped_paths_a,
        "stripped_predicted_b": stripped_paths_b,
        "stripped_overlap": jaccard(stripped_paths_a, stripped_paths_b),
        "stripped_recall_a": _recall(stripped_paths_a, changed_a),
        "stripped_recall_b": _recall(stripped_paths_b, changed_b),
        "stripped_recall_mean": (
            _recall(stripped_paths_a, changed_a) + _recall(stripped_paths_b, changed_b)
        ) / 2,
        "stripped_conflict_recall": _conflict_recall(
            stripped_paths_a, stripped_paths_b, pair["conflict_paths"]),
    }


def _ap(rows, key):
    labels = [int(row["label"] == "conflict") for row in rows]
    scores = [row[key] for row in rows]
    return average_precision(labels, scores), pr_auc_trapezoid(labels, scores)


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def summarize(rows, top_k):
    labels = [int(row["label"] == "conflict") for row in rows]
    conflicts = sum(labels)
    overlap_ap, overlap_pr = _ap(rows, "predicted_overlap")
    actual_ap, actual_pr = _ap(rows, "actual_overlap")
    stripped_ap, stripped_pr = _ap(rows, "stripped_overlap")
    text_ap = average_precision(labels, [row["text_score"] for row in rows])
    equal_ap = average_precision(
        labels, [0.5 * row["text_score"] + 0.5 * row["predicted_overlap"] for row in rows])
    heavy_ap = average_precision(
        labels, [0.75 * row["text_score"] + 0.25 * row["predicted_overlap"] for row in rows])
    flagged = [row for row in rows if row["predicted_overlap"] > 0]
    summary = {
        "protocol_version": PROTOCOL_VERSION,
        "top_k": top_k,
        "pairs": len(rows),
        "conflicts": conflicts,
        "repositories": len({row["repo"] for row in rows}),
        "mean_recall_at_k": _mean([row["recall_mean"] for row in rows]),
        "mean_conflict_path_recall": _mean([row["conflict_recall"] for row in rows]),
        "predicted_overlap_ap": overlap_ap,
        "predicted_overlap_pr_auc": overlap_pr,
        "actual_overlap_ap": actual_ap,
        "actual_overlap_pr_auc": actual_pr,
        "actual_overlap_is_oracle": True,
        "text_only_ap": text_ap,
        "equal_blend_ap": equal_ap,
        "text_heavy_blend_ap": heavy_ap,
        "stripped_overlap_ap": stripped_ap,
        "stripped_overlap_pr_auc": stripped_pr,
        "stripped_mean_recall_at_k": _mean([row["stripped_recall_mean"] for row in rows]),
        "stripped_mean_conflict_path_recall": _mean(
            [row["stripped_conflict_recall"] for row in rows]),
        "overlap_positive_rule": {
            "flagged": len(flagged),
            "true_positives": sum(1 for row in flagged if row["label"] == "conflict"),
            "false_positives": sum(1 for row in flagged if row["label"] == "clean"),
            "missed_conflicts": sum(
                1 for row in rows
                if row["label"] == "conflict" and row["predicted_overlap"] == 0),
        },
        "per_pair": [
            {
                "instance_id": row["instance_id"],
                "repo": row["repo"],
                "label": row["label"],
                "text_score": row["text_score"],
                "predicted_overlap": row["predicted_overlap"],
                "actual_overlap": row["actual_overlap"],
                "recall_mean": row["recall_mean"],
                "conflict_recall": row["conflict_recall"],
                "stripped_overlap": row["stripped_overlap"],
                "stripped_recall_mean": row["stripped_recall_mean"],
                "stripped_conflict_recall": row["stripped_conflict_recall"],
            }
            for row in rows
        ],
    }
    return summary


def evaluate(table, anchors, text_scores, top_k=5, file_loader=git_files, rank=rank_task):
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    rows = []
    for pair in table["pairs"]:
        files = file_loader(anchors[pair["cohort"]], pair["repo_id"])
        rows.append(pair_row(pair, files, text_scores, top_k=top_k, rank=rank))
    return rows, summarize(rows, top_k)


def _private_rows(rows):
    return [
        {
            "instance_id": row["instance_id"],
            "repo": row["repo"],
            "label": row["label"],
            "predicted_a": row["predicted_a"],
            "predicted_b": row["predicted_b"],
            "stripped_predicted_a": row["stripped_predicted_a"],
            "stripped_predicted_b": row["stripped_predicted_b"],
        }
        for row in rows
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=PUBLIC_OUT)
    parser.add_argument("--private-out", type=Path, default=PRIVATE_OUT)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    table = _load(args.table)
    verify_table(table)
    text_results = _load(TEXT_RESULTS)
    text_scores = {row["instance_id"]: row["tfidf"] for row in text_results["scores"]}
    anchors = _anchors()
    rows, summary = evaluate(table, anchors, text_scores, top_k=args.top_k)

    private = dict(summary, table_sha256=table["table_sha256"],
                   pairs_detail=_private_rows(rows))
    public = dict(summary, table_sha256=table["table_sha256"],
                  task_text_public=False)
    args.private_out.parent.mkdir(parents=True, exist_ok=True)
    args.private_out.write_text(
        json.dumps(private, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"pairs {summary['pairs']}, conflicts {summary['conflicts']}, top_k {summary['top_k']}")
    print(f"mean recall@k {summary['mean_recall_at_k']:.3f}")
    print(f"mean conflict-path recall {summary['mean_conflict_path_recall']:.3f}")
    print(f"predicted overlap AP {summary['predicted_overlap_ap']:.3f}")
    print(f"actual overlap AP {summary['actual_overlap_ap']:.3f} (oracle)")
    print(f"text-only AP {summary['text_only_ap']:.3f}")
    print(f"equal blend AP {summary['equal_blend_ap']:.3f}")
    print(f"text-heavy blend AP {summary['text_heavy_blend_ap']:.3f}")
    print(f"stripped overlap AP {summary['stripped_overlap_ap']:.3f}")
    print(f"stripped mean recall@k {summary['stripped_mean_recall_at_k']:.3f}")
    rule = summary["overlap_positive_rule"]
    print(f"overlap > 0: flagged {rule['flagged']}, "
          f"true positives {rule['true_positives']}, "
          f"false positives {rule['false_positives']}, "
          f"missed conflicts {rule['missed_conflicts']}")
    print(f"wrote {args.private_out}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
