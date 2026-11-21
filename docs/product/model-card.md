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
| Average precision | 0.356 |
| ROC AUC | 0.648 |
| Brier raw / calibrated | 0.229 / 0.158 |
| Forward-time AUC | 0.625 |
| Issue-title transfer AUC (unseen repositories) | 0.582 |

Band rates from out-of-fold scores:

| Band | Pairs | Conflicts | Rate |
| --- | --- | --- | --- |
| Low (below 70th percentile) | 455 | 74 | 16.3% |
| Elevated (70th to 90th) | 130 | 39 | 30.0% |
| High (90th and above) | 67 | 31 | 46.3% |

The high band captures 20.1 percent of conflicts with 44.6 percent precision. The top 30 percent captures 48.6 percent with 35.9 percent precision. The base rate is 22.1 percent.

## Calibration

Isotonic regression on out-of-fold scores reduces the Brier score from 0.229 to 0.158. Probabilities are still rough; the band and percentile are the intended outputs.

## Limitations

- Retrospective co-active PR pairs, not tasks dispatched from a queue.
- PR titles are written after coding and can summarize the change.
- Issue-text transfer is weaker (AUC 0.582) and uses a small 165-pair subset.
- Agent identity and repository metadata carry much of the signal, so new agents and unusual repositories may behave differently.
- Textual merge conflict is not semantic incompatibility. Clean merges can still break tests.
- The file ranker is lexical and finds only about 22 percent of changed files.

## Ethical and operational notes

- Treat a high band as a reason to review, not a reason to block.
- Do not use the score as the sole basis for denying work or evaluating an agent.
- Keep the model version and training table hash with any reported result.
- The model artifact contains coefficients only, not task text.
