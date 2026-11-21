"""Export a Hugging Face-ready public view of the natural cohort.

The export contains pair identifiers, labels, metadata and a fixed fold
assignment. It does not contain task text, PR bodies, issue text, diffs or
changed-file paths; those stay in the private table or can be rejoined from
AIDev and the replication package.

    python3 scripts/export_natural_cohort_hf.py
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_natural_predictions import _canonical_fold_map

TABLE = ROOT / "data/private/research/natural-cohort-2026-11/table.json"
OUT_DIR = ROOT / "data/natural-cohort-2026-11/hf"
OUT_CSV = OUT_DIR / "pairs.csv"
OUT_CARD = OUT_DIR / "README.md"
TOKEN = re.compile(r"[a-z0-9]+")

COLUMNS = [
    "pair_id", "repo", "pr_a", "pr_b", "label", "stratum",
    "agent_a", "agent_b", "language", "license", "stars", "is_forked",
    "created_a", "created_b", "title_eligible", "title_similarity",
    "issue_linked", "strict_issue", "conflict_paths", "conflict_types",
    "fold", "split",
]


def _tokens(text):
    return set(TOKEN.findall((text or "").lower()))


def _title_similarity(pair):
    first, second = _tokens(pair["title_a"]), _tokens(pair["title_b"])
    union = first | second
    return round(len(first & second) / len(union), 6) if union else 1.0


def _strict_issue(pair):
    if pair.get("issue_source_a") != "body" or pair.get("issue_source_b") != "body":
        return False
    times = (pair.get("issue_created_a"), pair.get("issue_created_b"),
             pair.get("created_a"), pair.get("created_b"))
    if any(value is None for value in times):
        return False
    return times[0] < times[2] and times[1] < times[3]


def _split(fold):
    if fold == 4:
        return "test"
    if fold == 3:
        return "validation"
    return "train"


def main():
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    fold_map = _canonical_fold_map(table)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for pair in table["pairs"]:
            fold = fold_map[pair["instance_id"]]
            writer.writerow({
                "pair_id": pair["instance_id"],
                "repo": pair["repo"],
                "pr_a": pair["pr_a"],
                "pr_b": pair["pr_b"],
                "label": pair["label"],
                "stratum": pair["stratum"],
                "agent_a": pair.get("agent_a") or "",
                "agent_b": pair.get("agent_b") or "",
                "language": pair.get("language") or "",
                "license": pair.get("license") or "",
                "stars": pair.get("stars") if pair.get("stars") is not None else "",
                "is_forked": pair.get("is_forked"),
                "created_a": pair.get("created_a") or "",
                "created_b": pair.get("created_b") or "",
                "title_eligible": pair["title_a"].strip().casefold() != pair["title_b"].strip().casefold(),
                "title_similarity": _title_similarity(pair),
                "issue_linked": bool(pair.get("issue_title_a") and pair.get("issue_title_b")),
                "strict_issue": _strict_issue(pair),
                "conflict_paths": len(pair.get("conflict_paths") or []),
                "conflict_types": len(pair.get("conflict_types") or []),
                "fold": fold,
                "split": _split(fold),
            })
    OUT_CARD.write_text(CARD, encoding="utf-8")
    print(f"wrote {OUT_CSV.relative_to(ROOT)} ({len(table['pairs'])} rows)")
    print(f"wrote {OUT_CARD.relative_to(ROOT)}")


CARD = """---
license: cc-by-4.0
task_categories:
  - text-classification
language:
  - en
tags:
  - merge-conflict
  - coding-agents
  - software-engineering
  - repository-level
pretty_name: CollisionGuard Natural Cohort
---

# CollisionGuard natural cohort

Retrospective benchmark for predicting whether two AI coding tasks will produce
a textual Git merge conflict. The pairs are real co-active agent pull requests;
this project did not design their outcomes.

## Source

- Pair list and labels: `rq3_merge_replay_full.csv` from the replication package
  for *Concurrent AI-Agent Pull Requests on GitHub*, Zenodo
  [10.5281/zenodo.21186464](https://doi.org/10.5281/zenodo.21186464), CC-BY-4.0.
- Task text and repository metadata: `hao-li/AIDev`, CC-BY-4.0. Task text is
  **not** included here. Join on `repo` and PR number, or use the AIDev
  `pull_request`, `issue`, `related_issue` and `repository` tables.
- Labels are three-way `git merge-tree` replays of the two PR final heads over
  their merge base. They are not prospective task runs.

## Files

`pairs.csv` has one row per pair:

| column | meaning |
| --- | --- |
| `pair_id` | stable identifier |
| `repo`, `pr_a`, `pr_b` | GitHub repository and PR numbers |
| `label` | `clean` or `conflict` |
| `stratum` | `same` or `cross` agent |
| `agent_a`, `agent_b` | agent names from AIDev |
| `language`, `license`, `stars`, `is_forked` | repository metadata |
| `created_a`, `created_b` | PR creation timestamps |
| `title_eligible` | both PR titles are non-empty and differ |
| `title_similarity` | Jaccard similarity of the two title token sets |
| `issue_linked` | both PRs link an issue in AIDev |
| `strict_issue` | both PRs close a body-linked issue created before their own PR |
| `conflict_paths`, `conflict_types` | counts only; paths come from the source package |
| `fold` | repository-grouped fold 0-4 |
| `split` | fold 4 = test, fold 3 = validation, folds 0-2 = train |

## Cohort size

673 pairs across 616 repositories, 518 clean and 155 conflict. 666 pairs have
distinct PR titles. 182 pairs are strict-issue pairs. Some repositories
contribute more than one pair, so whole repositories are kept in one fold.

## Intended use

Baselines for pre-start conflict prediction, repository-disjoint validation,
and comparison with the constructed cohorts in the CollisionGuard repository.
The benchmark is retrospective and selected. It is not a population base rate
and it does not establish that rescheduling tasks reduces conflicts.

## Citation

CollisionGuard project, 2026. Include the Zenodo DOI above for the source
package. See the project repository for the protocol and results.
"""

if __name__ == "__main__":
    main()
