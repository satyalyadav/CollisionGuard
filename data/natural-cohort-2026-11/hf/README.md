---
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
