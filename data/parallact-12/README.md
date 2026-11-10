# Twelve verified ParallACT task pairs

This small public bundle gives teammates the task descriptions and locally computed Git merge labels needed to develop CollisionGuard baselines. Clone the repository to get the data. No private files, account or download step is needed to read or verify this bundle.

- `features.json` contains twelve records with `instance_id`, `repo`, `base_commit`, `task_a` and `task_b`.
- `targets.json` contains the same twelve IDs, each with `status: complete` and a `clean` or `conflict` label.
- `provenance.json` records the website sources, matching pinned seed sources, hashes and component terms. It is audit information, not model input.
- `licenses/` contains full license texts, pinned upstream declarations and their source URLs. [LICENSE.md](LICENSE.md) explains their scope.

To check the released bytes and their agreement with the recorded task hashes and replay outcomes, run from the repository root:

```sh
python3 scripts/export_parallact_release.py --verify
```

This check uses only the standard library and local public files. It does not rerun the agent tasks or merge replays. Maintainers with the original local records can regenerate the JSON and checksum inventory with `python3 scripts/export_parallact_release.py`. The default export uses the ignored recovery directory and requires the bundled license files to exist.

## What the labels mean

The [recovery](../../docs/pilot/parallact-recovery-results.md) produced seven clean and five conflict labels across eight repositories. Each accepted case has an exact reconstructed base tree, two independently applied agent patches and two identical Git merge results. `conflict` means Git could not merge the two changes automatically, including content, rename and modify/delete conflicts. `clean` does not establish functional correctness.

These are the same twelve cases recovered after changing resource limits. They are a development set, not a fresh blind sample. Runner and website source revisions remain unknown. Twelve examples cannot establish model accuracy or real-world conflict rates. Keep repositories separated during evaluation and fit text processing on training data only. IDs, base SHAs and audit fields are not predictors. The feature export contains no file-prediction targets.

## Attribution and changes

The task text is as presented in the [ParallACT explorer](https://lingyunxiao18.github.io/ParallACT/explorer.html). Credit Rishabh Mediratta, Lingyun Xiao, Peter Stone, Joydeep Biswas and Elias Stengel-Eskin, [ParallACT](https://lingyunxiao18.github.io/ParallACT/) and its [paper](https://arxiv.org/abs/2611.00314). Task A derives from SWE-bench Pro. Credit Scale AI and [SWE-bench Pro's pinned dataset card](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro/blob/2d52cb3df914a3fcf80c7f66738b3a88ae37fc50/README.md), together with the upstream repositories linked per record.

CollisionGuard selected these twelve pairs, checked matching task wording against pinned seeds and website prompts, removed execution-prompt prefixes, stripped outer whitespace and added its own Git labels. No substantive task wording was rewritten. Each `task_sha256` is SHA-256 of the released UTF-8 task string after `strip()`. The verified local originals remain unchanged.

The collection and CollisionGuard's contributions use CC BY-SA 4.0. Component terms and notices remain in force. The [release assessment](../../docs/research/parallact-public-release.md) explains our interpretation of the website license and its limits. This release implies no endorsement and claims no rights beyond those the licensors supply. Agent patches, trajectories, source archives and research logs are not included.
