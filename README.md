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
- [Controlled single-project pilot](docs/pilot/controlled-single-project-results.md), with the [protocol](docs/pilot/controlled-single-project-protocol.md). Five repositories and ten coding tasks produced five verified common-start pairs. Ordinary Git staging gave three clean and two conflicts; this is construction evidence, not prediction accuracy.
- [Fresh single-project cohort](docs/pilot/fresh-cohort-results.md), with the [protocol](docs/pilot/fresh-cohort-protocol.md) and [public summary](data/controlled-fresh-2026-11/summary.json). Five new repositories, ten tasks, ordinary Git staging frozen before coding. All five pairs qualified and conflicted; both tasks in each pair touched the same module and test file, so this is not a base rate.
- [First prediction check](docs/pilot/controlled-prediction-results.md) on the ten constructed pairs, with the [public summary](data/controlled-prediction-10/summary.json) and [scores](data/controlled-prediction-10/results.json). TF-IDF ranks most conflicts high, but the construction and task text both name the target module and test file, so the score cannot be separated from the construction. Logistic regression lands below the no-skill AP. This is a pipeline check, not accuracy evidence.
- [File predictor check](docs/pilot/file-predictor-results.md) on the same ten pairs, with the [public results](data/controlled-prediction-10/file-predictor.json). The path-only predictor finds about 62 percent of changed files, but its overlap score is below the text-only score and adds nothing to the blend. Removing explicit paths drops recall to 30 percent. It also misses changelog conflicts.
- [Controlled five-project pilot](docs/pilot/controlled-results.md) and [SWE-rebench analysis](docs/research/swe-rebench-verification-2026-11.md), plus the [broader data search](docs/research/broader-data-search-2026-11.md) and [agent-log verification](docs/research/agentlogs-verification-2026-11.md). These record why the project chose constructed pairs over reuse of existing corpora.
- [Natural-mix cohort](docs/pilot/natural-cohort-results.md), with the [protocol](docs/pilot/natural-cohort-protocol.md), [public summary](data/natural-cohort-2026-11/summary.json) and [text results](data/natural-cohort-2026-11/results-title.json).
- [Product prototype](docs/product/README.md) and [model card](docs/product/model-card.md). A CLI ranks two tasks by merge-risk before coding, using task types, repository metadata and agent pairing. Repository-grouped CV AUC is 0.648; the top 10 percent band has a 46.3 percent conflict rate against a 22.1 percent base. The closer issue-title transfer check is 0.582. Treat it as triage, not a guarantee.
- [Hugging Face-ready cohort export](data/natural-cohort-2026-11/hf/README.md): 673 pairs with labels, metadata and fixed repository-grouped folds. Task text stays out; join AIDev by repository and PR number. Real co-active AI-agent PR pairs from a CC-BY replication package; outcomes were not designed by this project. On 666 pairs, PR titles alone give AUC 0.524, essentially chance, and the constructed cohort's 0.948 AP does not transfer. The path-only file predictor on 652 pairs reaches overlap AUC 0.553 against text 0.525; the fixed blend gains 0.014 AP with a paired interval of -0.014 to +0.047. On the 165-pair strict-issue subset, overlap is a below-0.5 point estimate and the blend does not improve on text. The cohort therefore challenges the model: no reliable gain from file overlap, and the actual-path reference is low. An accuracy claim still does not follow.

The [ParallACT reuse assessment](docs/research/parallact-reuse-terms.md) recommends a bounded local research and training pilot with unresolved rights documented. The later [public-release assessment](docs/research/parallact-public-release.md) recommends a curated task-and-label release with the existing license conditions and source notices. The full local workspaces remain excluded from Git.

The recovery produced a small dataset ready for baseline development, now released in `data/parallact-12/`. It reuses the twelve known v1 cases with corrected resource limits; it is not a fresh sample or evidence of prediction accuracy. The controlled single-project pilot adds five verified common-start pairs built from pinned public repositories, and shows that capture policy changes the labels. A first prediction check joins the two constructed cohorts into ten pairs and scores them under leave-one-repository-out folds. Its only public artifacts are counts, hashes and scores; the task text stays private. Broader data and evaluation remain necessary. No prediction accuracy has been established.

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
