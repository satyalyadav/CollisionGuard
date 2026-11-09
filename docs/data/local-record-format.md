# Local task-pair records

The [recovery report](../pilot/parallact-recovery-results.md) identifies the private files that are ready for model development. Raw records are stored locally under `data/private/parallact/`, which Git ignores. The ready files are `data/private/parallact/recovery/features.json` and `targets.json`. Older cache paths are compatibility symlinks to this durable storage, not extra copies or backups. Teammates cloning the public repository do not receive these files.

The [public-release assessment](../research/parallact-public-release.md) recommends a curated release of the twelve task pairs and calculated labels with the specified licenses and notices. The local storage path remains ignored; no raw records were uploaded during that investigation.

Each feature record describes one pair and contains only these fields:

| Field | Meaning |
| --- | --- |
| `instance_id` | Join key for features and labels; exclude it from predictors. |
| `repo` | Source repository and future split group. |
| `base_commit` | Benchmark starting commit used for replay; a context/group key, not a predictor. |
| `task_a` | Initial task assigned to agent A. |
| `task_b` | Initial task assigned to agent B. |

The separate target record has the same `instance_id`, a completed verification status and a `label` of `clean` or `conflict`. A conflict means `git merge-tree` returned exit status 1. This includes content conflicts and structural conflicts such as modify/delete or rename conflicts. A clean merge does not prove the combined program works.

Only pairs with checked assignments, exact base trees, independently applied agent patches and repeatable merges belong in the ready dataset. Feature and target IDs must match exactly, with no duplicates. Excluded or unfinished cases stay in the audit records; they are never assigned a clean label.

For model experiments, join on `instance_id` and keep repositories separate across training and evaluation. Exclude `instance_id` and literal `base_commit` hashes from model predictors; they identify and group records. Related task variants and repeated attempts must stay together. Fit text processing on training data only. Repository grouping can leave too few examples for a reliable evaluation; report that limitation rather than relaxing the split silently.

Keep family names, reference solutions, actual patches, changed-file lists, tests, merge output and other evaluation fields out of predictors. The current export contains no file-prediction targets. Completed changes can supply those separate training targets in future work. These controlled examples support development and feasibility checks; they do not establish real-world conflict rates or prediction accuracy.
