# CollisionGuard v0.2 model card

## Model

An equal-weight average of two classifiers over pre-start task and repository features: a class-balanced logistic regression and an 800-tree extremely randomized forest. The logistic model supplies the signed factor explanations; the forest contributes nonlinear interactions. The averaged score is calibrated with Platt scaling on out-of-fold scores; isotonic regression produced overconfident 0.0 and 1.0 tails on this cohort.

Artifact: `models/collisionguard-v0.2.joblib`. Training script: `scripts/train_product_model.py`.

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
| Average precision | 0.443 |
| ROC AUC | 0.703 |
| Brier raw / in-sample calibrated / cross-fitted calibrated | 0.198 / 0.155 / 0.157 |
| Brier constant baseline | 0.172 |
| Forward-time AUC | 0.654 |
| Issue-title transfer AUC (unseen repositories) | 0.563 (0.441-0.684) |

Band rates from out-of-fold scores:

| Band | Pairs | Conflicts | Rate |
| --- | --- | --- | --- |
| Low (below 70th percentile) | 455 | 72 | 15.8% |
| Elevated (70th to 90th) | 130 | 35 | 26.9% |
| High (90th and above) | 67 | 37 | 55.2% |

The high band captures 25.7 percent of conflicts (37/144). The top 10 percent by score captures 25.7 percent with 56.9 percent precision. The top 30 percent captures 50.0 percent with 36.9 percent precision. The base rate is 22.1 percent.

The band rates are cross-validated but optimistic: the feature set and ensemble were chosen after looking at folds 0-3, and fold 4 was inspected during development. Fold 4 alone has 13 top-decile pairs, of which 5 conflict (38.5 percent against a 25.2 percent base). Treat the exact high-band rate as uncertain.

## Calibration

Platt scaling reduces the in-sample Brier score from 0.198 to 0.155. A leave-one-fold-out calibrator gives 0.157, against a constant-probability baseline of 0.172. The cross-fitted value is the honest one; the in-sample value is optimistic. Calibration is modest but real. The calibrated score stays below 0.54 on this cohort, close to the observed high-band rate. Probabilities are still rough; the band and percentile are the intended outputs.

## Alternatives tested

A raw logistic regression alone reaches AP 0.405 and AUC 0.709. The forest alone reaches AP 0.430 and AUC 0.679. The equal average reaches AP 0.443 and AUC 0.703, with the best top-decile hit count. The v0.1 pipeline standardized its one-hot features, which amplified rare categories; removing that scaling was the main source of the gain.

Word and character TF-IDF of the two PR titles added to the metadata model reached AP 0.419 and AUC 0.712. The gain over the corrected metadata-only logistic was small and its interval included zero, so it is not in the product.

Within the 165-pair strict-issue subset, a model trained on issue titles alone reached AUC 0.486; adding issue bodies reached 0.326. The title-trained transfer model reached 0.563. A standalone pre-start model is not supported by 24 conflicts.

Twenty base-tree shape features and seventeen AIDev prior-activity features did not improve grouped cross-validation. Tree shape lowered AP; prior activity helped only on the subset with history and did not beat the ensemble. Neither is in the product.

A zero-shot GLM-5.3 scorer on 40 balanced held-out pairs reached AUC 0.551 and AP 0.651. The calibrated model on the same pairs reached AUC 0.715 and AP 0.713; a rank-average fusion reached 0.670 AUC. The LLM scores were not integrated. The sample is small and the prompt supplied only titles, repository metadata, agent names and predicted files.

## Limitations

- Retrospective co-active PR pairs, not tasks dispatched from a queue.
- PR titles are written after coding and can summarize the change.
- Issue-text transfer is weaker (AUC 0.563, 95 percent interval 0.441-0.684) and uses a small 165-pair subset. The interval includes chance.
- Agent identity and repository metadata carry much of the signal, so new agents and unusual repositories may behave differently.
- Textual merge conflict is not semantic incompatibility. Clean merges can still break tests.
- The file ranker is lexical and finds only about 22 percent of changed files.
- The forest is not interpretable per feature. The CLI factors are the linear component's contributions and do not describe the forest's share.

## Ethical and operational notes

- Treat a high band as a reason to review, not a reason to block.
- Do not use the score as the sole basis for denying work or evaluating an agent.
- Keep the model version and training table hash with any reported result.
- The model artifact contains coefficients only, not task text.
