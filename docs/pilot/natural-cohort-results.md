# Natural-mix cohort results

This cohort uses merge outcomes this project did not design. It is built from real pairs of AI-agent pull requests that were open at the same time in the same repository. The pair list and labels come from a public CC-BY replication package; task text comes from AIDev. The design is frozen in the [protocol](natural-cohort-protocol.md).

## Cohort and attrition

| Stage | Pairs | Detail |
| --- | --- | --- |
| Source attempts | 747 | 25 unavailable refs, 6 no merge base |
| Evaluable labels | 716 | 549 clean, 167 conflict |
| Joined to AIDev text | 673 | 616 repositories; 518 clean, 155 conflict |
| Title-eligible | 666 | seven pairs have identical titles |
| Both linked to an issue | 193 | 183 after ten identical issue titles |
| Strict-issue subset | 182 | both PRs close an issue created before their own PR opened |
| Strict-issue, title-eligible | 174 | of the 183 issue-text pairs |

The source claims one pair per repository, but the released file contains 656 repositories across 716 evaluable pairs and some PRs recur; 616 of those repositories join to AIDev text. Fold construction therefore keeps whole repositories together. The source also samples the first co-active pair per repository and stratum, so the pairs are not independent draws and prevalence is not a population base rate.

Task text variants: PR titles (least leaky), PR title and body (about 46 percent of joined PR bodies contain path-like strings against 2.5 percent of titles, so bodies are a leaky upper bound), linked issue titles, and linked issue text. PR text is written when the PR opens, after coding starts. Issue text predates coding but is only a proxy for the agent's instructions.

Labels are merges of the PRs' final heads fetched in July 2026, not their state during co-activity. Later pushes, maintainer fixes and base-branch merges are folded in, and the replay approximates rather than reproduces GitHub's sequential integration.

## Label verification

Twenty pilot pairs, ten per label, were replayed locally with the source procedure: shallow-fetch both `refs/pull/N/head` refs, find the merge base, and run `git merge-tree --write-tree`. All 20 labels reproduced (20/20). One conflict-path set differed from the source row; the conflict label itself agreed.

## Text-only results

Repository-grouped 5-fold cross-validation, one out-of-fold score per pair, 1,000 repository-clustered bootstrap replicates. The same fold assignment is reused across variants.

| Variant | Pairs | Conflicts | Prevalence | TF-IDF AP (95% interval) | TF-IDF AUC | Logistic AP | Logistic AUC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PR titles | 666 | 151 | 0.227 | 0.263 (0.219-0.325) | 0.523 | 0.228 | 0.513 |
| PR title and body | 672 | 154 | 0.229 | 0.263 (0.212-0.331) | 0.508 | 0.275 | 0.575 |
| Issue titles | 183 | 32 | 0.175 | 0.165 (0.116-0.235) | 0.497 | 0.146 | 0.386 |
| Issue title and body | 183 | 32 | 0.175 | 0.190 (0.127-0.280) | 0.555 | 0.290 | 0.597 |

Subset checks:

- PR titles with dissimilar titles (Jaccard below 0.5, 640 pairs): TF-IDF AUC 0.505, logistic AUC 0.499. The small title signal is concentrated in near-duplicate tasks.
- Same-agent stratum (563 pairs): TF-IDF AUC 0.544. Cross-agent stratum (103 pairs, prevalence 0.408): AUC 0.522. The higher cross-agent AP (0.452) tracks its higher prevalence, not better ranking.
- Strict-issue subset (174 pairs, 28 conflicts): issue-text TF-IDF AP 0.167, AUC 0.533; logistic AP 0.284 against 0.161 prevalence, AUC 0.613. This is the defensible pre-start proxy: both PRs close an issue created before their own PR opened. The hand-crafted features show a modest, consistent lift; TF-IDF does not. The interval is wide and issue bodies can be edited after creation.

What this means:

- PR titles alone give essentially no discrimination (AUC 0.523). The constructed cohort's TF-IDF AP of 0.948 does not transfer to natural task text. That score was driven by task wording, the pair construction and a 0.700 conflict prevalence, and the path-stripped run still scored 0.909, so it cannot isolate the contribution of filenames.
- PR bodies add signal (logistic AUC 0.575), but they are written after coding and often name changed files. They are not a pre-start input.
- Linked issue text is the closest pre-start proxy. On the strict subset the hand-crafted features give AP 0.284 against 0.161 prevalence and AUC 0.613; TF-IDF gives no lift. The interval is wide and 174 pairs are few. This is the only text variant that is plausibly better than chance, and it needs replication.
- The honest summary is weak discrimination for the tested text models, not evidence that natural conflict prediction is impossible.

## Pilot file predictor

The pilot is a balanced 80-pair sample, one pair per repository, 79 scorable rows after one truncated tree. Forty conflicts give a 0.506 prevalence, so AP values are not comparable with the full cohort's 0.23 prevalence; the paired difference is the useful number.

| Measure | Value |
| --- | --- |
| Mean footprint recall at 5 | 0.217 |
| Mean conflict-path recall | 0.237 |
| Predicted-overlap AP | 0.577 |
| Predicted-overlap AUC | 0.591 |
| Directory-overlap AP | 0.592 |
| Text-only AP (same rows) | 0.588 |
| Text-only AUC (same rows) | 0.535 |
| Equal blend AP | 0.612 |
| Text-heavy blend AP | 0.610 |
| Path-heavy blend AP | 0.587 |
| Actual-overlap AP (oracle) | 0.714 |
| Actual-overlap AUC (oracle) | 0.758 |

The fixed equal blend gains 0.025 AP over text on the same rows. The paired repository-bootstrap interval is about -0.043 to +0.097, so the pilot does not establish a gain. Path-only overlap does not beat text AP (0.577 against 0.588). A BM25 path ranker scored 0.611 overlap AP with lower recall (0.179); it stays exploratory until confirmed on held-out data.

The oracle is the Jaccard overlap of the two actual changed-file sets. Even perfect overlap knowledge reaches only 0.714 AP and 0.758 AUC, because overlapping files can merge cleanly and some conflicts arise from add/delete or non-overlapping edits. That ceiling limits what any file predictor can add.

## Full-cohort file predictor

The primary full run uses all 666 title-eligible pairs with the title text and the fixed top five. It scored 652 pairs across 598 repositories: four pairs were unavailable, five trees were truncated, and five changed-file lists were truncated. Conflicts are 144 of 652 (prevalence 0.221).

| Measure | Value |
| --- | --- |
| Mean footprint recall at 5 | 0.225 |
| Recall on changed paths present in the tree | 0.246 |
| Mean changed-path coverage | 0.774 |
| Conflict-path coverage | 0.881 |
| Conflict-path recall (union) | 0.177 |
| Conflict-path intersection recall | 0.047 |
| Predicted-overlap AP | 0.258 (0.212-0.314) |
| Predicted-overlap AUC | 0.553 |
| Directory-overlap AP | 0.263 |
| Directory-overlap AUC | 0.555 |
| Nonzero-score overlap AP | 0.261 |
| Random-overlap control AP | 0.231 |
| Random-overlap control AUC | 0.512 |
| Text-only AP | 0.259 |
| Text-only AUC | 0.524 |
| Equal-blend AP | 0.274 |
| Equal-blend AP gain, paired | +0.016 (-0.011 to +0.046) |
| Equal-blend AUC gain, paired | +0.025 (-0.009 to +0.060) |
| Oracle overlap AP | 0.333 |
| Oracle overlap AUC | 0.673 |
| Overlap-positive rule | 47 true positives, 118 false positives, 97 missed conflicts |

By stratum:

| Stratum | Pairs | Conflicts | Text AUC | Overlap AUC | Oracle AUC |
| --- | --- | --- | --- | --- | --- |
| Same-agent | 550 | 103 | 0.543 | 0.573 | 0.721 |
| Cross-agent | 102 | 41 | 0.527 | 0.521 | 0.580 |

Path overlap ranks slightly better than text (AUC 0.553 against 0.524) and the fixed equal blend gains 0.016 AP. Both paired intervals include zero, so the run does not establish that predicted file overlap adds reliable information. The point estimate is consistent with a small gain at most.

The overlap-positive rule is not usable: it flags 165 pairs, of which 118 are clean, and misses 97 of 144 conflicts.

The oracle remains low: perfect knowledge of the two changed-file sets reaches 0.333 AP and 0.673 AUC. Overlapping files often merge cleanly, many conflicts are changelog, lockfile or documentation collisions that the task text never names, and changed-path coverage in the base tree is 77 percent. Intersection recall is 0.047: the predictor almost never names the exact file where both sides conflict.

The path signal is concentrated in same-agent pairs (AUC 0.573, oracle 0.721) and disappears in cross-agent pairs (AUC 0.521, oracle 0.580). That is consistent with the cross-agent stratum containing more near-duplicate tasks, where titles alone already carry what little signal exists.

### Strict-issue file run

The pre-start proxy subset uses issue title and body for both sides, and only pairs where both PRs close a pre-created issue. It scored 165 pairs across 164 repositories, with 24 conflicts (prevalence 0.145).

| Measure | Value |
| --- | --- |
| Mean footprint recall at 5 | 0.176 |
| Predicted-overlap AP | 0.140 (0.096-0.211) |
| Predicted-overlap AUC | 0.463 |
| Directory-overlap AP | 0.137 |
| Directory-overlap AUC | 0.432 |
| Text-only AP | 0.150 |
| Text-only AUC | 0.532 |
| Equal-blend AP | 0.143 |
| Equal-blend AUC | 0.506 |
| Oracle overlap AP | 0.182 |
| Oracle overlap AUC | 0.605 |

On the strict subset, path overlap is below chance (AUC 0.463), text is barely above it (0.532), and the blend does not improve on text. The oracle is also low (0.605 AUC), so even perfect overlap knowledge has little room. This subset gives no support for the central hypothesis. Twenty-four conflicts make this an imprecise null, not a precise zero.

## What the natural cohort shows

- The constructed cohort's 0.948 TF-IDF AP does not transfer. On 666 natural pairs, PR titles give AUC 0.523 and AP 0.263 against 0.227 prevalence. The natural task text is short, and titles alone are essentially uninformative.
- The strict pre-start proxy is weak but not empty for the hand-crafted text model (AUC 0.613 on 174 pairs). TF-IDF on the same text gives no lift. This is the most defensible text result and it needs replication.
- Path-only file prediction finds 22.5 percent of changed files and ranks conflicts slightly better than text (AUC 0.553 against 0.524). The fixed equal blend gains 0.016 AP, but the paired interval includes zero. On the strict subset it is below chance.
- The oracle ceiling is low: 0.333 AP and 0.673 AUC for exact changed-file overlap. Overlapping files often merge cleanly, and many conflicts are changelog, lockfile or documentation collisions that the task text never names.
- The honest reading is a weak or null result for this cohort. The data challenge the model rather than confirm it. That is a useful finding: the constructed benchmark overstated predictability, and file overlap is not a strong proxy for textual conflict in natural agent work.


## Limits

- Retrospective co-active PR pairs are not tasks dispatched from a common queue. Open PRs omit tasks that never produce a PR, and the source's stratified sample raises conflict prevalence: cross-agent pairs are about 16 percent of the source sample against roughly 0.5 percent of all co-active pairs.
- Labels merge final heads at replay time, not the co-active state. A PR that changed after the overlap window can carry a later fix or conflict into the label.
- PR titles and bodies can encode implementation details learned during coding. Three selected issues were created at or after their own PR opened, and 67 pairs have an issue created at or after the first PR opened. The early-issue subset is a sensitivity check, not a clean pre-start cohort.
- Five of twenty checked API trees initially used a target-base shortcut instead of the true merge base. All 108 rows stored with that shortcut were refreshed; 20 of the 108 bases changed. The full run recomputes every base from the heads.
- Changed-file lists come from the PR files API, capped at 300 paths per PR, and can include paths relative to a different base. Coverage of changed paths in the base tree is reported.
- The file predictor sees only paths, not file contents, imports or test names. Top five is fixed for comparability with the constructed-pair run.
- No result here establishes prospective accuracy. A strict pre-start claim needs archived prompts and checkout SHAs at dispatch.

## Reproduction

```sh
uv run --locked python scripts/build_natural_cohort.py --check
uv run --locked python scripts/run_natural_predictions.py --text title
uv run --locked python scripts/analyze_natural_cohort.py
```

The fetch and file-predictor commands are in the [protocol](natural-cohort-protocol.md). They require a GitHub token and the private table and checkpoint, which stay out of Git.
