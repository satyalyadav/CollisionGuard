# CollisionGuard product (v0.2)

CollisionGuard is an experimental triage tool. Given two coding tasks and a Git repository, it ranks the pair's merge-conflict risk and lists the files each task is likely to touch. Use it to decide which pairs to review first or run one at a time. It is not a safety guarantee and it should not auto-approve work.

## What it uses

Only inputs available before either agent starts:

- the two task descriptions,
- the repository language and tracked-file count,
- which agent handles each task, and whether they are the same,
- repository paths, used separately to show likely and shared files.

It does not read diffs, changed files, branch state, or merge outcomes.

## What it reports

- A risk band (low, elevated, high) and the pair's percentile among historical pairs.
- The historical conflict rate for that band.
- The likely files for each task and any shared paths or directories.
- The largest factors that raised or lowered the score.
- A caveat that the model is retrospective and weak.

## Run it

```sh
PYTHONPATH=src uv run --locked python -m collisionguard.cli \
  --repo /path/to/repo \
  --task-a "Add an API endpoint for user exports" \
  --task-b "Update the API client retry logic" \
  --agent-a codex --agent-b claude
```

Add `--json` for machine-readable output. Task text can also come from files with `--task-a-file` and `--task-b-file`.

Pass both agent names for the calibrated band rates. Common spellings such as `codex`, `claude` and `copilot` are normalized to the training names. If either name is missing, the model treats the pair as unknown-agent and the CLI warns that the historical band rates may not apply.

For a browser demo:

```sh
PYTHONPATH=src uv run --locked python scripts/serve_product.py
# open http://127.0.0.1:8765
```

## Measured performance

Trained on 652 natural co-active AI-agent PR pairs from 598 repositories (144 conflicts, prevalence 22.1 percent). Repository-grouped cross-validation.

The score is an equal-weight average of a class-balanced logistic regression and an 800-tree extremely randomized forest. The forest adds nonlinear interactions; the linear model supplies the per-pair explanations in the CLI.

| Measure | Value |
| --- | --- |
| Average precision | 0.443 |
| ROC AUC | 0.703 |
| Brier score, raw / in-sample calibrated / cross-fitted calibrated | 0.198 / 0.155 / 0.157 |
| Brier score, constant baseline | 0.172 |
| Forward-time AUC (last 30 percent) | 0.654 |
| Issue-title transfer AUC, unseen repositories | 0.563 (95 percent interval 0.441-0.684) |
| Top 10 percent precision / recall | 0.569 / 0.257 |
| Top 20 percent precision / recall | 0.415 / 0.375 |
| Top 30 percent precision / recall | 0.369 / 0.500 |

The high band (top 10 percent by score) has a 55.2 percent conflict rate against a 22.1 percent base, up from 49.3 percent in v0.1. The elevated band has 26.9 percent and the low band 15.8 percent. The top 10 percent captures 37 of 144 conflicts; the top 30 percent captures 72. A scheduler can use this to order review, but 45 percent of high-band pairs still merge cleanly and half of conflicts fall outside the top 30 percent.

The band rate is optimistic because the feature set and ensemble were chosen after looking at folds 0-3, and fold 4 was inspected during development. Fold 4 alone has 13 top-decile pairs, of which 5 conflict (38.5 percent against a 25.2 percent base). Treat the exact rate as uncertain.

Two changes explain the gain. The v0.1 logistic standardized its one-hot features, which amplified rare categories; removing that scaling and averaging the linear score with the forest raised AP from 0.363 to 0.443. A raw logistic alone scores AP 0.405 and AUC 0.709; the forest alone scores AP 0.430 and AUC 0.679. The average trades a little AUC for better tail ranking.

The issue-title transfer test is the closer pre-start check, because it uses issue text instead of outcome-adjacent PR titles. Its AUC is 0.563, essentially unchanged from v0.1 and still including chance in the interval. The product therefore remains a retrospective triage prior.

## Train or refresh the model

```sh
uv run --locked python scripts/train_product_model.py
```

This writes `models/collisionguard-v0.2.joblib` and the public metrics in `data/natural-cohort-2026-11/product-model.json`. The training table and file results stay under the ignored private root.

## Alternatives tested

A zero-shot GLM-5.3 scorer on 40 balanced held-out pairs did not beat the calibrated model (AUC 0.551 against 0.715). It is not in the product.

Adding word and character TF-IDF of the two PR titles to the metadata model reached AP 0.419 and AUC 0.712, but the gain over the corrected metadata-only logistic was small and the interval included zero. It is not in the product.

Adding 20 base-tree shape features, or 17 AIDev prior-activity features, did not improve the grouped cross-validation. Tree shape lowered AP; prior activity helped only where history existed and did not beat the ensemble. Neither is in the product.

## Roadmap

1. Add repository-history risk: prior conflict rate, churn and hot files, cut at dispatch time. This needs a blobless clone or commit crawl of the cohort repositories; the filtered AIDev sample has no file-level history.
2. Replace the lexical path ranker with symbol retrieval from the base tree; keep changed files out of the index. This needs file contents, so it is the first natural ASU Sol job.
3. Test a stronger zero-shot judge and out-of-fold fusion on a pre-registered sample; the 40-pair GLM result is too small to settle it.
4. Pair any high-risk flag with a cheap `git merge-tree` check once branches exist. The predictor orders checks; it does not replace them.
5. Run a frozen-label scheduling simulation before claiming fewer conflicts or faster makespan.

Larger embedding, symbol-index and replay batches can move to ASU Sol when the allocation, VPN and credentials are available. Local CPU handles the current cohort.

## Limits

- The labels are replayed textual merge conflicts between PR final heads, not prospective task runs.
- Most training text is PR titles, written after coding. The issue-text transfer is weaker and its interval includes chance.
- Agent identity and repository metadata carry much of the signal. The model may not transfer to new agents or unusual repositories.
- The path finder is lexical. It finds about 22 percent of changed files and often picks generic files.
- The forest is less interpretable than a linear model. The CLI reasons come from the linear component, so they do not describe the forest's contribution.
- Calibrated probabilities are rough. Use the band and percentile, not the third decimal.
- No result establishes a causal reduction in conflicts from serializing tasks.

See the [model card](model-card.md) for details.
