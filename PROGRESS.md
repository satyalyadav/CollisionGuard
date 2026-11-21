# Project progress

Summary for reports. Dates use America/Phoenix time.

## Current status

- The [public repository](https://github.com/satyalyadav/CollisionGuard) holds code, reports and the [twelve-pair dataset](data/parallact-12/README.md). Student IDs and full local workspaces stay excluded.
- The [resource recovery](docs/pilot/parallact-recovery-results.md) produced twelve verified pairs across eight repositories, with seven clean and five conflict labels. Opus 5.5 accepted the records. The public bundle adds task statements, licenses, source notices and offline verification.
- Recovery reuses the same twelve cases; earlier failures and unknown runner/site provenance remain.
- The [release assessment](docs/research/parallact-public-release.md) supplies the limited release basis. The blanket private-only advice was too cautious. No prediction accuracy has been established.
- The [controlled single-project pilot](docs/pilot/controlled-single-project-results.md) built five verified common-start task pairs from one parent anchor. Raw full-directory capture labeled all five as conflicts because ignored pytest caches and bytecode were force-included. Ordinary Git staging of the same outputs gives three clean and two conflicts. Those five repositories are development examples.
- The [fresh cohort](docs/pilot/fresh-cohort-results.md) built five more verified pairs from repositories outside the earlier pilots, with ordinary Git staging frozen before coding. All five pairs qualified and all five conflicted; both tasks in each pair edited the same module and test file. This is a purposive construction, not a conflict base rate.
- The [first prediction check](docs/pilot/controlled-prediction-results.md) scores the ten constructed pairs with the existing baselines. TF-IDF average precision is 0.948, but the construction and task text both name the target module and test file, so the score cannot be separated from the construction. Logistic regression is below the no-skill AP. No accuracy claim follows.
- The [file predictor check](docs/pilot/file-predictor-results.md) finds about 62 percent of changed files with raw task text and 30 percent with paths removed. Its overlap score is 0.819, below the text-only 0.948, and adding it to the text score does not help. It also misses changelog conflicts. No accuracy claim follows.
- The [natural-mix cohort](docs/pilot/natural-cohort-results.md) uses 666 real co-active AI-agent PR pairs from a CC-BY replication package, joined to AIDev text; outcomes were not designed here. PR titles alone give AUC 0.524 and AP 0.267 against 0.227 prevalence, so the constructed 0.948 does not transfer. The path-only file predictor on 652 pairs reaches overlap AUC 0.553 against text 0.525; the fixed blend gains 0.014 AP with a paired interval of -0.014 to +0.047. On the 165-pair strict-issue subset, overlap is a below-0.5 point estimate. Twenty replay labels agreed. The cohort challenges the model; no reliable file-overlap gain is established.
- CooperBench forms a communicating condition. Other corpora lack verified task/base joins. The [AIDev pilot](docs/pilot/results.md) remains inconclusive. Sol access is unverified; project `AGENTS.md` remains a suggestion.

- The [product prototype](docs/product/README.md) ranks two tasks before coding with task-type, repository and agent-pair features. Repository-grouped CV gives AP 0.356 and AUC 0.648; the issue-title transfer check is 0.582. The top 10 percent band has a 46.3 percent conflict rate against a 22.1 percent base. The CLI and calibrated model card are in the repo. It is a weak triage tool, not a safety guarantee.
- The [Hugging Face-ready export](data/natural-cohort-2026-11/hf/README.md) publishes 673 pairs with labels, metadata and fixed folds; task text stays private and is rejoined from AIDev.

## Milestones

### 2026-11-07: Preserve the proposal

Converted the PDF to [Markdown](docs/proposal/original-proposal.md). Removed redundant conversion files as requested. The unchanged private copy remains local; the public copy removes student IDs.

### 2026-11-07: Research and audit sources

Reviewed novelty, data and evaluation. Prediction before either task starts is the proposed contribution. The [source audit](docs/research/data-source-audit.md) reproduced six ParallACT pairs and one CooperBench pair. Workflow/corpus evidence remained incomplete. Opus confirmed the replay evidence.

### 2026-11-07: Close the AIDev pilot

Sampled PR pairs and attempted Git diagnostics. Unqueried historical records leave feasibility unassessed. Opus review prompted clearer statuses and disclosure of unretained script revisions.

### 2026-11-08: Publish and run the first import pilot

Published scripts, reports and metadata, then checked reuse terms. Six retention checks matched. Seven of twelve new cases replayed, with two clean and five conflict labels. Four unsupported v2 cases and a whitespace false negative prevented a pass. Fixed future whitespace matching while preserving the failed result.

### 2026-11-08: Run the v1-only follow-up

All twelve associations passed; four replays completed, with two clean and two conflict labels. Two cases hit the repository download budget and six exceeded the archive decompression limit. Opus confirmed the evidence. Recorded collection limitations without changing frozen records. That collector was superseded by the recovery.

### 2026-11-08: Recover useful local records

Reused caches with separate JSON/archive limits. All twelve pairs have repeatable exact-tree labels and synchronized records. Preserved producer history and the interrupted first job's unknown exit. Opus 5.5 accepted the records. No model was trained at this milestone.

### 2026-11-08: Preserve durable local storage

Moved all three ParallACT workspaces into ignored `data/private/parallact/`, verifying unchanged file hashes. Cache paths remain symlinks. No backup or sharing was created.

### 2026-11-08: Clarify public release terms

A targeted source check and Opus review support a curated release under existing terms. Preserve component licenses and notices; credit alone is insufficient. No raw data was published during this investigation.

### 2026-11-09: Package the public dataset

Released task statements and labels with sources, component terms and license texts. Offline verification checks the pairs against recovery evidence; originals remain unchanged. PR1 adds TF-IDF and logistic baselines. Follow-up fixes add repository-separated evaluation, strict record validation, explicit synthetic mode and a reproducible dependency lock. All 67 tests and both runner modes pass. Commands are in the README. These runs demonstrate the workflow, not prediction accuracy.

### 2026-11-16: Controlled single-project pilot

Built one private parent anchor holding five pinned upstream trees, then ran ten DeepSeek V4.1 Flash coding tasks, two per repository, each in an isolated T3 worktree. All ten starts matched the pinned source tree and all five pairs replayed twice with identical results. The frozen full-directory capture labeled every pair `conflict`, because `git add --force` admitted pytest caches and bytecode. A separately named post-hoc analysis staged the same final directories as ordinary Git files: three clean merges and two conflicts (`CHANGES.rst` in itsdangerous; `CHANGELOG.rst` and `tests/test_utils.py` in packaging). The post-hoc labels are diagnostic, not replacements. See the [protocol](docs/pilot/controlled-single-project-protocol.md), [results](docs/pilot/controlled-single-project-results.md) and [public summary](data/controlled-single-project/posthoc-git-visible.json).

### 2026-11-20: Commit the pilot record and freeze an ordinary-staging collector

Committed the controlled, SWE-rebench and source-search scripts, tests, protocols, results and decision logs, and archived the oral report source under `docs/archive/2026-11-oral-report/`. Removed the generated report and presentation files. The collector now takes its staging policy from the frozen plan: `full-directory-v3` reproduces the old force-add captures, and `ordinary-git-staging-v1` lets the repository's own ignore rules decide.

### 2026-11-20: Collect the fresh cohort

Ran ten coding tasks on pluggy, requests, httpx, urllib3 and jsonschema, none of them used in the earlier controlled pilots or the public twelve. The first attempt stopped at the requests capture because the filesystem inventory could not see directory symlinks; the recorder was corrected, a fixture test was added, and the cohort was refrozen from a new anchor. In the corrected run every start matched its pinned tree, every patch replayed twice, and the feasibility gate passed. All five pairs conflicted under ordinary Git staging. Both tasks in each pair edited the same module and test file, so the five-of-five result describes this construction, not a base rate. See the [protocol](docs/pilot/fresh-cohort-protocol.md), [results](docs/pilot/fresh-cohort-results.md) and [public summary](data/controlled-fresh-2026-11/summary.json). The prediction check below uses these labels.

### 2026-11-20: Run the first prediction check

Built a ten-pair table from the two constructed cohorts, keeping task text in the ignored private data root. The table has 3 clean and 7 conflict labels across ten repositories. Ran TF-IDF cosine and logistic regression with leave-one-repository-out folds; the leakage audit passed for all ten folds. TF-IDF average precision is 0.948, but the construction and task text both name the target module and test file, so the score cannot be separated from the construction. Removing explicit paths leaves 0.909; the run cannot isolate wording from the paired authorship. Logistic regression is 0.685, below the no-skill AP of 0.700. Added a builder, a runner and eleven tests. See the [results](docs/pilot/controlled-prediction-results.md), [public summary](data/controlled-prediction-10/summary.json) and [scores](data/controlled-prediction-10/results.json). No accuracy result.

### 2026-11-21: Test the file predictor on the ten pairs

Merged the path-only file predictor from PR 2 and evaluated it on the ten constructed pairs. At top five it recalled 62 percent of changed files with raw task text and 30 percent with explicit paths removed. Its predicted overlap scored 0.819 average precision, below the text-only 0.948; equal and text-heavy blends did not improve the text score. The overlap-positive rule caught all seven conflicts but also flagged two clean pairs, and the predictor missed the changelog conflicts in itsdangerous and packaging. Added the evaluation script, eleven tests and public results. See the [results](docs/pilot/file-predictor-results.md) and [public output](data/controlled-prediction-10/file-predictor.json). No accuracy result.

### 2026-11-21: Build the natural-mix cohort

Built the first cohort whose merge outcomes this project did not design. The pair list and labels come from the CC-BY replication package for *Concurrent AI-Agent Pull Requests on GitHub* (Zenodo 10.5281/zenodo.21186464): 747 attempts, 716 evaluable, 167 conflicts. Joining to AIDev task text left 673 pairs across 616 repositories (518 clean, 155 conflict). Seven pairs with identical titles were dropped, leaving 666. Issue text is available for 193 pairs; 182 of them are strict, where both PRs close a pre-created issue (174 usable).

Label replay agreed 20/20 on a fixed sample. Text-only results under repository-grouped 5-fold CV: PR titles give TF-IDF AP 0.267 against 0.227 prevalence and AUC 0.524; logistic AUC 0.534. The strict-issue subset gives TF-IDF AUC 0.534 and logistic AP 0.254 against 0.161 prevalence, AUC 0.566. The constructed cohort's 0.948 AP does not transfer.

Fetched the true merge base, base tree and changed paths for all 666 title-eligible pairs (662 ok, four unavailable, five truncated trees, five truncated file lists). An equal target-base shortcut had produced wrong trees for 20 of 108 refreshed rows; all were corrected. The path-only file predictor scored 652 pairs: mean footprint recall 0.225, predicted-overlap AUC 0.553, text AUC 0.525, actual-path reference AUC 0.673. The fixed equal blend gains 0.014 AP, paired interval -0.014 to +0.047. On the strict-issue subset (165 pairs), overlap AUC is 0.463 and the blend does not beat text. The cohort challenges the model rather than confirming it.

Reviews: Sol 6.2 high found the manifest and merge-base errors and asked for paired gains and better attrition reporting; ASU GLM-5.3 reproduced the source's headline numbers and flagged final-head labels and the strict subset; ASU MiMo-2.6 rejected CooperBench as engineered data. Added six scripts, four test modules, the protocol, results and public summaries. No accuracy claim follows.

### 2026-11-21: Build the product prototype and public cohort export

Built a pre-start risk model and CLI. Features are task-type keyword counts, repository language and size, agent identities and pairing, and task lengths; no diffs or changed files. A logistic regression with isotonic calibration reaches AP 0.356 and AUC 0.648 under repository-grouped cross-validation on 652 natural pairs. Forward-time AUC is 0.625. On 165 strict-issue pairs from unseen repositories, issue-title transfer AUC is 0.582. The top 10 percent band has a 46.3 percent conflict rate against a 22.1 percent base and captures 20.1 percent of conflicts; the top 30 percent captures 48.6 percent at 35.9 percent precision. The CLI reports a band, percentile, historical band rate, likely and shared files, and top factors.

Added a bounded auto-research loop that tunes on folds 0-3 and checks fold 4 once. It selected the full feature set; fold 4 AP is 0.412 and AUC 0.708, but fold 4 was already inspected in exploratory work, so this is a check rather than a sealed test. Added the package, training script, tests, product guide, model card and a Hugging Face-ready 673-row export with fixed repository-grouped folds. Task text stays private. The model is a weak triage prior, not a reliable conflict warning.

## Maintaining this log

Record decisions and results, link evidence, distinguish plans from completed work and correct mistakes explicitly. Aim for roughly 500 words; consolidate at phase boundaries.
