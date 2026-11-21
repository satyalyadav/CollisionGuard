# Natural-mix cohort protocol

This protocol covers the first cohort whose merge outcomes this project did not design. It is a retrospective benchmark built from real pairs of AI-agent pull requests that were open at the same time in the same repository. The pair list and labels come from a public CC-BY replication package; task text and repository metadata come from AIDev.

The protocol fixes the cohort definition, text variants, validation scheme and metrics before repository trees are fetched and before the file predictor is scored. It does not fix any result.

## Why this cohort

Every earlier cohort was constructed by this project. Both tasks in a pair were written to touch the same module, so the conflict rate and the text score partly measure that construction. The natural cohort removes that choice: the tasks were authored by other people and agents, and the outcomes include both clean merges and conflicts at their observed mix.

The cohort is still retrospective. It does not prove that the text was available before either agent started coding. It is the strongest natural-mix benchmark available from public data without replaying every task from a frozen prompt.

## Source

- Pair list and labels: `rq3_merge_replay_full.csv` from the replication package for *Concurrent AI-Agent Pull Requests on GitHub*, Zenodo DOI `10.5281/zenodo.21186464`, license CC-BY-4.0 (confirmed through the Zenodo record API; the GitHub mirror has no LICENSE file). File SHA-256 `a6a3f3e88f6b8445a07d5b43bb8c6d4583cfffb33bd25f650a766a096baaef3c`.
- Task text and repository metadata: `hao-li/AIDev`, retrieved 2026-11-21, license CC-BY-4.0. Tables `pull_request`, `issue`, `related_issue` and `repository`. Per-file hashes are in the private table and the public summary.
- Repository trees and changed-file lists: GitHub REST API at the pair's common base commit, fetched after this protocol was written.
- Local join: `scripts/build_natural_cohort.py`. The joined table stays under the ignored private root because it contains task text.

The source package reports 747 attempted pairs, 716 evaluable, and 167 conflicts. One pair per repository is claimed in its README; the file contains 656 repositories across 716 evaluable pairs, and some PRs appear in more than one pair. Folds therefore group whole repositories.

## Cohort definition

A pair qualifies when:

1. Its source label is `CLEAN` or `CONFLICT` (not `UNAVAIL_fetch` or `UNAVAIL_nobase`).
2. Both PRs are present in AIDev's pull-request table by repository and number.
3. Both PR titles are non-empty.

The joined cohort has 673 pairs across 616 repositories, with 518 clean and 155 conflict labels (prevalence 0.230). Six hundred and sixty-six pairs remain after dropping seven pairs whose two titles are identical after case-folding; those pairs describe the same task on both sides.

The primary full run uses all 666 title-eligible pairs. A secondary design keeps one pair per repository (610 pairs) to match the source paper's intended sampling unit; it is a sensitivity check, not the primary cohort. Multiple pairs can share a repository or a PR, so repository-grouped folds are mandatory.

Each pair carries the source conflict paths and conflict types for diagnostics. They are not inputs. Issue creation times are stored so an early-issue sensitivity check can drop issues created at or after the first PR opened.

## Text variants

Four variants are evaluated on identical folds:

| variant | text | availability | role |
| --- | --- | --- | --- |
| `title` | PR titles | 666 pairs | primary, least leaky |
| `title_body` | PR title and body | 672 pairs | leaky upper bound; bodies name changed files in about 58 percent of pairs |
| `issue_title` | linked issue titles, both sides required | 183 pairs | closest to pre-start |
| `issue_title_body` | linked issue text, both sides required | 183 pairs | pre-start proxy with context |

PR text is written when the PR opens, after coding has started. Issue text is created before coding, but a linked issue is only a proxy for the agent's instructions. No variant establishes the strict pre-start claim; results must be reported with that limit.

One linked issue is chosen per PR, preferring explicit body links, then the lowest issue id. Pairs with an issue on both sides form the issue subset. Pairs with identical text on both sides are excluded per variant.

The strict-issue subset keeps only pairs where both PRs close a linked issue and each issue was created before its own PR opened. It has 182 pairs (28 conflicts), 174 of them in the title-eligible issue-text run. This is the defensible pre-start proxy; issue bodies can still be edited after creation.

## Repository inputs

For each pair, the fetcher records:

- the true merge base of the two PR head SHAs. An equal target-base SHA is not accepted as a shortcut; five of twenty checked pairs had a different true merge base, so every pair recomputes the base from its heads;
- every blob path in the tree at that commit;
- each PR's changed paths, capped at 300 paths per PR.

The GitHub compare and tree APIs provide the base and tree when they succeed. If the comparison is unavailable (for example HTTP 422 for a very large diff), both PR heads are fetched into a temporary bare repository and the base, tree and changed paths are derived locally with `git merge-base`, `git ls-tree` and `git diff`.

A pair is skipped if the tree is truncated, if either file list is truncated, if either PR or file list is unavailable, or if no common base exists. Skips are reported with reasons. Changed paths that are absent from the base tree are reported as coverage; footprint recall is computed both over all changed paths and over paths present in the tree.

## Validation

- Repository-grouped 5-fold cross-validation, seed 0. Whole repositories stay in one fold, and pairs that share a repository or a PR stay together through the repository grouping.
- One out-of-fold score per pair for every model.
- No tuning on test folds. Top five files is fixed to match the constructed-cohort run. Blend weights are fixed at 0.5/0.5, 0.75/0.25 and 0.25/0.75.

## Models and metrics

Text-only: fold prior, TF-IDF cosine and logistic regression over the existing hand-crafted features.

File predictor: rank each task's text against repository paths, keep the top five, and score the pair by the Jaccard overlap of the two lists. Directory overlap is a secondary measure.

Reported: average precision with a repository-clustered bootstrap interval, trapezoidal PR-AUC, precision at recall 0.5, recall at a 20 percent flag budget, footprint recall at five, conflict-path recall, the overlap-positive rule's confusion counts, and the fixed blends.

The oracle is the Jaccard overlap of the two actual changed-file sets. It bounds what a perfect file predictor could contribute and is not a deployable score.

## Pilot and scale

The pilot is a balanced 80-pair sample, one pair per repository, selected by a fixed seed and stratified by label and language group. Its purpose is to catch pipeline errors and estimate whether file overlap carries any signal. It is not an accuracy result.

The full run uses all 666 title-eligible pairs and is attempted only if the pilot pipeline completes and the labels reproduce on a local sample. It is the only basis for a cohort-level claim, and even it is retrospective and conditional on the source sample. The one-pair-per-repository design (610 pairs) is reported alongside it as a sensitivity check.

## Label verification

Before the full run, at least 20 pilot pairs (ten per label) are replayed locally with the source package's procedure: shallow-fetch both `refs/pull/N/head` refs, find the merge base, and run `git merge-tree --write-tree`. A label reproduces when exit 0 is clean and exit 1 with a conflict report is conflict. Disagreements are reported and the affected pair is excluded from the full run unless the cause is understood.

## Budgets

- Pilot fetch: 80 pairs, under 600 GitHub API calls, under 20 minutes.
- Full fetch: 666 pairs, under 4,000 GitHub API calls, split across runs if the rate limit is reached.
- Local replay: at most 25 pairs, shallow depth 80 with a depth-600 retry, under 3 GiB of temporary disk.

## Limits

- Retrospective co-active PRs are not tasks dispatched from a common queue. The population is selected by agent adoption and by both PRs being opened.
- PR titles and bodies can encode implementation details learned during coding. Issue links extracted from PR bodies also use later information; three selected issues were created at or after their own PR opened and 67 pairs have an issue created at or after the first PR opened. The early-issue sensitivity check drops the latter.
- The source samples the first co-active pair per repository and stratum, so pairs are not independent draws. Attrition is reported by label, stratum and language.
- The source sample oversamples cross-agent pairs; prevalence is not a population base rate.
- PR titles are outcome-adjacent summaries. Issue text is pre-coding but may not be the agent's actual prompt.
- Repository state at the common base is an approximation of the decision-time tree.
- Changed-file lists can be truncated, and rename handling may mismatch conflict paths.
- Text-only and file-overlap results on this cohort remain retrospective until a prospective or strict-timing cohort exists.
