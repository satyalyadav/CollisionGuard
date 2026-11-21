"""Run the text-only baselines on the natural-mix cohort.

The cohort is 673 real co-active AI-agent PR pairs from the CC-BY replication
package, joined to AIDev task text. Outcomes were not designed by this project.
This runner uses repository-grouped 5-fold cross-validation and reports one
out-of-fold score per pair.

    python3 scripts/run_natural_predictions.py --text title
    python3 scripts/run_natural_predictions.py --text issue_title_body

Text variants:
- title: PR titles only. Least leaky variant available for every pair.
- title_body: PR title and body. Bodies often name changed files; upper bound.
- issue_title: linked issue titles, both sides required. Closest to pre-start.
- issue_title_body: linked issue text, both sides required.

No variant establishes the strict pre-start claim: PR text is written when the
PR opens, after coding has started. Issue text is created before coding but is
only a proxy for the agent's actual instructions.
"""

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from baselines import LogisticRegressionBaseline, TfidfBaseline
from sklearn.metrics import roc_auc_score
from build_natural_cohort import verify_table
from evaltools import splits
from evaltools.report import evaluate
from evaltools.schema import normalize_records

TABLE = ROOT / "data/private/research/natural-cohort-2026-11/table.json"
PUBLIC_DIR = ROOT / "data/natural-cohort-2026-11"
PROTOCOL_VERSION = "natural-cohort-results-1"
N_SPLITS = 5
SEED = 0

VARIANTS = ("title", "title_body", "issue_title", "issue_title_body")


def _load(path):
    if not path.is_file():
        raise ValueError(f"missing table: {path}; run scripts/build_natural_cohort.py")
    table = json.loads(path.read_text(encoding="utf-8"))
    verify_table(table)
    return table


def _text(pair, variant):
    if variant == "title":
        return pair["title_a"], pair["title_b"]
    if variant == "title_body":
        return (pair["title_a"] + "\n\n" + (pair.get("body_a") or "")).strip(), \
               (pair["title_b"] + "\n\n" + (pair.get("body_b") or "")).strip()
    if variant == "issue_title":
        return pair.get("issue_title_a") or "", pair.get("issue_title_b") or ""
    if variant == "issue_title_body":
        a, b = pair.get("issue_title_a"), pair.get("issue_title_b")
        if not a or not b:
            return "", ""
        return (a + "\n\n" + (pair.get("issue_body_a") or "")).strip(), \
               (b + "\n\n" + (pair.get("issue_body_b") or "")).strip()
    raise ValueError(f"unknown text variant: {variant}")


def _eligible(table, variant):
    pairs, excluded_identical = [], 0
    for pair in table["pairs"]:
        a, b = _text(pair, variant)
        if not a or not b:
            continue
        if a.strip().casefold() == b.strip().casefold():
            excluded_identical += 1
            continue
        row = dict(pair)
        row["task_a"], row["task_b"] = a, b
        pairs.append(row)
    return pairs, excluded_identical


def _records(pairs):
    rows = [{
        "instance_id": pair["instance_id"],
        "repo": pair["repo"],
        "label": pair["label"],
        "task_a": pair["task_a"],
        "task_b": pair["task_b"],
        "family": None,
        "time": None,
    } for pair in pairs]
    return normalize_records(rows)


def _folds(records):
    return splits.group_kfold(records, n_splits=N_SPLITS, seed=SEED)


def _canonical_fold_map(table):
    """Assign every pair, including identical-title pairs, to one shared fold.

    All variants reuse this map so the same repository stays in the same fold
    even when a variant adds a pair the title variant excludes.
    """
    records = [{
        "instance_id": pair["instance_id"],
        "repo": pair["repo"],
        "task_a": pair["title_a"],
        "task_b": pair["title_b"],
        "family": None,
    } for pair in table["pairs"]]
    mapping = {}
    for fold, (_, test) in enumerate(splits.group_kfold(records, N_SPLITS, SEED)):
        for index in test:
            mapping[records[index]["instance_id"]] = fold
    if len(mapping) != len(table["pairs"]):
        raise ValueError("canonical fold map does not cover every pair")
    return mapping


def _fold_prior(records, folds):
    scores = [None] * len(records)
    for train, test in folds:
        rate = sum(records[i]["label"] for i in train) / len(train)
        for i in test:
            scores[i] = rate
    return scores


def _tfidf(records, pairs, folds):
    scores = [None] * len(records)
    for train, test in folds:
        model = TfidfBaseline().fit([text for i in train for text in pairs[i]])
        for i in test:
            scores[i] = model.predict_score(*pairs[i])
    return scores


def _logistic(records, pairs, folds):
    scores = [None] * len(records)
    for train, test in folds:
        model = LogisticRegressionBaseline().fit(
            [pairs[i] for i in train],
            [records[i]["label"] for i in train],
            [(records[i]["repo"], records[i]["repo"]) for i in train],
        )
        for i in test:
            scores[i] = model.predict_proba(
                *pairs[i], records[i]["repo"], records[i]["repo"])
    return scores


def _summary(name, records, scores):
    result = evaluate(records, scores, n_boot=1000, calibrated=(name == "logistic"))
    return {
        "n": result["n"],
        "positives": result["positives"],
        "prevalence": result["prevalence"],
        "repositories": result["n_repos"],
        "average_precision": result["average_precision"],
        "ap_interval": result["ap_interval"],
        "pr_auc_trapezoid": result["pr_auc_trapezoid"],
        "roc_auc": roc_auc_score([record["label"] for record in records], scores),
        "precision_at_recall_0_5": result["precision_at_recall"]["precision"],
        "recall_at_top_20pct": result["recall_at_budget"]["recall"],
    }


def _fmt(value):
    return "n/a" if value is None else f"{value:.3f}"


def _print_model(name, summary):
    ci = summary["ap_interval"]
    print(f"  {name:<14} AP {_fmt(summary['average_precision'])} "
          f"[{_fmt(ci['low'])}, {_fmt(ci['high'])}]  "
          f"PR-AUC {_fmt(summary['pr_auc_trapezoid'])}  "
          f"AUC {_fmt(summary['roc_auc'])}  "
          f"P@R0.5 {_fmt(summary['precision_at_recall_0_5'])}  "
          f"R@20% {_fmt(summary['recall_at_top_20pct'])}")


def build(table, variant):
    pairs_rows, excluded_identical = _eligible(table, variant)
    if len(pairs_rows) < N_SPLITS:
        raise ValueError(f"variant {variant} leaves only {len(pairs_rows)} pairs")
    records = _records(pairs_rows)
    pairs = [(pair["task_a"], pair["task_b"]) for pair in pairs_rows]
    fold_map = _canonical_fold_map(table)
    missing = [record["instance_id"] for record in records
               if record["instance_id"] not in fold_map]
    if missing:
        raise ValueError(f"{variant}: {len(missing)} pairs have no canonical fold")
    folds = []
    for fold in range(N_SPLITS):
        test = [index for index, record in enumerate(records)
                if fold_map.get(record["instance_id"]) == fold]
        train = [index for index, record in enumerate(records)
                 if fold_map.get(record["instance_id"]) != fold]
        if not test or not train:
            raise ValueError(f"{variant}: fold {fold} is empty after filtering")
        folds.append((train, test))
    for train, test in folds:
        splits.assert_no_leakage(splits.take(records, train), splits.take(records, test))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scores = {
            "fold_prior": _fold_prior(records, folds),
            "tfidf": _tfidf(records, pairs, folds),
            "logistic": _logistic(records, pairs, folds),
        }
        models = {name: _summary(name, records, values)
                  for name, values in scores.items()}

    labels = [record["label"] for record in records]
    return {
        "protocol_version": PROTOCOL_VERSION,
        "table_sha256": table["table_sha256"],
        "variant": variant,
        "validation": {
            "scheme": "repository-grouped k-fold",
            "folds": N_SPLITS,
            "seed": SEED,
            "leakage_audit_passed": True,
        },
        "pairs": len(records),
        "clean": labels.count(0),
        "conflict": labels.count(1),
        "prevalence": sum(labels) / len(labels),
        "repositories": len({record["repo"] for record in records}),
        "excluded_identical_text": excluded_identical,
        "models": models,
        "scores": [
            {
                "instance_id": record["instance_id"],
                "repo": record["repo"],
                "label": record["label"],
                "fold_prior": scores["fold_prior"][i],
                "tfidf": scores["tfidf"][i],
                "logistic": scores["logistic"][i],
            }
            for i, record in enumerate(records)
        ],
        "caveats": [
            "Retrospective co-active PR pairs, not tasks dispatched from a common queue.",
            "PR text is written at PR creation, after coding has started; title only is the least leaky variant.",
            "The issue-text subset is closer to pre-start but is only a proxy for the agent's instructions.",
            "Pairs come from a stratified sample with all cross-agent pairs; prevalence is not a population base rate.",
            "Multiple pairs can share a repository or a PR; folds keep whole repositories together.",
            "Text-only results do not establish prediction accuracy for unseen repositories.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", choices=VARIANTS, default="title")
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    table = _load(args.table)
    results = build(table, args.text)
    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    out = args.out or (PUBLIC_DIR / f"results-{args.text}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"variant {args.text}: {results['pairs']} pairs, "
          f"{results['conflict']} conflicts ({results['prevalence']:.3f}), "
          f"{results['repositories']} repositories")
    for name in ("fold_prior", "tfidf", "logistic"):
        _print_model(name, results["models"][name])
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
