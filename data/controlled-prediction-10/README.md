# Controlled prediction check: public files

This folder holds the public side of the ten-pair prediction check. The full table, including task text and changed paths, stays in the ignored private data root because the pilot protocols keep prompts out of the public repository.

- `summary.json` reports the pair count, label counts, cohort counts, repository names and input hashes.
- `results.json` reports per-pair scores and aggregate metrics. It contains no task text and no local paths.
- `file-predictor.json` reports file-prediction recall, overlap scores and blend scores for the path-only predictor. It contains no task text, no predicted file lists and no local paths.
- The method, results and limits are in [the report](../../docs/pilot/controlled-prediction-results.md) and [the file-predictor report](../../docs/pilot/file-predictor-results.md).

The table covers five controlled-v3 pairs (3 clean, 2 conflict) and five fresh-cohort pairs (all conflict). Ten pairs cannot establish prediction accuracy. The scores check the workflow only.

Rebuild and run locally:

```sh
uv run --locked python scripts/build_controlled_prediction.py
uv run --locked python scripts/run_controlled_predictions.py
```
