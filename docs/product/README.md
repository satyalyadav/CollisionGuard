# CollisionGuard product (v0.1)

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

| Measure | Value |
| --- | --- |
| Average precision | 0.363 |
| ROC AUC | 0.677 |
| Brier score, raw / calibrated | 0.220 / 0.155 |
| Brier score, held-out fold | 0.151 (constant baseline 0.172) |
| Forward-time AUC (last 30 percent) | 0.625 |
| Issue-title transfer AUC, unseen repositories | 0.582 (95 percent interval 0.458-0.705) |
| Top 10 percent precision / recall | 0.492 / 0.222 |
| Top 20 percent precision / recall | 0.385 / 0.347 |
| Top 30 percent precision / recall | 0.369 / 0.500 |

The high band (top 10 percent by score) has a 49.3 percent conflict rate against a 22.1 percent base. The elevated band (70th to 90th percentile) has 30.8 percent. The low band has 15.6 percent. A scheduler can use this to order review, but half of flagged pairs still merge cleanly and half of conflicts fall outside the top 30 percent.

The issue-title transfer test is the closer pre-start check, because it uses issue text instead of outcome-adjacent PR titles. Its AUC is 0.582, but the 95 percent interval includes chance, so the transfer result is uncertain.

## Train or refresh the model

```sh
uv run --locked python scripts/train_product_model.py
```

This writes `models/collisionguard-v0.1.joblib` and the public metrics in `data/natural-cohort-2026-11/product-model.json`. The training table and file results stay under the ignored private root.

## Alternatives tested

A zero-shot GLM-5.3 scorer on 40 balanced held-out pairs did not beat the calibrated model (AUC 0.551 against 0.715). It is not in the product.

## Roadmap

1. Add repository-history risk: prior conflict rate, churn and hot files, cut at dispatch time.
2. Replace the lexical path ranker with symbol retrieval from the base tree; keep changed files out of the index.
3. Fuse a zero-shot LLM score with the calibrated model, out of fold, and test whether it clears the triage bar on unseen repositories.
4. Pair any high-risk flag with a cheap `git merge-tree` check once branches exist. The predictor orders checks; it does not replace them.
5. Run a frozen-label scheduling simulation before claiming fewer conflicts or faster makespan.

Larger embedding and replay batches can move to ASU Sol when the allocation, VPN and credentials are available. Local CPU handles the current cohort.

## Limits

- The labels are replayed textual merge conflicts between PR final heads, not prospective task runs.
- Most training text is PR titles, written after coding. The issue-text transfer is weaker.
- Agent identity and repository metadata carry much of the signal. The model may not transfer to new agents or unusual repositories.
- The path finder is lexical. It finds about 22 percent of changed files and often picks generic files.
- Calibrated probabilities are rough. Use the band and percentile, not the third decimal.
- No result establishes a causal reduction in conflicts from serializing tasks.

See the [model card](model-card.md) for details.
