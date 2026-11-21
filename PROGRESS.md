# Project progress

Summary for reports. Dates use America/Phoenix time.

## Current status

- The [public repository](https://github.com/satyalyadav/CollisionGuard) holds code, reports and the [twelve-pair dataset](data/parallact-12/README.md). Student IDs and full local workspaces stay excluded.
- The [resource recovery](docs/pilot/parallact-recovery-results.md) produced twelve verified pairs across eight repositories, with seven clean and five conflict labels. Opus 5.5 accepted the records. The public bundle adds task statements, licenses, source notices and offline verification.
- Recovery reuses the same twelve cases; earlier failures and unknown runner/site provenance remain.
- The [release assessment](docs/research/parallact-public-release.md) supplies the limited release basis. The blanket private-only advice was too cautious. No prediction accuracy has been established.
- The [controlled single-project pilot](docs/pilot/controlled-single-project-results.md) built five verified common-start task pairs from one parent anchor. Raw full-directory capture labeled all five as conflicts because ignored pytest caches and bytecode were force-included. Ordinary Git staging of the same outputs gives three clean and two conflicts. Those five repositories are development examples.
- The [fresh cohort](docs/pilot/fresh-cohort-results.md) built five more verified pairs from repositories outside the earlier pilots, with ordinary Git staging frozen before coding. All five pairs qualified and all five conflicted; both tasks in each pair edited the same module and test file. This is a purposive construction, not a conflict base rate.
- The [first prediction check](docs/pilot/controlled-prediction-results.md) scores the ten constructed pairs with the existing baselines. TF-IDF average precision is 0.948, but the task text names the target module and test file, so the rank restates the construction. Logistic regression is at the base-rate reference. No accuracy claim follows.
- CooperBench forms a communicating condition. Other corpora lack verified task/base joins. The [AIDev pilot](docs/pilot/results.md) remains inconclusive. Sol access is unverified; project `AGENTS.md` remains a suggestion.

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

Ran ten coding tasks on pluggy, requests, httpx, urllib3 and jsonschema, none of them used in the earlier controlled pilots or the public twelve. The first attempt stopped at the requests capture because the filesystem inventory could not see directory symlinks; the recorder was corrected, a fixture test was added, and the cohort was refrozen from a new anchor. In the corrected run every start matched its pinned tree, every patch replayed twice, and the feasibility gate passed. All five pairs conflicted under ordinary Git staging. Both tasks in each pair edited the same module and test file, so the five-of-five result describes this construction, not a base rate. See the [protocol](docs/pilot/fresh-cohort-protocol.md), [results](docs/pilot/fresh-cohort-results.md) and [public summary](data/controlled-fresh-2026-11/summary.json). No prediction run has used this data.

### 2026-11-21: Run the first prediction check

Built a ten-pair table from the two constructed cohorts, keeping task text under `data/private/`. The table has 3 clean and 7 conflict labels across ten repositories. Ran TF-IDF cosine and logistic regression with leave-one-repository-out folds; the leakage audit passed for all ten folds. TF-IDF average precision is 0.948, but the prompts name the target module and test file, so the rank restates the construction. Removing explicit paths leaves 0.909, so wording similarity also restates how the pairs were authored. Logistic regression is 0.685, at the base-rate reference. Added a builder, a runner and seven tests. See the [results](docs/pilot/controlled-prediction-results.md), [public summary](data/controlled-prediction-10/summary.json) and [scores](data/controlled-prediction-10/results.json). No accuracy result.

## Maintaining this log

Record decisions and results, link evidence, distinguish plans from completed work and correct mistakes explicitly. Aim for roughly 500 words; consolidate at phase boundaries.
