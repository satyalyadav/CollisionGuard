# Evaluation tools

Code lives in `src/evaltools/`, tests in `tests/test_evaltools_*.py` and
`tests/test_run_evaluation.py`. The tools use only the standard library.

Two runnable entry points:

```sh
uv run --locked python src/eval_demo.py        # made-up scores, shows the leakage check catching a random split
uv run --locked python src/run_evaluation.py   # scores the baselines from src/run_baselines.py on the public twelve pairs
```

`run_evaluation.py` first audits the leave-one-repository-out folds used by
`run_baselines.py` for shared repositories, tasks and task pairs, then reports
metrics with repo-cluster bootstrap intervals. The numbers demonstrate that the
workflow runs. Twelve pairs cannot establish prediction accuracy.

## Input contract

One dict per task pair, following [local-record-format.md](../data/local-record-format.md):

| Field | Meaning |
| --- | --- |
| `instance_id` | Unique pair id |
| `repo` | Split group |
| `task_a`, `task_b` | Task text, or `task_a_id`, `task_b_id` if already hashed |
| `label` | `conflict` / `clean` (or 1 / 0) |
| `family` | Optional. Variants of one task, kept on one side of every split |
| `time` | Optional. Only used by the forward-time split |

Predictions are one score per pair, a list in record order or a dict by
`instance_id`. Higher means more conflict risk; use values in [0, 1] if you want
Brier score, log loss and calibration. Whoever builds a baseline only has to
produce those scores.

## What is checked

- `splits.group_kfold` and `holdout_split` tie together every pair that shares a
  repo, a task or a family, and never divide a group. Too few groups raises an
  error instead of producing a weaker split.
- `splits.assert_no_leakage` fails on shared instance ids, repos, tasks,
  families or unordered task pairs.
- `splits.forward_time_split` trains on earlier pairs and drops later pairs that
  share a task or family with training (optionally also seen repos).
- `metrics`: average precision and trapezoid PR-AUC (reported separately because
  they differ), precision at a recall target, recall at a review budget,
  confusion counts, Brier score, log loss, reliability table and ECE.
- `bootstrap`: resamples whole repos for intervals and for paired differences
  between two models.
- `report.evaluate` collects these and lists warnings (few repos, few positives,
  repos with no positives).

## Limits

- With the 12 verified ParallACT pairs across 8 repos there are 1 to 2 pairs
  per repo, so any result is a demonstration. The report warns about this.
- The ParallACT pairs carry no usable timestamps, so the forward-time split
  cannot be run on them.
- Undefined metrics (for example AP in a resample with no positives) are
  reported as nan or counted as skipped, never silently set to zero.
