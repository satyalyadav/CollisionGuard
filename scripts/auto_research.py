"""Bounded auto-research loop for the product model.

Tuning uses folds 0-3 only. Fold 4 is scored once, after a config is selected.
The keep rule requires at least a 0.01 mean average-precision gain over the
baseline and a positive gain in at least three of the four folds.

    python3 scripts/auto_research.py
    python3 scripts/auto_research.py --out data/private/research/product-2026-11/auto-research.jsonl
"""

import argparse
import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from collisionguard.features import pair_features
from evaltools.metrics import average_precision
from run_natural_predictions import _canonical_fold_map

TABLE = ROOT / "data/private/research/natural-cohort-2026-11/table.json"
FILE_RESULTS = ROOT / "data/natural-cohort-2026-11/file-predictor.json"
OUT = ROOT / "data/private/research/product-2026-11/auto-research.jsonl"
BASELINE = "type_logistic_0.5"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _features(pair, tree_files, groups):
    base = pair_features(pair["title_a"], pair["title_b"],
                         language=pair.get("language"),
                         tree_files=tree_files,
                         same_agent=pair["stratum"] == "same",
                         agent_a=pair.get("agent_a"),
                         agent_b=pair.get("agent_b"))
    if groups == "type":
        return {key: value for key, value in base.items()
                if key.startswith(("type_", "both_", "la", "lb"))}
    if groups == "type_repo":
        return {key: value for key, value in base.items() if key != "same"}
    return base


def _model(name, c):
    if name == "logistic":
        return make_pipeline(StandardScaler(),
                             LogisticRegression(class_weight="balanced",
                                                max_iter=2000, C=c))
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.06,
                                          max_leaf_nodes=15, l2_regularization=1.0,
                                          random_state=0)


def _fit_predict(train_x, train_y, test_x, name, c):
    vectorizer = DictVectorizer(sparse=False)
    matrix = vectorizer.fit_transform(train_x)
    model = _model(name, c)
    model.fit(matrix, train_y)
    return [float(value) for value in
            model.predict_proba(vectorizer.transform(test_x))[:, 1]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    table = _load(TABLE)
    file_results = _load(FILE_RESULTS)
    pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
    rows = []
    for row in file_results["per_pair"]:
        pair = pairs[row["instance_id"]]
        if pair["title_a"].strip().casefold() == pair["title_b"].strip().casefold():
            continue
        rows.append({"pair": pair, "tree_files": row.get("tree_files", 0)})
    labels = [1 if row["pair"]["label"] == "conflict" else 0 for row in rows]
    fold_of = _canonical_fold_map(table)
    folds = [fold_of[row["pair"]["instance_id"]] for row in rows]

    configs = [
        (BASELINE, "logistic", 0.5, "type"),
        ("type_logistic_0.1", "logistic", 0.1, "type"),
        ("type_logistic_1.0", "logistic", 1.0, "type"),
        ("type_same_logistic_0.5", "logistic", 0.5, "full"),
        ("type_repo_logistic_0.5", "logistic", 0.5, "type_repo"),
        ("type_hgb", "hgb", 0.0, "type"),
        ("type_repo_hgb", "hgb", 0.0, "type_repo"),
    ]

    results = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, model_name, c, groups in configs:
            fold_scores = []
            for fold in range(4):
                train = [i for i, value in enumerate(folds) if value != fold]
                test = [i for i, value in enumerate(folds) if value == fold]
                train_x = [_features(rows[i]["pair"], rows[i]["tree_files"], groups)
                           for i in train]
                test_x = [_features(rows[i]["pair"], rows[i]["tree_files"], groups)
                          for i in test]
                scores = _fit_predict(train_x, [labels[i] for i in train],
                                      test_x, model_name, c)
                if len(set(labels[i] for i in test)) < 2:
                    continue
                fold_scores.append({
                    "fold": fold,
                    "average_precision": average_precision(
                        [labels[i] for i in test], scores),
                    "roc_auc": roc_auc_score([labels[i] for i in test], scores),
                })
            mean_ap = float(np.mean([item["average_precision"] for item in fold_scores]))
            mean_auc = float(np.mean([item["roc_auc"] for item in fold_scores]))
            results.append({"name": name, "model": model_name, "C": c,
                            "groups": groups, "folds": fold_scores,
                            "mean_average_precision": mean_ap,
                            "mean_roc_auc": mean_auc})
            print(f"{name:26} AP {mean_ap:.3f} AUC {mean_auc:.3f}", flush=True)

        baseline = next(item for item in results if item["name"] == BASELINE)
        eligible = []
        for item in results:
            gains = [fold["average_precision"] - base["average_precision"]
                     for fold, base in zip(item["folds"], baseline["folds"])]
            item["gains"] = gains
            if (item is not baseline
                    and item["mean_average_precision"] - baseline["mean_average_precision"] >= 0.01
                    and sum(1 for gain in gains if gain > 0) >= 3):
                eligible.append(item)
        selected = max(eligible, key=lambda item: item["mean_average_precision"]) \
            if eligible else baseline

        selected_features = [_features(row["pair"], row["tree_files"], selected["groups"])
                             for row in rows]
        test = [i for i, value in enumerate(folds) if value == 4]
        train = [i for i, value in enumerate(folds) if value != 4]
        test_scores = _fit_predict([selected_features[i] for i in train],
                                   [labels[i] for i in train],
                                   [selected_features[i] for i in test],
                                   selected["model"], selected["C"])
        final = {
            "fold": 4,
            "average_precision": average_precision([labels[i] for i in test], test_scores),
            "roc_auc": roc_auc_score([labels[i] for i in test], test_scores),
        }

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline": BASELINE,
        "selected": selected["name"],
        "configs": results,
        "fold4": final,
        "note": "Fold 4 was inspected in earlier exploratory runs; treat it as a check, not a sealed test.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"selected {selected['name']}; fold 4 AP {final['average_precision']:.3f} "
          f"AUC {final['roc_auc']:.3f}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
