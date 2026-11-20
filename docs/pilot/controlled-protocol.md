# Controlled five-repository pilot

## Purpose

This pilot checks whether ten private coding runs can produce complete, replayable task outputs from five pinned public repositories. It records merge labels for five pairs that start from the same Git tree. Task prompts are researcher-authored exercises, not reports of known defects, examples of normal coding traffic, or evidence of accuracy. The pilot does not train a model or estimate how often real tasks conflict.

The runs use Claude Haiku 5.5 through Kiro for all ten coding tasks. The coordinator uses Codex gpt-6-luna with reasoning effort `max` and service tier `default`. Kiro runs use mode `vibe`, with no effort option. No other coding model is part of this pilot.

## Sources and pinned trees

GitHub's repository API was read at the time recorded in `data/controlled-pilot/repositories.json`. The API confirmed public visibility, default branch, star count, archive status, license metadata, and the pinned commit for each canonical repository. The worktree's commit tree, index tree, status, and extra-file lists were captured locally before any coding run.

The requested `python-dateutil/dateutil` API path returned 404. The current dateutil README identifies `dateutil/dateutil` as the repository that hosts the package and issue tracker, so the pilot records that explicit name resolution and uses its `master` branch. This is a canonical-name correction, not a replacement selected after seeing model output. GitHub reports `NOASSERTION` for the API license field on `pypa/packaging` and `dateutil/dateutil`; the source repositories contain their own license and contribution terms. Counts and metadata reflect the observation time only.

The source checkouts were created through T3's project clone control and registered as separate projects. Their auto-pull setting is off. Each project uses the Codex gpt-6-luna `max` / `default` project selection so it cannot inherit the cancelled Kiro Luna choice. Each coding run names its project ID and explicitly requests Kiro `claude-haiku-5.5` with `mode: vibe`.

## Task design and isolation

Each repository has two distinct, modest tasks written before any coding output. Prompts, prompt hashes, source commit and tree, model selection, task IDs, and pair IDs are frozen in the ignored private plan. Public files contain task identifiers and hashes, not prompt text. A child receives only its own task and repository. It must not inspect other checkouts, prompts, outputs, shared selection, or CollisionGuard evidence, and it must not delegate, commit, push, open a PR, or contact the repository.

The source contribution guidance was read before task selection. This includes the linked Pallets guidance for Click and ItsDangerous, the attrs contribution and AI policies, the packaging development and patch guides, and dateutil's `CONTRIBUTING.md` and `AGENTS.md`. These runs are private research artifacts, not submissions to those projects. No upstream interaction is authorized.

Each child starts in a separate worktree created by T3 from its registered source project. A synchronous project script records the worktree's HEAD, HEAD tree, index tree, full Git status, tracked index, untracked files, and ignored files outside the source checkout. The child's first tool action verifies the record and pinned commit. If the host startup hook did not run, the same first action captures the clean starting state before any edits and identifies that fallback in the record. A mismatch stops that task before code changes.

## Output capture and replay

The coordinator collects the entire final worktree tree, including staged changes, unstaged changes, new files, binary content, symlinks, and mode changes. It keeps scratch or generated artifacts in the recorded output and flags their paths. No output is cleaned up or amended after collection. The private output record includes the final working tree, final index tree when Git can write one, full patch bytes and SHA-256, changed paths, complete final-tree inventory, status, and the collection commands' exit codes and output hashes.

Each pair is replayed from its recorded base in a temporary Git repository that reads source objects without changing the source checkout. Git applies both full patches independently, and the resulting side trees must match the captured outputs. Git 2.43.0 runs `merge-tree --write-tree` twice. Only identical, recognized results can label a pair: exit 0 is `clean`; exit 1 with a conflict report is `conflict`. Errors, timeouts, missing evidence, differing repeats, or unknown output are unlabelled. Empty or identical outputs, unequal starts, source drift, provenance contradictions, or limit violations also block a label.

Every pair appears in the final public denominator, including pairs with no collected output. The private run record distinguishes a submitted task from a coding run confirmed started. A pair counts as attempted only when both coding runs started; missing outputs or replay evidence stay unlabelled and do not disappear from the results.

## Budgets and task quality

Each child is asked to finish within eight minutes. T3 does not enforce that target, so records distinguish the instruction from measured run duration. The recorder kills a command's entire process group after its declared deadline. Targeted project tests have a three-minute limit; dependency preparation uses a separate bounded command. Tests run in task-specific virtual environments outside the source worktrees. The work uses one child and one heavy shell job at a time. No sudo, credentials, global package installs, containers, production services, or arbitrary extra repositories are allowed.

The task's test result is reported separately from its merge label. A failing task test does not automatically exclude a nonempty, provenance-valid output from replay. A clean merge label means only that Git replayed both outputs without a textual conflict.

## Feasibility gate and limits

All five pairs must be attempted. The gate passes only if at least three pairs across at least three repositories have equal verified starts, separate nonempty outputs, identical repeated full-tree replay, and no provenance contradictions or budget violations. It does not require both labels and does not select cases based on outcomes. Failure of the gate leaves all attempted and excluded rows in the denominator.

The records keep provider usage fields when the provider exposes them. Missing token or credit fields remain unavailable; no monetary cost is inferred. T3 clone controls do not return network transfer counts, so the private source record reports local checkout and Git object storage, with transferred bytes marked unavailable. The coordinator stops launching children at 2026-11-16T00:27:41Z UTC and keeps partial evidence if the limit is reached.

Private prompts, source facts, raw transcripts, worktree snapshots, complete patches, job logs, provenance records, and feature-target joins live under ignored `data/private/research/controlled-pilot/`. Public results expose source facts, hashes, task status, replay labels, and the feasibility gate. Third-party code and task outputs remain local pending separate reuse review.
