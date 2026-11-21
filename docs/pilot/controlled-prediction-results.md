# Prediction check on the ten constructed pairs

This is the first prediction run on pairs built by this project. It joins the frozen task text from the two controlled cohorts to their published labels, then scores the pairs with the same baselines used on the public twelve. Ten pairs cannot establish accuracy. The run checks that the pipeline works end to end and records what the starting methods do on this construction.

## Data

| Cohort | Pairs | Clean | Conflict | Label source |
| --- | --- | --- | --- | --- |
| Controlled v3 | 5 | 3 | 2 | Post-hoc ordinary Git staging |
| Fresh 2026-11 | 5 | 0 | 5 | Frozen ordinary Git staging |
| Total | 10 | 3 | 7 | |

Every pair uses a different repository, so leave-one-repository-out is also leave-one-pair-out for the held-out side. The full table, including task text and changed paths, stays under `data/private/research/controlled-prediction-10/`. The public summary is [summary.json](../../data/controlled-prediction-10/summary.json) and the public scores are [results.json](../../data/controlled-prediction-10/results.json). Both carry counts, labels, hashes and per-pair scores, with no task text and no local paths.

Table SHA-256: `4b06ebb7e97ffe71b63c030401e86a4b59280fc5b6b0946b7f2b69851e94d091`.

The builder checks each acceptance statement against its frozen prompt bytes and verifies the fresh plan hash against the published summary. It rejects a missing task, a reused task, a duplicate repository, a changed prompt, or a table with only one label class.

## Method

- Task input is the frozen acceptance text. The builder checks that this exact text appears in the prompt bytes the child received.
- TF-IDF cosine and logistic regression use the existing models in `src/baselines.py`; the runner adds no new feature.
- A second TF-IDF run removes path-like tokens such as `src/module.py` from the task text, to show how much of the score comes from the named target.
- Folds leave out all pairs from one repository. The leakage audit passed for all ten folds.
- Metrics come from `src/evaltools/` with 500 repository-cluster bootstrap resamples.
- TF-IDF is a similarity, not a probability, so calibration metrics are left out for it.
- The base-rate reference scores each test pair with the conflict rate of its training folds.

## Results

| Model | Average precision | PR-AUC (trapezoid) |
| --- | --- | --- |
| Base-rate reference | 0.700 | 0.350 |
| TF-IDF cosine | 0.948 | 0.944 |
| TF-IDF cosine, file paths removed | 0.909 | 0.902 |
| Logistic regression | 0.685 | 0.619 |

Per-pair scores:

| Repository | Cohort | Label | TF-IDF | Logistic |
| --- | --- | --- | --- | --- |
| pypa/packaging | v3 | conflict | 0.996 | 0.126 |
| psf/requests | fresh | conflict | 0.734 | 0.825 |
| pytest-dev/pluggy | fresh | conflict | 0.625 | 0.510 |
| urllib3/urllib3 | fresh | conflict | 0.605 | 0.820 |
| encode/httpx | fresh | conflict | 0.486 | 0.489 |
| python-attrs/attrs | v3 | clean | 0.435 | 0.448 |
| python-jsonschema/jsonschema | fresh | conflict | 0.330 | 0.408 |
| pallets/click | v3 | clean | 0.229 | 0.349 |
| pallets/itsdangerous | v3 | conflict | 0.182 | 0.059 |
| dateutil/dateutil | v3 | clean | 0.083 | 0.836 |

## What the numbers mean

The TF-IDF average precision of 0.948 is not a prediction result. The construction puts both tasks in a pair on the same module and test file, and the task text names that module and test file. Lexical similarity therefore restates the construction. All five fresh pairs are conflicts, so a model that scores the fresh wording higher gets a high rank without learning anything about conflict risk. One v3 conflict, itsdangerous, scores below three clean pairs.

Removing explicit file paths drops average precision from 0.948 to 0.909. The small drop says the score does not come only from the named paths. The pairs were also authored together, so wording similarity still restates how the tasks were built.

Logistic regression lands at the base-rate reference. The hand-crafted features add no usable signal here, and the fitted scores are unstable at this sample size.

The base-rate reference has an average precision of 0.700 because seven of ten pairs are conflicts. That is the class balance of this construction, not the prevalence of conflicts among arbitrary task pairs.

## Limits

- Ten pairs across ten repositories. The bootstrap intervals are wide and unstable.
- The two cohorts use different capture policies, and the v3 labels are post-hoc.
- The fresh cohort was designed to conflict, so the label distribution is not a base rate.
- The task text was written by the coordinator and delivered by one model.
- The prompts name the module and test file, which makes lexical overlap partly a leak of the construction.
- No timestamps or historical decisions exist, so a forward-time check is impossible.
- The private table cannot be rebuilt from the public repository alone.

## Next

1. Remove file and module names from the task text, then rescore. If the rank survives, wording carries signal beyond the named paths. If it collapses, the current score is a construction artifact.
2. Add a file predictor over the pre-start tree and compare it with the text-only score. The ten pairs have changed-path labels, so this step is ready.
3. Collect more pairs with both clean and conflict outcomes before claiming accuracy. The current set cannot support a train or held-out result.

## Reproduction

```sh
uv run --locked python scripts/build_controlled_prediction.py
uv run --locked python scripts/build_controlled_prediction.py --check
uv run --locked python scripts/run_controlled_predictions.py
uv run --locked python -m unittest tests.test_controlled_prediction -v
```

The builder reads the frozen plans and the published labels. The private plans must exist for these commands to run.
