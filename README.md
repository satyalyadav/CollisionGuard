# CollisionGuard

CollisionGuard studies whether task descriptions and repository information available before coding can predict textual Git merge conflicts between two AI coding tasks. The intended use is deciding which tasks to run together.

- [Project progress log](PROGRESS.md), with completed work, decisions, evidence, and planned next actions.
- [Original proposal snapshot](docs/proposal/original-proposal.md). Public copy with student IDs removed. Keep the proposal content fixed.
- [Research findings and next steps](docs/research/overview.md). This is the evolving assessment, separate from the original proposal.
- Detailed research on [prior work and novelty](docs/research/prior-work-and-novelty.md), [data and labels](docs/research/data-and-label-feasibility.md), and [evaluation](docs/research/evaluation-and-experiments.md).
- [Research automation and ASU Sol](docs/research/research-automation.md), with options for later experiment runs.
- [Exploratory pilot results](docs/pilot/results.md), with the [protocol](docs/pilot/protocol.md). Opus review is complete; primary historical-evidence collection remains unfinished.
- [Alternative data-source search](docs/research/data-source-search.md), reviewed by Opus 5.5. ParallACT is the first import-audit candidate; reuse checks remain open.
- [Data-source audit and verdicts](docs/research/data-source-audit.md), reviewed by Opus 5.5, with complete-tree replay evidence and explicit reuse conditions.

The audit reproduced selected benchmark merge outcomes. A complete training dataset has not been validated, and no model has been trained.

## Start here

Clone this repository, read the progress log, then follow the linked research and audit reports. The retained JSON files contain audit metadata and outcomes, not a complete training dataset. Raw third-party patches and the private proposal copy are excluded from Git. Local paths in past run records describe the original research machine.

For local development, install Python 3.10 or newer, Git, and [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
```

These tests check local sampling and replay helpers using small fixtures. They do not train a model or validate a dataset. The historical replay protocol pins Git 2.43.0; review that requirement before running new evidence collection. Audit scripts may download external data when invoked directly.

No project-wide reuse license has been selected. Third-party materials retain their own terms; public access to this repository does not relicense them.
