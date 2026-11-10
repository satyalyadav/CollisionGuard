# CollisionGuard

CollisionGuard studies whether task descriptions and repository information available before coding can predict textual Git merge conflicts between two AI coding tasks. The intended use is deciding which tasks to run together.

- [Public task dataset](data/parallact-12/README.md): twelve verified task pairs and labels, ready to use after cloning. Includes source credits, component licenses and an offline verification command.
- [Successful resource recovery](docs/pilot/parallact-recovery-results.md): the replay evidence behind those twelve pairs. See the [record format](docs/data/local-record-format.md).
- [Project progress log](PROGRESS.md), with completed work, decisions, evidence, and planned next actions.
- [Original proposal snapshot](docs/proposal/original-proposal.md). Public copy with student IDs removed. Keep the proposal content fixed.
- [Research findings and next steps](docs/research/overview.md). This is the evolving assessment, separate from the original proposal.
- Detailed research on [prior work and novelty](docs/research/prior-work-and-novelty.md), [data and labels](docs/research/data-and-label-feasibility.md), and [evaluation](docs/research/evaluation-and-experiments.md).
- [Research automation and ASU Sol](docs/research/research-automation.md), with options for later experiment runs.
- [Exploratory pilot results](docs/pilot/results.md), with the [protocol](docs/pilot/protocol.md). Opus review is complete; primary historical-evidence collection remains unfinished.
- [ParallACT local pilot](docs/pilot/parallact-results.md), reviewed by Opus 5.5. Seven new pairs replayed; the frozen coverage gate failed because the sample included unsupported v2 runs and one whitespace false negative.
- [V1-only follow-up pilot](docs/pilot/parallact-v1-results.md), reviewed by Opus 5.5. All twelve task/output associations passed; four merge replays completed. Local archive limits caused the failed gate. The collector needs fixes before reuse.
- [Alternative data-source search](docs/research/data-source-search.md), reviewed by Opus 5.5. ParallACT is the first import-audit candidate; see the later reuse assessment and pilot below.
- [Data-source audit and verdicts](docs/research/data-source-audit.md), reviewed by Opus 5.5, with complete-tree replay evidence and explicit reuse conditions.

The [ParallACT reuse assessment](docs/research/parallact-reuse-terms.md) recommends a bounded local research and training pilot with unresolved rights documented. The later [public-release assessment](docs/research/parallact-public-release.md) recommends a curated task-and-label release with the existing license conditions and source notices. The full local workspaces remain excluded from Git.

The recovery produced a small dataset ready for baseline development, now released in `data/parallact-12/`. It reuses the twelve known v1 cases with corrected resource limits; it is not a fresh sample or evidence of prediction accuracy. Broader data and evaluation remain necessary. No prediction results have been established.

## Start here

Clone this repository and read [the dataset guide](data/parallact-12/README.md) to use the twelve task pairs. Run `python3 scripts/export_parallact_release.py --verify` to check the public bundle without dependencies or network access. Full third-party run outputs, patches, the private proposal copy and `data/private/` remain excluded from Git. Original local records live in `data/private/parallact/recovery/`. Local paths in past run records describe the original research machine.

For local development, install Python 3.10 or newer, Git, and [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
```

Run the starting prediction methods on the public twelve-pair dataset, or explicitly choose the invented examples:

```sh
uv run --locked python src/run_baselines.py
uv run --locked python src/run_baselines.py --synthetic
```

The runner keeps each evaluation repository out of training and fits text weights on training tasks only. It reports unsupported folds rather than inventing scores. These small runs check the workflow; they do not establish prediction accuracy.

Tests cover sampling, replay helpers and prediction methods using fixtures. The historical replay protocol pins Git 2.43.0; review that requirement before new evidence collection. Audit scripts may download external data when invoked directly.

No project-wide reuse license has been selected. Third-party materials retain their own terms; public access to this repository does not relicense them.
