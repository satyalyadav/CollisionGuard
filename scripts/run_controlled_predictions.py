"""Run the existing baselines on the ten constructed pairs.

This is a workflow check, not an accuracy result. Ten pairs across ten
repositories, with seven conflicts, cannot establish generalization. The runner
uses the same leave-one-repository-out folds and the same models as the public
twelve-pair demonstration.

    python3 scripts/run_controlled_predictions.py
"""

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from baselines import TfidfBaseline
from build_controlled_prediction import verify_table
from evaltools import splits
from evaltools.report import evaluate, format_report, prevalence_scores
from evaltools.schema import normalize_records
from run_baselines import _folds, run_logistic_baseline, run_tfidf_baseline

TABLE = ROOT / "data/private/research/controlled-prediction-10/table.json"
PUBLIC_OUT = ROOT / "data/controlled-prediction-10/results.json"
PROTOCOL_VERSION = "controlled-prediction-results-1"
PATH_RE = re.compile(
    r"`?[A-Za-z0-9_./-]+\.(?:py|rst|md|txt|toml|cfg|ini|yaml|yml)(?![\w.])`?")


def _load(path):
    if not path.is_file():
        raise ValueError(f"missing table: {path}; run scripts/build_controlled_prediction.py")
    table = json.loads(path.read_text(encoding="utf-8"))
    verify_table(table)
    return table


def _records(table):
    rows = []
    for pair in table["pairs"]:
        rows.append({
            "instance_id": pair["instance_id"],
            "repo": pair["repo"],
            "label": pair["label"],
            "task_a": pair["task_a"],
            "task_b": pair["task_b"],
        })
    return normalize_records(rows)


def _audit_folds(records):
    count = 0
    for train, test in _folds([(record["repo"], record["repo"]) for record in records]):
        if train and test:
            splits.assert_no_leakage(splits.take(records, train), splits.take(records, test))
            count += 1
    return count


def _fold_priors(records):
    scores = [None] * len(records)
    for train, test in _folds([(record["repo"], record["repo"]) for record in records]):
        for index, score in zip(test, prevalence_scores(splits.take(records, train),
                                                        splits.take(records, test))):
            scores[index] = score
    return scores


def _strip_paths(text):
    """Remove explicit file paths so similarity cannot read the named target."""
    return PATH_RE.sub(" ", text)


def _tfidf_scores(pairs, repos):
    scores = [None] * len(pairs)
    for train, test in _folds(repos):
        model = TfidfBaseline().fit([text for index in train for text in pairs[index]])
        for index in test:
            scores[index] = model.predict_score(*pairs[index])
    return scores


def _json_safe(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _evaluate(name, records, scores, calibrated):
    result = evaluate(records, scores, n_boot=500, calibrated=calibrated)
    print("\n" + format_report(result, name))
    return result


def build_results(table, source=None):
    records = _records(table)
    # normalize_records stores hashed task ids, so the models read the table text.
    pairs = [(pair["task_a"], pair["task_b"]) for pair in table["pairs"]]
    labels = [record["label"] for record in records]
    repos = [(record["repo"], record["repo"]) for record in records]
    ids = [record["instance_id"] for record in records]

    print(f"Data source: {source or TABLE.relative_to(ROOT)}")
    print(f"pairs {len(records)}, positives {sum(labels)}, "
          f"repositories {len({record['repo'] for record in records})}")
    folds = _audit_folds(records)
    print(f"Leakage audit passed for {folds} leave-one-repository-out folds.")
    print("Demo only: ten constructed pairs do not establish prediction accuracy.")

    base_rate = _fold_priors(records)
    tfidf = run_tfidf_baseline(pairs, labels, repos, ids)
    stripped = [(_strip_paths(a), _strip_paths(b)) for a, b in pairs]
    tfidf_stripped = _tfidf_scores(stripped, repos)
    logistic = run_logistic_baseline(pairs, labels, repos, ids)
    no_skill_ap = sum(labels) / len(labels)

    results = {
        "protocol_version": PROTOCOL_VERSION,
        "table_sha256": table["table_sha256"],
        "pairs": len(records),
        "clean": labels.count(0),
        "conflict": labels.count(1),
        "repositories": len({record["repo"] for record in records}),
        "no_skill_ap": no_skill_ap,
        "leakage_audit": {"folds": folds, "passed": True},
        "models": {
            "fold_prior_reference": _evaluate(
                "fold prior (probability reference)", records, base_rate, True),
            "tfidf_cosine": _evaluate("TF-IDF cosine", records, tfidf, False),
            "tfidf_cosine_paths_removed": _evaluate(
                "TF-IDF cosine, file paths removed", records, tfidf_stripped, False),
            "logistic_regression": _evaluate("logistic regression", records, logistic, True),
        },
        "scores": [
            {
                "instance_id": record["instance_id"],
                "cohort": table["pairs"][index]["cohort"],
                "repo": record["repo"],
                "label": record["label"],
                "fold_prior": base_rate[index],
                "tfidf": tfidf[index],
                "tfidf_paths_removed": tfidf_stripped[index],
                "logistic": logistic[index],
            }
            for index, record in enumerate(records)
        ],
        "caveats": [
            "Ten constructed pairs across ten repositories, with seven conflicts.",
            "Both tasks in every pair were designed to touch the same module.",
            "The task text names the module and test file, so lexical similarity partly restates the construction.",
            "The two cohorts use different capture policies and are not a random sample.",
            "The fold-prior reference assigns one constant per class, so its pooled AP equals prevalence; use no_skill_ap as the no-skill reference.",
            "These scores check the workflow and support no accuracy or held-out claim.",
        ],
    }
    return _json_safe(results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=PUBLIC_OUT)
    args = parser.parse_args(argv)

    table = _load(args.table)
    results = build_results(table, source=args.table)
    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
