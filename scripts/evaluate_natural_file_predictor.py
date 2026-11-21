"""Evaluate the path-only file predictor on the natural-mix cohort.

Inputs are the private natural-cohort table, the fetched repository trees and
changed-file lists, and the text-only scores for the same pairs. The run asks:

1. Does rank-by-path-similarity find the files each task changed?
2. Does predicted overlap separate clean from conflicting pairs?
3. Does adding overlap improve the text-only score?

The pilot is a balanced sample of real co-active PR pairs. It is a signal check;
the full cohort run is the one that can support a claim.

    python3 scripts/evaluate_natural_file_predictor.py \
        --repo-data data/private/research/natural-cohort-2026-11/repo-data.jsonl
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_natural_cohort import verify_table
from evaltools.bootstrap import cluster_bootstrap
from evaltools.metrics import average_precision, pr_auc_trapezoid
from sklearn.metrics import roc_auc_score
from file_predictor import predict_files_tfidf
from run_controlled_predictions import _strip_paths

PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
TABLE = PRIVATE / "table.json"
TEXT_RESULTS = {
    "title": ROOT / "data/natural-cohort-2026-11/results-title.json",
    "issue_title_body": ROOT / "data/natural-cohort-2026-11/results-issue_title_body.json",
}
PUBLIC_OUT = ROOT / "data/natural-cohort-2026-11/file-predictor-pilot.json"
PROTOCOL_VERSION = "natural-file-predictor-1"
TOP_K = 5


def _strict_issue(pair):
    if pair.get("issue_source_a") != "body" or pair.get("issue_source_b") != "body":
        return False
    times = (pair.get("issue_created_a"), pair.get("issue_created_b"),
             pair.get("created_a"), pair.get("created_b"))
    if any(value is None for value in times):
        return False
    return times[0] < times[2] and times[1] < times[3]


def _load_json(path):
    if not path.is_file():
        raise ValueError(f"missing input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path):
    rows = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            rows[row["instance_id"]] = row
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid row") from exc
    return rows


def jaccard(first, second):
    first, second = set(first), set(second)
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def recall(predicted, actual):
    actual = set(actual)
    return len(set(predicted) & actual) / len(actual) if actual else 0.0


def _percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
    return values[index]


def _paired_gain(rows, first_key, second_key, n_boot=1000, seed=0):
    """Paired repository-bootstrap difference second minus first."""
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault(row["repo"], []).append(index)
    repos = sorted(groups)
    rng = random.Random(seed)
    ap_diffs, auc_diffs = [], []
    for _ in range(n_boot):
        indices = []
        for _ in repos:
            indices.extend(groups[rng.choice(repos)])
        labels = [int(rows[i]["label"] == "conflict") for i in indices]
        if len(set(labels)) < 2:
            continue
        first = [rows[i][first_key] for i in indices]
        second = [rows[i][second_key] for i in indices]
        ap_diffs.append(average_precision(labels, second)
                        - average_precision(labels, first))
        auc_diffs.append(roc_auc_score(labels, second) - roc_auc_score(labels, first))
    if not ap_diffs:
        return None
    return {
        "ap_difference": _percentile(ap_diffs, 0.5),
        "ap_interval": [_percentile(ap_diffs, 0.025), _percentile(ap_diffs, 0.975)],
        "auc_difference": _percentile(auc_diffs, 0.5),
        "auc_interval": [_percentile(auc_diffs, 0.025), _percentile(auc_diffs, 0.975)],
        "bootstrap": len(ap_diffs),
    }


def directory(path):
    parent = str(Path(path).parent)
    return "" if parent == "." else parent


def _rank(task, files, top_k=TOP_K, stripped=False):
    text = _strip_paths(task) if stripped else task
    return predict_files_tfidf(text, files, top_k=top_k)


def _conflict_intersection(predicted_a, predicted_b, conflict_paths):
    conflict_paths = set(conflict_paths)
    if not conflict_paths:
        return None
    shared = set(predicted_a) & set(predicted_b)
    return len(shared & conflict_paths) / len(conflict_paths)


def _conflict_coverage(conflict_paths, tree_set):
    conflict_paths = list(conflict_paths)
    if not conflict_paths:
        return None
    return sum(1 for path in conflict_paths if path in tree_set) / len(conflict_paths)


def _conflict_recall(predicted_a, predicted_b, conflict_paths):
    conflict_paths = set(conflict_paths)
    if not conflict_paths:
        return None
    return len((set(predicted_a) | set(predicted_b)) & conflict_paths) / len(conflict_paths)


def pair_row(pair, fetched, text_score, task_a, task_b):
    files = fetched["tree_paths"]
    tree_set = set(files)
    ranked_a = _rank(task_a, files)
    ranked_b = _rank(task_b, files)
    predicted_a = [path for path, _ in ranked_a]
    predicted_b = [path for path, _ in ranked_b]
    nonzero_a = [path for path, score in ranked_a if score > 0]
    nonzero_b = [path for path, score in ranked_b if score > 0]
    stripped_a = [path for path, _ in _rank(task_a, files, stripped=True)]
    stripped_b = [path for path, _ in _rank(task_b, files, stripped=True)]
    changed_a = [row["path"] for row in fetched["files_a"]]
    changed_b = [row["path"] for row in fetched["files_b"]]
    available_a = [path for path in changed_a if path in tree_set]
    available_b = [path for path in changed_b if path in tree_set]
    rng = random.Random(pair["instance_id"])
    random_a = sorted(rng.sample(files, min(TOP_K, len(files)))) if files else []
    random_b = sorted(rng.sample(files, min(TOP_K, len(files)))) if files else []
    dirs_a = {directory(path) for path in predicted_a}
    dirs_b = {directory(path) for path in predicted_b}
    return {
        "instance_id": pair["instance_id"],
        "repo": pair["repo"],
        "pr_a": pair["pr_a"],
        "pr_b": pair["pr_b"],
        "language": pair.get("language"),
        "stratum": pair["stratum"],
        "label": pair["label"],
        "text_score": text_score,
        "tree_files": len(files),
        "tree_truncated": fetched.get("tree_truncated", False),
        "files_truncated": fetched.get("files_truncated", False),
        "changed_a": changed_a,
        "changed_b": changed_b,
        "predicted_a": predicted_a,
        "predicted_b": predicted_b,
        "predicted_overlap": jaccard(predicted_a, predicted_b),
        "nonzero_overlap": jaccard(nonzero_a, nonzero_b),
        "random_overlap": jaccard(random_a, random_b),
        "directory_overlap": jaccard(dirs_a, dirs_b),
        "actual_overlap": jaccard(changed_a, changed_b),
        "recall_a": recall(predicted_a, changed_a),
        "recall_b": recall(predicted_b, changed_b),
        "recall_mean": (recall(predicted_a, changed_a) + recall(predicted_b, changed_b)) / 2,
        "recall_available_mean": (recall(predicted_a, available_a)
                                  + recall(predicted_b, available_b)) / 2,
        "coverage_mean": ((len(available_a) / len(changed_a) if changed_a else 0.0)
                          + (len(available_b) / len(changed_b) if changed_b else 0.0)) / 2,
        "conflict_recall": _conflict_recall(predicted_a, predicted_b,
                                            pair.get("conflict_paths", [])),
        "conflict_intersection_recall": _conflict_intersection(
            predicted_a, predicted_b, pair.get("conflict_paths", [])),
        "conflict_path_coverage": _conflict_coverage(
            pair.get("conflict_paths", []), tree_set),
        "stripped_predicted_a": stripped_a,
        "stripped_predicted_b": stripped_b,
        "stripped_overlap": jaccard(stripped_a, stripped_b),
        "stripped_recall_mean": (
            recall(stripped_a, changed_a) + recall(stripped_b, changed_b)) / 2,
        "stripped_conflict_recall": _conflict_recall(
            stripped_a, stripped_b, pair.get("conflict_paths", [])),
    }


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _ap(rows, key):
    labels = [int(row["label"] == "conflict") for row in rows]
    scores = [row[key] for row in rows]
    return average_precision(labels, scores), pr_auc_trapezoid(labels, scores)


def _bootstrap(rows, key):
    labels = [int(row["label"] == "conflict") for row in rows]
    scores = [row[key] for row in rows]
    repos = [row["repo"] for row in rows]

    def ap(y, s):
        return average_precision(y, s)

    return cluster_bootstrap(labels, scores, repos, ap, 1000, 0)


def _strata_metrics(rows):
    out = {}
    for key in ("same", "cross"):
        group = [row for row in rows if row["stratum"] == key]
        if len(group) < 5:
            continue
        labels = [int(row["label"] == "conflict") for row in group]
        if len(set(labels)) < 2:
            continue
        out[key] = {
            "pairs": len(group),
            "conflicts": sum(labels),
            "prevalence": sum(labels) / len(labels),
            "text_ap": average_precision(labels, [row["text_score"] for row in group]),
            "text_auc": roc_auc_score(labels, [row["text_score"] for row in group]),
            "overlap_ap": average_precision(
                labels, [row["predicted_overlap"] for row in group]),
            "overlap_auc": roc_auc_score(
                labels, [row["predicted_overlap"] for row in group]),
            "oracle_ap": average_precision(
                labels, [row["actual_overlap"] for row in group]),
            "oracle_auc": roc_auc_score(
                labels, [row["actual_overlap"] for row in group]),
        }
    return out


def summarize(rows):
    labels = [int(row["label"] == "conflict") for row in rows]
    overlap_ap, overlap_pr = _ap(rows, "predicted_overlap")
    directory_ap, directory_pr = _ap(rows, "directory_overlap")
    actual_ap, actual_pr = _ap(rows, "actual_overlap")
    text_ap = average_precision(labels, [row["text_score"] for row in rows])
    text_auc = roc_auc_score(labels, [row["text_score"] for row in rows])
    blended = {
        "equal": average_precision(
            labels, [0.5 * row["text_score"] + 0.5 * row["predicted_overlap"] for row in rows]),
        "text_heavy": average_precision(
            labels, [0.75 * row["text_score"] + 0.25 * row["predicted_overlap"] for row in rows]),
        "path_heavy": average_precision(
            labels, [0.25 * row["text_score"] + 0.75 * row["predicted_overlap"] for row in rows]),
    }
    nonzero_ap, nonzero_pr = _ap(rows, "nonzero_overlap")
    random_ap, random_pr = _ap(rows, "random_overlap")
    blend_values = {
        "equal": [0.5 * row["text_score"] + 0.5 * row["predicted_overlap"] for row in rows],
        "text_heavy": [0.75 * row["text_score"] + 0.25 * row["predicted_overlap"] for row in rows],
        "path_heavy": [0.25 * row["text_score"] + 0.75 * row["predicted_overlap"] for row in rows],
    }
    for index, row in enumerate(rows):
        row["blend_equal"] = blend_values["equal"][index]
        row["blend_text_heavy"] = blend_values["text_heavy"][index]
        row["blend_path_heavy"] = blend_values["path_heavy"][index]
    flagged = [row for row in rows if row["predicted_overlap"] > 0]
    by_language = {}
    for row in rows:
        key = row["language"] or "unknown"
        by_language.setdefault(key, []).append(row)
    languages = {}
    for key, group in sorted(by_language.items(), key=lambda kv: -len(kv[1])):
        if len(group) >= 5:
            languages[key] = {
                "pairs": len(group),
                "conflicts": sum(1 for row in group if row["label"] == "conflict"),
                "mean_recall": _mean([row["recall_mean"] for row in group]),
                "predicted_overlap_ap": average_precision(
                    [int(row["label"] == "conflict") for row in group],
                    [row["predicted_overlap"] for row in group]),
            }
    by_stratum = {}
    for key in ("same", "cross"):
        group = [row for row in rows if row["stratum"] == key]
        if group:
            by_stratum[key] = {
                "pairs": len(group),
                "conflicts": sum(1 for row in group if row["label"] == "conflict"),
                "mean_recall": _mean([row["recall_mean"] for row in group]),
            }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "top_k": TOP_K,
        "pairs": len(rows),
        "conflicts": sum(labels),
        "prevalence": sum(labels) / len(labels),
        "repositories": len({row["repo"] for row in rows}),
        "mean_recall_at_k": _mean([row["recall_mean"] for row in rows]),
        "mean_recall_at_k_available_paths": _mean(
            [row["recall_available_mean"] for row in rows]),
        "mean_changed_path_coverage": _mean([row["coverage_mean"] for row in rows]),
        "mean_conflict_path_recall": _mean([row["conflict_recall"] for row in rows]),
        "mean_conflict_intersection_recall": _mean(
            [row["conflict_intersection_recall"] for row in rows]),
        "mean_conflict_path_coverage": _mean(
            [row["conflict_path_coverage"] for row in rows]),
        "predicted_overlap_ap": overlap_ap,
        "predicted_overlap_ap_interval": _bootstrap(rows, "predicted_overlap"),
        "predicted_overlap_auc": roc_auc_score(labels, [row["predicted_overlap"] for row in rows]),
        "predicted_overlap_pr_auc": overlap_pr,
        "directory_overlap_ap": directory_ap,
        "directory_overlap_auc": roc_auc_score(labels, [row["directory_overlap"] for row in rows]),
        "directory_overlap_pr_auc": directory_pr,
        "actual_overlap_ap": actual_ap,
        "actual_overlap_auc": roc_auc_score(labels, [row["actual_overlap"] for row in rows]),
        "actual_overlap_pr_auc": actual_pr,
        "actual_overlap_is_oracle": True,
        "text_only_ap": text_ap,
        "text_only_auc": text_auc,
        "nonzero_overlap_ap": nonzero_ap,
        "nonzero_overlap_pr_auc": nonzero_pr,
        "random_overlap_ap": random_ap,
        "random_overlap_auc": roc_auc_score(labels, [row["random_overlap"] for row in rows]),
        "random_overlap_pr_auc": random_pr,
        "blends": blended,
        "paired_gain_equal_blend": _paired_gain(rows, "text_score", "blend_equal"),
        "paired_gain_text_heavy": _paired_gain(rows, "text_score", "blend_text_heavy"),
        "stripped_overlap_ap": _ap(rows, "stripped_overlap")[0],
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
        "languages": languages,
        "strata": by_stratum,
        "strata_metrics": _strata_metrics(rows),
        "per_pair": rows,
        "caveats": [
            "Balanced pilot of real co-active PR pairs; prevalence is not a base rate.",
            "Task text is the PR title, written when the PR opens, not before coding.",
            "Trees come from the common base of the two PR heads; later base drift is not modeled.",
            "Changed-file lists come from the GitHub files API and may be truncated at 300.",
            "Top five is fixed for comparability with the constructed-pair run.",
            "A pilot cannot establish generalization; it is a signal check for the full cohort.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--repo-data", type=Path, default=PRIVATE / "repo-data.jsonl")
    parser.add_argument("--text", choices=("title", "issue_title_body"), default="title")
    parser.add_argument("--strict-issue", action="store_true",
                        help="keep only pairs where both PRs close a pre-created issue")
    parser.add_argument("--text-results", type=Path, default=None)
    parser.add_argument("--selection", type=Path, default=None,
                        help="manifest whose selected IDs must all be accounted for")
    parser.add_argument("--out", type=Path, default=PUBLIC_OUT)
    args = parser.parse_args(argv)

    table = _load_json(args.table)
    verify_table(table)
    text_path = args.text_results or TEXT_RESULTS[args.text]
    text = _load_json(text_path)
    if text.get("table_sha256") != table.get("table_sha256"):
        raise ValueError("text results were produced from a different table")
    text_scores = {row["instance_id"]: row for row in text["scores"]}
    fetched = _load_jsonl(args.repo_data)
    pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
    if args.strict_issue:
        pairs = {key: pair for key, pair in pairs.items() if _strict_issue(pair)}
    selected_ids = None
    if args.selection:
        selected_ids = set(_load_json(args.selection)["instance_ids"]) & set(pairs)
        fetched = {key: value for key, value in fetched.items()
                   if key in selected_ids}

    rows, skipped = [], []
    for instance_id, data in fetched.items():
        pair = pairs.get(instance_id)
        if pair is None:
            skipped.append({"instance_id": instance_id, "reason": "not-in-table"})
            continue
        if data.get("status") != "ok":
            skipped.append({"instance_id": instance_id,
                            "reason": data.get("status", "unknown")})
            continue
        if data.get("tree_truncated"):
            skipped.append({"instance_id": instance_id, "reason": "tree-truncated"})
            continue
        if data.get("files_truncated"):
            skipped.append({"instance_id": instance_id, "reason": "files-truncated"})
            continue
        if pair["title_a"].strip().casefold() == pair["title_b"].strip().casefold():
            skipped.append({"instance_id": instance_id, "reason": "identical-text"})
            continue
        if instance_id not in text_scores:
            skipped.append({"instance_id": instance_id, "reason": "no-text-score"})
            continue
        if args.text == "issue_title_body":
            task_a = (pair["issue_title_a"] + "\n\n" + (pair.get("issue_body_a") or "")).strip()
            task_b = (pair["issue_title_b"] + "\n\n" + (pair.get("issue_body_b") or "")).strip()
        else:
            task_a, task_b = pair["title_a"], pair["title_b"]
        if not task_a or not task_b:
            skipped.append({"instance_id": instance_id, "reason": "missing-task-text"})
            continue
        row = pair_row(pair, data, text_scores[instance_id]["tfidf"], task_a, task_b)
        rows.append(row)
    if selected_ids is not None:
        for instance_id in sorted(selected_ids - set(fetched)):
            skipped.append({"instance_id": instance_id, "reason": "not-fetched"})
        missing = selected_ids - {row["instance_id"] for row in rows} - {
            item["instance_id"] for item in skipped}
        if missing:
            raise ValueError(f"{len(missing)} selected pairs are unaccounted for")

    rows.sort(key=lambda row: row["instance_id"])
    if not rows:
        raise SystemExit("no usable fetched pairs")

    summary = summarize(rows)
    summary["table_sha256"] = table["table_sha256"]
    summary["text_variant"] = args.text
    summary["strict_issue"] = args.strict_issue
    summary["selection"] = {
        "manifest": args.selection.name if args.selection else None,
        "selected": len(selected_ids) if selected_ids is not None else None,
        "scored": len(rows),
        "skipped": len(skipped),
    }
    summary["skipped"] = skipped
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")

    print(f"text {args.text}{' strict-issue' if args.strict_issue else ''}: "
          f"pairs {summary['pairs']} ({summary['conflicts']} conflicts, "
          f"{summary['repositories']} repos); skipped {len(skipped)}")
    print(f"mean recall@{TOP_K} {summary['mean_recall_at_k']:.3f}; "
          f"conflict-path recall {summary['mean_conflict_path_recall'] or float('nan'):.3f}")
    print(f"predicted overlap AP {summary['predicted_overlap_ap']:.3f} "
          f"[{summary['predicted_overlap_ap_interval']['low']:.3f}, "
          f"{summary['predicted_overlap_ap_interval']['high']:.3f}], "
          f"AUC {summary['predicted_overlap_auc']:.3f}")
    print(f"directory overlap AP {summary['directory_overlap_ap']:.3f}; "
          f"actual overlap AP {summary['actual_overlap_ap']:.3f}; "
          f"text only AP {summary['text_only_ap']:.3f} AUC {summary['text_only_auc']:.3f}")
    print(f"blends equal {summary['blends']['equal']:.3f}, "
          f"text-heavy {summary['blends']['text_heavy']:.3f}, "
          f"path-heavy {summary['blends']['path_heavy']:.3f}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
