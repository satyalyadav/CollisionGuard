"""Combine natural-cohort text and file results into one analysis table.

Reads the public result files, joins pair metadata by instance id, and reports
the same metrics on pre-declared subsets: same-agent vs cross-agent, dissimilar
titles, and excluding pairs that link the same issue. Task text is never read;
the metadata needed for the subsets is in the private table.

    python3 scripts/analyze_natural_cohort.py
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evaltools.metrics import average_precision
from sklearn.metrics import roc_auc_score

PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
PUBLIC = ROOT / "data/natural-cohort-2026-11"
TABLE = PRIVATE / "table.json"
OUT = PUBLIC / "analysis.json"
VARIANTS = ("title", "title_body", "issue_title", "issue_title_body")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _title_similarity(pair):
    first, second = _tokens(pair["title_a"]), _tokens(pair["title_b"])
    union = first | second
    return len(first & second) / len(union) if union else 1.0


def _strict_issue(pair):
    """Both PRs close a linked issue created before their own PR opened."""
    if pair.get("issue_source_a") != "body" or pair.get("issue_source_b") != "body":
        return False
    times = (pair.get("issue_created_a"), pair.get("issue_created_b"),
             pair.get("created_a"), pair.get("created_b"))
    if any(value is None for value in times):
        return False
    return times[0] < times[2] and times[1] < times[3]


def _early_issue(pair):
    """True when both linked issues predate the first PR opening."""
    times = (pair.get("issue_created_a"), pair.get("issue_created_b"),
             pair.get("created_a"), pair.get("created_b"))
    if any(value is None for value in times):
        return False
    first_pr = min(times[2], times[3])
    return times[0] < first_pr and times[1] < first_pr


def _label(value):
    if isinstance(value, str):
        return 1 if value.strip().lower() == "conflict" else 0
    return int(value)


def _metrics(rows, score_key):
    labels = [_label(row["label"]) for row in rows]
    scores = [row[score_key] for row in rows]
    if not rows or len(set(labels)) < 2:
        return None
    return {
        "pairs": len(rows),
        "conflicts": sum(labels),
        "prevalence": sum(labels) / len(labels),
        "average_precision": average_precision(labels, scores),
        "roc_auc": roc_auc_score(labels, scores),
    }


def _subsets(rows):
    return {
        "all": rows,
        "early_issue": [row for row in rows if row["early_issue"]],
        "strict_issue": [row for row in rows if row["strict_issue"]],
        "same_agent": [row for row in rows if row["stratum"] == "same"],
        "cross_agent": [row for row in rows if row["stratum"] == "cross"],
        "titles_dissimilar": [row for row in rows if row["title_similarity"] < 0.5],
        "different_linked_issue": [row for row in rows if not row["same_issue"]],
        "dissimilar_and_different_issue": [
            row for row in rows
            if row["title_similarity"] < 0.5 and not row["same_issue"]
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=TABLE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    table = _load(args.table)
    pairs = {pair["instance_id"]: pair for pair in table["pairs"]}
    analysis = {
        "table_sha256": table["table_sha256"],
        "text": {},
        "file": None,
        "caveats": [
            "Subsets are sensitivity checks, not separate pre-registered cohorts.",
            "Title similarity is computed from the task text and is therefore a predictor feature.",
            "The file analysis covers only pairs with a fetched tree and both PRs.",
        ],
    }

    for variant in VARIANTS:
        path = PUBLIC / f"results-{variant}.json"
        if not path.is_file():
            continue
        results = _load(path)
        if results.get("table_sha256") != table["table_sha256"]:
            raise ValueError(f"{variant}: results belong to a different table")
        rows = []
        for score in results["scores"]:
            pair = pairs[score["instance_id"]]
            rows.append({
                "instance_id": score["instance_id"],
                "repo": score["repo"],
                "label": score["label"],
                "stratum": pair["stratum"],
                "language": pair.get("language"),
                "title_similarity": _title_similarity(pair),
                "same_issue": bool(pair["issue_number_a"]
                                   and pair["issue_number_a"] == pair["issue_number_b"]),
                "early_issue": _early_issue(pair),
                "strict_issue": _strict_issue(pair),
                "tfidf": score["tfidf"],
                "logistic": score["logistic"],
            })
        entry = {"pairs": len(rows),
                 "early_issue_pairs": sum(1 for row in rows if row["early_issue"]),
                 "strict_issue_pairs": sum(1 for row in rows if row["strict_issue"]),
                 "models": {}}
        for model in ("tfidf", "logistic"):
            entry["models"][model] = {
                name: _metrics(subset, model)
                for name, subset in _subsets(rows).items()
            }
        analysis["text"][variant] = entry

    file_path = PUBLIC / "file-predictor.json"
    if file_path.is_file():
        file_results = _load(file_path)
        if file_results.get("table_sha256") not in (None, table["table_sha256"]):
            raise ValueError("file results belong to a different table")
        rows = []
        for row in file_results["per_pair"]:
            pair = pairs[row["instance_id"]]
            item = dict(row)
            item["stratum"] = pair["stratum"]
            item["title_similarity"] = _title_similarity(pair)
            item["same_issue"] = bool(pair["issue_number_a"]
                                      and pair["issue_number_a"] == pair["issue_number_b"])
            item["early_issue"] = _early_issue(pair)
            item["strict_issue"] = _strict_issue(pair)
            rows.append(item)
        by_repo = {}
        for row in rows:
            by_repo.setdefault(row["repo"], []).append(row)
        one_per_repo = [min(group, key=lambda row: (row["pr_a"], row["pr_b"]))
                        for group in by_repo.values()]
        models = {
            key: {
                name: _metrics(subset, key)
                for name, subset in _subsets(rows).items()
            }
            for key in ("text_score", "predicted_overlap", "directory_overlap",
                        "actual_overlap", "nonzero_overlap", "random_overlap",
                        "blend_equal", "blend_text_heavy")
        }
        models["one_per_repo"] = {
            key: _metrics(one_per_repo, key)
            for key in ("text_score", "predicted_overlap", "actual_overlap",
                        "blend_equal")
        }
        analysis["file"] = {"pairs": len(one_per_repo), "models": models}

    strict_path = PUBLIC / "file-predictor-strict-issue.json"
    if strict_path.is_file():
        strict = _load(strict_path)
        rows = []
        for row in strict["per_pair"]:
            pair = pairs[row["instance_id"]]
            item = dict(row)
            item["stratum"] = pair["stratum"]
            item["title_similarity"] = _title_similarity(pair)
            item["same_issue"] = bool(pair["issue_number_a"]
                                      and pair["issue_number_a"] == pair["issue_number_b"])
            item["early_issue"] = _early_issue(pair)
            item["strict_issue"] = _strict_issue(pair)
            rows.append(item)
        analysis["file_strict_issue"] = {
            "pairs": len(rows),
            "models": {
                key: {
                    name: _metrics(subset, key)
                    for name, subset in _subsets(rows).items()
                }
                for key in ("text_score", "predicted_overlap", "directory_overlap",
                            "actual_overlap", "nonzero_overlap", "random_overlap",
                            "blend_equal", "blend_text_heavy")
            },
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}")
    for variant, entry in analysis["text"].items():
        models = entry["models"]
        tfidf = models["tfidf"]["all"]
        logistic = models["logistic"]["all"]
        print(f"  {variant:<18} n={entry['pairs']:<4} "
              f"early-issue {entry['early_issue_pairs']:<4} "
              f"strict-issue {entry['strict_issue_pairs']:<4} "
              f"tfidf AUC {tfidf['roc_auc']:.3f}  logistic AUC {logistic['roc_auc']:.3f}")
    for label, key in (("file", "file"), ("file strict", "file_strict_issue")):
        entry = analysis.get(key)
        if not entry:
            continue
        for model, models in entry["models"].items():
            value = models.get("all")
            if value:
                print(f"  {label} {model:<20} n={value['pairs']} "
                      f"AP {value['average_precision']:.3f} AUC {value['roc_auc']:.3f}")


if __name__ == "__main__":
    main()
