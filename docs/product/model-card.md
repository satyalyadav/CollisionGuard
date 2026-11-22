# CollisionGuard v0.1 model card

## Model

A logistic regression over pre-start task and repository features. Coefficients are fitted on natural co-active AI-agent pull-request pairs and calibrated with isotonic regression on out-of-fold scores.

Artifact: `models/collisionguard-v0.1.joblib`. Training script: `scripts/train_product_model.py`.

## Intended use

Triage for a coding-agent scheduler or a human reviewer. The model ranks pairs of task descriptions by textual merge-conflict risk and supports ordering review or serializing suspicious pairs.

Not intended for: automatic approval, safety certification, estimating semantic compatibility, or deciding whether tests pass.

## Training data

- 652 pairs across 598 repositories, 144 conflicts (22.1 percent).
- Source: the CC-BY replication package for *Concurrent AI-Agent Pull Requests on GitHub* (Zenodo 10.5281/zenodo.21186464), joined to AIDev task text.
- Labels: a three-way `git merge-tree` replay of the two PR final heads over their merge base.
- Text: PR titles. This is outcome-adjacent; the model card reports a transfer test on linked issue text as the closer pre-start check.

## Features

- Task-type keyword counts for docs, tests, dependencies, CI, refactor, UI, API, database, security, and performance.
- Whether both tasks mention each type.
- Repository language, log tracked-file count, agent identities and pair, same-agent flag, and log task lengths.
- No changed-file, diff, branch, or label inputs.

## Metrics

Repository-grouped 5-fold cross-validation, seed 0:

| Measure | Value |
| --- | --- |
| Average precision | 0.363 |
| ROC AUC | 0.677 |
| Brier raw / calibrated | 0.220 / 0.155 |
| Brier held-out fold / constant baseline | 0.151 / 0.172 |
| Forward-time AUC | 0.625 |
| Issue-title transfer AUC (unseen repositories) | 0.582 (0.458-0.705) |

Band rates from out-of-fold scores:

| Band | Pairs | Conflicts | Rate |
| --- | --- | --- | --- |
| Low (below 70th percentile) | 455 | 71 | 15.6% |
| Elevated (70th to 90th) | 130 | 40 | 30.8% |
| High (90th and above) | 67 | 33 | 49.3% |

The high band captures 22.9 percent of conflicts (33/144). The top 10 percent by score captures 22.2 percent with 49.2 percent precision. The top 30 percent captures 50.0 percent with 36.9 percent precision. The base rate is 22.1 percent.

## Calibration

Isotonic regression reduces the in-sample Brier score from 0.220 to 0.155. A calibrator fitted on folds 0-3 and scored on fold 4 gives 0.151, against a constant-probability baseline of 0.172. Calibration is modest but real. Probabilities are still rough; the band and percentile are the intended outputs.

## Alternatives tested

A zero-shot GLM-5.3 scorer on 40 balanced held-out pairs reached AUC 0.551 and AP 0.651. The calibrated model on the same pairs reached AUC 0.715 and AP 0.713; a rank-average fusion reached 0.670 AUC. The LLM scores were not integrated. The sample is small and the prompt supplied only titles, repository metadata, agent names and predicted files.

## Limitations

- Retrospective co-active PR pairs, not tasks dispatched from a queue.
- PR titles are written after coding and can summarize the change.
- Issue-text transfer is weaker (AUC 0.582, 95 percent interval 0.458-0.705) and uses a small 165-pair subset. The interval includes chance.
- Agent identity and repository metadata carry much of the signal, so new agents and unusual repositories may behave differently.
- Textual merge conflict is not semantic incompatibility. Clean merges can still break tests.
- The file ranker is lexical and finds only about 22 percent of changed files.

## Ethical and operational notes

- Treat a high band as a reason to review, not a reason to block.
- Do not use the score as the sole basis for denying work or evaluating an agent.
- Keep the model version and training table hash with any reported result.
- The model artifact contains coefficients only, not task text.
