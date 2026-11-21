# File predictor on the ten constructed pairs

This run tests the path-only predictor merged from PR 2 on the ten pairs built by this project. It asks whether ranking repository file paths from a task description finds the files each task changed, whether the overlap between two ranked lists predicts the merge label, and whether that overlap improves the task-text baseline. Ten pairs cannot establish accuracy. The run is a construction check and a baseline for a better predictor.

## Data and method

- Ten pairs across ten repositories, with three clean and seven conflict labels.
- Task text comes from the frozen plans. The full table stays in the ignored private data root.
- File lists come from each repository's pinned tree at the cohort anchor, read with `git ls-tree`.
- The predictor ranks every file path by character n-gram TF-IDF similarity to the task text. It returns the top five files for each task.
- Predicted overlap is the Jaccard similarity of the two top-five lists.
- Actual overlap is the Jaccard similarity of the two changed-file sets.
- The path-stripped run removes path-like tokens such as `src/module.py` from the task text before ranking.
- Text scores are the existing leave-one-repository-out TF-IDF scores from the prediction check.
- Blends add the path overlap to the text score with fixed weights. They are not tuned.

Public results: [file-predictor.json](../../data/controlled-prediction-10/file-predictor.json). Table SHA-256: `d2d3557815b9fc9d03eb30ee50a89bbea5d55e1686948327c92e41fdb6aae4fe`.

## Results

| Measure | Value |
| --- | --- |
| Mean recall at 5, raw task text | 0.621 |
| Mean recall at 5, paths removed | 0.296 |
| Mean conflict-path recall, raw | 0.643 |
| Predicted overlap AP | 0.819 |
| Actual overlap AP (oracle) | 0.860 |
| Text-only AP | 0.948 |
| Equal blend AP | 0.933 |
| Text-heavy blend AP | 0.948 |
| Path-stripped overlap AP | 0.768 |

The `overlap > 0` rule flagged nine pairs using the unfiltered top-five lists. All seven conflicts were among them, along with two clean pairs, so it missed no conflict and produced two false positives on this set. Applying the existing overlap helper's default 0.1 similarity cutoff flags four of seven conflicts and the same two clean pairs.

Per-pair values:

| Repository | Label | Predicted overlap | Actual overlap | Recall at 5 | Conflict recall | Stripped overlap | Stripped recall |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pallets/click | clean | 0.00 | 0.20 | 0.00 | n/a | 0.00 | 0.00 |
| pallets/itsdangerous | conflict | 0.25 | 1.00 | 0.67 | 0.00 | 0.25 | 0.67 |
| python-attrs/attrs | clean | 0.25 | 0.00 | 0.12 | n/a | 0.25 | 0.12 |
| pypa/packaging | conflict | 1.00 | 1.00 | 0.33 | 0.00 | 1.00 | 0.33 |
| dateutil/dateutil | clean | 0.67 | 1.00 | 1.00 | n/a | 0.67 | 1.00 |
| pytest-dev/pluggy | conflict | 0.67 | 0.67 | 0.83 | 1.00 | 0.43 | 0.83 |
| psf/requests | conflict | 0.67 | 1.00 | 0.75 | 1.00 | 0.43 | 0.00 |
| encode/httpx | conflict | 0.67 | 1.00 | 1.00 | 1.00 | 0.25 | 0.00 |
| urllib3/urllib3 | conflict | 0.25 | 1.00 | 0.50 | 0.50 | 0.11 | 0.00 |
| python-jsonschema/jsonschema | conflict | 0.25 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 |

## What the numbers mean

The path-only predictor finds about 62 percent of the files each task changed when the task text is left intact. That is useful as a rough file router, but it is not enough for a conflict warning.

The predicted overlap ranks conflicts worse than the text score alone, 0.819 against 0.948. Adding it to the text score does not help. The equal blend falls to 0.933, and the text-heavy blend stays at 0.948.

Removing explicit paths drops mean recall from 0.621 to 0.296. The ablation removes 20 path tokens from the five fresh statements and none from the earlier five, so this pooled drop mixes a changed fresh cohort with an unchanged earlier cohort. The predictor leans heavily on the task naming the file. For requests, httpx, urllib3 and jsonschema, recall falls to zero once the paths are removed, because the remaining words do not match the path text.

File overlap is also not the same as conflict. Dateutil is clean even though both tasks changed the same files (actual overlap 1.00) and the predictor saw substantial overlap (0.67). Packaging is a conflict with full predicted and actual overlap. Itsdangerous and packaging conflict in changelog files that the predictor never ranks, and packaging also misses the conflicting `tests/test_utils.py` in its top five, so conflict-path recall is zero for both.

The `overlap > 0` rule looks good on this set, but seven positives and two false positives are too few to trust. It is a screening idea, not a result.

## Limits

- Ten pairs, one model, constructed labels. The fresh cohort was designed to overlap, and all five fresh pairs conflicted.
- The predictor sees only file paths, not file contents, imports or test names.
- Top five was chosen before the run and not tuned.
- The task text often names the target file, which makes the raw recall optimistic.
- The path-stripped run still leaves function names and module names in the text.
- No accuracy or held-out claim follows.

## Next

1. Give the predictor file contents or import relationships, not just paths. A task that names a function but not its file should still find the right file.
2. Test predicted overlap as a secondary feature with a proper repository-disjoint split and a larger sample.
3. Handle changelog and documentation conflicts separately. They are real merge conflicts but not coding targets.
4. Collect more pairs with a natural mix of clean and conflict outcomes before making a claim.

## Reproduction

```sh
uv run --locked python scripts/evaluate_file_predictor.py
uv run --locked python -m unittest tests.test_file_predictor_evaluation -v
```

The script reads the private table and the frozen plans, so those must exist locally.
