"""Train and calibrate the CollisionGuard product model.

The model uses only pre-start inputs: the two task descriptions, the repository
language and size, and whether the same agent handles both tasks. It is trained
on the natural-mix title cohort and evaluated with repository-grouped folds.

    python3 scripts/train_product_model.py

Outputs:
- models/collisionguard-v0.2.joblib
- data/natural-cohort-2026-11/product-model.json
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from collisionguard.features import pair_features
from collisionguard.model import (
    SigmoidCalibrator, fit, raw_scores, save_artifact)
from evaltools.bootstrap import cluster_bootstrap
from evaltools.metrics import average_precision
from run_natural_predictions import _canonical_fold_map

PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
TABLE = PRIVATE / "table.json"
FILE_RESULTS = ROOT / "data/natural-cohort-2026-11/file-predictor.json"
STRICT_RESULTS = ROOT / "data/natural-cohort-2026-11/file-predictor-strict-issue.json"
MODEL_OUT = ROOT / "models" / "collisionguard-v0.2.joblib"
PUBLIC_OUT = ROOT / "data/natural-cohort-2026-11/product-model.json"
FOLDS = 5
SEED = 0
TOP_K = 5


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _features(pair, tree_files, task_a=None, task_b=None):
    return pair_features(
        task_a if task_a is not None else pair["title_a"],
        task_b if task_b is not None else pair["title_b"],
        language=pair.get("language"),
        tree_files=tree_files,
        same_agent=pair["stratum"] == "same",
        agent_a=pair.get("agent_a"),
        agent_b=pair.get("agent_b"),
    )


def _records(rows):
    return [{
        "instance_id": row["pair"]["instance_id"],
        "repo": row["pair"]["repo"],
        "task_a": row["pair"]["instance_id"] + "-a",
        "task_b": row["pair"]["instance_id"] + "-b",
        "family": None,
    } for row in rows]


def _oof(rows, labels, folds):
    features = [_features(row["pair"], row["tree_files"]) for row in rows]
    scores = [None] * len(rows)
    for train, test in folds:
        model, vectorizer = fit([features[i] for i in train], [labels[i] for i in train])
        batch = raw_scores(model, vectorizer, [features[i] for i in test])
        for index, value in zip(test, batch):
            scores[index] = value
    return scores


def _band_stats(scores, labels, low_cut, high_cut):
    bands = {}
    for name, predicate in (
        ("low", lambda value: value < low_cut),
        ("elevated", lambda value: low_cut <= value < high_cut),
        ("high", lambda value: value >= high_cut),
    ):
        members = [i for i, value in enumerate(scores) if predicate(value)]
        conflicts = sum(labels[i] for i in members)
        bands[name] = {
            "pairs": len(members),
            "conflicts": conflicts,
            "rate": conflicts / len(members) if members else None,
        }
    return bands


def _budget(scores, labels, fraction):
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    count = max(1, int(len(scores) * fraction))
    selected = order[:count]
    tp = sum(labels[i] for i in selected)
    precision = tp / count
    prevalence = sum(labels) / len(labels)
    return {
        "fraction": fraction,
        "selected": count,
        "true_positives": tp,
        "conflicts": sum(labels),
        "recall": tp / sum(labels),
        "precision": precision,
        "lift": precision / prevalence if prevalence else None,
    }


def _transfer(title_rows, issue_rows):
    issue_repos = {row["pair"]["repo"] for row in issue_rows}
    train = [row for row in title_rows if row["pair"]["repo"] not in issue_repos]
    features = [_features(row["pair"], row["tree_files"]) for row in train]
    labels = [1 if row["pair"]["label"] == "conflict" else 0 for row in train]
    model, vectorizer = fit(features, labels)
    test_features = []
    test_labels = []
    for row in issue_rows:
        pair = row["pair"]
        task_a = (pair.get("issue_title_a") or "").strip()
        task_b = (pair.get("issue_title_b") or "").strip()
        test_features.append(_features(pair, row["tree_files"], task_a, task_b))
        test_labels.append(1 if pair["label"] == "conflict" else 0)
    scores = raw_scores(model, vectorizer, test_features)
    repos = [row["pair"]["repo"] for row in issue_rows]
    return {
        "train_pairs": len(train),
        "test_pairs": len(test_labels),
        "conflicts": sum(test_labels),
        "average_precision": average_precision(test_labels, scores),
        "average_precision_interval": cluster_bootstrap(
            test_labels, scores, repos, average_precision, 1000, 0),
        "roc_auc": roc_auc_score(test_labels, scores),
        "roc_auc_interval": cluster_bootstrap(
            test_labels, scores, repos, roc_auc_score, 1000, 0),
        "scheme": "train on title pairs from repositories absent from the issue subset; test on issue titles",
    }


def _forward(title_rows, labels):
    order = sorted(range(len(title_rows)),
                   key=lambda i: (title_rows[i]["pair"].get("created_a") or "",
                                  title_rows[i]["pair"].get("created_b") or ""))
    cut = int(len(order) * 0.7)
    train, test = order[:cut], order[cut:]
    features = [_features(row["pair"], row["tree_files"]) for row in title_rows]
    model, vectorizer = fit([features[i] for i in train], [labels[i] for i in train])
    scores = raw_scores(model, vectorizer, [features[i] for i in test])
    y = [labels[i] for i in test]
    return {
        "train_pairs": len(train),
        "test_pairs": len(test),
        "conflicts": sum(y),
        "average_precision": average_precision(y, scores),
        "roc_auc": roc_auc_score(y, scores),
    }


def main():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _main()


def _main():
    table = _load(TABLE)
    file_results = _load(FILE_RESULTS)
    if file_results.get("table_sha256") != table["table_sha256"]:
        raise ValueError("file results belong to a different table")
    pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
    by_id = {row["instance_id"]: row for row in file_results["per_pair"]}

    title_rows = []
    for row in file_results["per_pair"]:
        pair = pairs[row["instance_id"]]
        if pair["title_a"].strip().casefold() == pair["title_b"].strip().casefold():
            continue
        title_rows.append({"pair": pair, "tree_files": row.get("tree_files", 0)})
    labels = [1 if row["pair"]["label"] == "conflict" else 0 for row in title_rows]
    fold_of = _canonical_fold_map(table)
    folds = []
    for fold in range(FOLDS):
        test = [index for index, row in enumerate(title_rows)
                if fold_of[row["pair"]["instance_id"]] == fold]
        train = [index for index, row in enumerate(title_rows)
                 if fold_of[row["pair"]["instance_id"]] != fold]
        folds.append((train, test))
    oof = _oof(title_rows, labels, folds)
    raw_ap = average_precision(labels, oof)
    raw_auc = roc_auc_score(labels, oof)
    calibrator = SigmoidCalibrator().fit(oof, labels)
    calibrated = [float(value) for value in calibrator.predict(oof)]
    # Leave-one-fold-out calibration is the honest estimate. A calibrator
    # fitted on its own inputs is optimistic even when those inputs are
    # out-of-fold classifier scores.
    crossfit = [None] * len(oof)
    for fold in range(FOLDS):
        train = [i for i, row in enumerate(title_rows)
                 if fold_of[row["pair"]["instance_id"]] != fold]
        test = [i for i, row in enumerate(title_rows)
                if fold_of[row["pair"]["instance_id"]] == fold]
        fold_calibrator = SigmoidCalibrator().fit(
            [oof[i] for i in train], [labels[i] for i in train])
        for index in test:
            crossfit[index] = float(fold_calibrator.predict([oof[index]])[0])
    crossfit_brier = brier_score_loss(labels, crossfit)

    ordered = sorted(oof)
    low_cut = ordered[int(0.70 * (len(ordered) - 1))]
    high_cut = ordered[int(0.90 * (len(ordered) - 1))]
    bands = _band_stats(oof, labels, low_cut, high_cut)

    features = [_features(row["pair"], row["tree_files"]) for row in title_rows]
    model, vectorizer = fit(features, labels)

    strict = _load(STRICT_RESULTS)
    issue_rows = []
    for row in strict["per_pair"]:
        pair = pairs[row["instance_id"]]
        if pair.get("issue_source_a") != "body" or pair.get("issue_source_b") != "body":
            continue
        issue_rows.append({"pair": pair, "tree_files": row.get("tree_files", 0)})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        transfer = _transfer(title_rows, issue_rows)
        forward = _forward(title_rows, labels)

    metrics = {
        "pairs": len(title_rows),
        "conflicts": sum(labels),
        "prevalence": sum(labels) / len(labels),
        "repositories": len({row["pair"]["repo"] for row in title_rows}),
        "validation": {"scheme": "repository-grouped 5-fold", "folds": FOLDS, "seed": SEED},
        "average_precision": raw_ap,
        "roc_auc": raw_auc,
        "brier_raw": brier_score_loss(labels, oof),
        "brier_calibrated": brier_score_loss(labels, calibrated),
        "brier_calibrated_crossfit": crossfit_brier,
        "brier_constant_baseline": (sum(labels) / len(labels))
                                       * (1 - sum(labels) / len(labels)),
        "budgets": {str(f): _budget(oof, labels, f) for f in (0.1, 0.2, 0.3)},
        "bands": bands,
        "band_thresholds": {"low_cut": low_cut, "high_cut": high_cut},
        "forward_time": forward,
        "issue_text_transfer": transfer,
    }
    metadata = {
        "version": "collisionguard-v0.2",
        "trained_on": "652 natural co-active AI-agent PR pairs (PR titles and repository metadata)",
        "table_sha256": table["table_sha256"],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "bands": {
            "low": {"rate": bands["low"]["rate"], "pairs": bands["low"]["pairs"],
                    "conflicts": bands["low"]["conflicts"]},
            "elevated": {"rate": bands["elevated"]["rate"],
                         "pairs": bands["elevated"]["pairs"],
                         "conflicts": bands["elevated"]["conflicts"]},
            "high": {"rate": bands["high"]["rate"], "pairs": bands["high"]["pairs"],
                     "conflicts": bands["high"]["conflicts"]},
        },
        "features": "task type words, language, repository size, same-agent flag, task lengths",
        "algorithm": ("equal-weight average of raw probabilities from a class-balanced "
                      "logistic regression and an 800-tree extremely randomized forest"),
        "caveat": ("Retrospective, weak triage. PR titles are outcome-adjacent; "
                   "the issue-text transfer is the closer pre-start check and is weaker."),
    }
    save_artifact(MODEL_OUT, model, vectorizer, calibrator, oof, metrics, metadata)
    PUBLIC_OUT.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUT.write_text(json.dumps(
        {"metrics": metrics, "metadata": metadata}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"trained on {metrics['pairs']} pairs ({metrics['conflicts']} conflicts, "
          f"prevalence {metrics['prevalence']:.3f})")
    print(f"AP {raw_ap:.3f}  AUC {raw_auc:.3f}  Brier {metrics['brier_raw']:.3f} "
          f"-> {metrics['brier_calibrated']:.3f}")
    for name, band in bands.items():
        print(f"band {name:8} n={band['pairs']:3} conflicts={band['conflicts']:3} "
              f"rate={band['rate']:.3f}")
    for fraction, budget in metrics["budgets"].items():
        print(f"top {fraction:>4} recall={budget['recall']:.3f} "
              f"precision={budget['precision']:.3f} lift={budget['lift']:.2f}")
    print(f"forward-time AUC {forward['roc_auc']:.3f} "
          f"(n={forward['test_pairs']}, conflicts={forward['conflicts']})")
    print(f"issue-title transfer AUC {transfer['roc_auc']:.3f} "
          f"(n={transfer['test_pairs']}, conflicts={transfer['conflicts']})")
    print(f"wrote {MODEL_OUT.relative_to(ROOT)} and {PUBLIC_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
