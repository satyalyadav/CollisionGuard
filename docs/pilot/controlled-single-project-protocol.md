# Controlled single-project source-subtree pilot

This document describes the protocol actually used for v3. Root updated these execution identifiers after collection. The immutable plan and prompts, rather than this edited account, establish what was frozen before the coding runs.

## Purpose

This pilot checks whether ten DeepSeek coding runs can produce complete, replayable task outputs from five pinned public repositories when every run starts from one CollisionGuard parent snapshot. It is a controlled construction for local research. The prompts are researcher-authored exercises, not reports of known defects or evidence of prediction accuracy. No coding output existed when the plan was frozen.

The earlier five-project pilot could not delegate from the root thread because T3 rejected a `target.projectId` for those source projects with "A local task runs in this thread's project". This protocol removes that dependency. One parent anchor holds all five upstream trees, and T3 creates each child worktree from the anchor inside the existing CollisionGuard project. No source project is registered, no top-level thread is created, and no child checkout is made in the shell.

## Parent anchor

The anchor is a local private ref in the existing CollisionGuard Git object database. Its tree contains:

- CollisionGuard's unchanged tracked HEAD tree.
- Each pinned upstream tree at `controlled_sources/<repo_id>/`.
- The recorder at `scripts/controlled_single_project.py`.

| repo | upstream commit | upstream tree |
| --- | --- | --- |
| pallets/click | `e38188e9e205005d5af5f9e59df51904c984586a` | `9f278790733eb087a591b95189e188094c3ac14f` |
| pallets/itsdangerous | `672971d66a2ef9f85151e53283113f33d642dabd` | `ef4287f82d8234404b58c7b29d38197e1f38e207` |
| python-attrs/attrs | `2a1fb86d44816afcc60e86d57956ce3604820326` | `f03d83ddabaad2ea3700f305b96db2240843f46d` |
| pypa/packaging | `5a7d3386d2777180a381eb947f21293124ce8df5` | `85c13f4c4e3eda5334b389b1501e1995727ff685` |
| dateutil/dateutil | `a78cbd81d5d03b5f126eb36edb92bca78972c804` | `da9176cc76597098f4b2927996f52d3b8cf0b9aa` |

Anchor ref `refs/research/controlled-single-project-2026-11-16-v3` resolves to commit `b40b3dced15f1f5a83593c42e3860ec24e3291cf`, tree `e1a019b7989a568d63b93580283ceed2475d5513`, parent `35e903769755c6f6f601b4b3eaa933f288c920a7`. The producer blob is `5bc9ff9ad5c44de7443753994f5e772a4c7621b6`, SHA-256 `6db73a1848df85b1e0ffb303cc3957e6ae58decfc7c17c544d388a71c57a9386`.

The builder imports source objects from the existing local clones with `git fetch --no-tags --no-write-fetch-head`. It builds the tree with a temporary `GIT_INDEX_FILE`, `read-tree --prefix`, `update-index`, `write-tree`, and `commit-tree`, then creates the private ref with a zero old-value guard. It does not switch branches, write the original index, or create a child checkout. Every source subtree was read back and equals its pinned upstream tree exactly. Each subtree keeps the upstream license and notice files.

The anchor commit is a CollisionGuard snapshot, not an upstream commit. Records keep parent snapshot IDs and original upstream IDs in separate fields.

## Model and launch

All ten coding tasks use the same selection: provider instance `opencode`, model `opencode-go/deepseek-v4.1-flash`, option `variant: max`, reasoning effort `max`, service tier `default`. Fast mode and priority processing are off. The coordinator is the root thread, which launches one child at a time.

A child is launched with T3 `delegate_task`, `isolation: "worktree"`, and no `target.projectId`. T3 creates the worktree from the parent anchor. Root records the returned live task metadata through the recorder. A task counts as started only when the returned metadata carries a run id and a started status. The existence of a snapshot file never implies a start.

Root switches the parent checkout to the anchor before launching and restores the original branch afterward. Untracked and ignored files are preserved. Root does not run `git clean`, `git reset --hard`, or `git stash`.

## Isolation and capture

Each prompt names one source prefix, `controlled_sources/<repo_id>`, and its upstream commit and tree. It contains no partner task, pair membership, other prompts, expected overlap, task objective beyond its own acceptance text, or solution. The child may read contribution guidance inside its own subtree only and must not read sibling sources or the private evidence root.

The first tool action must run the recorder's `capture` command. That action records the parent HEAD, tree, index tree, branch, status, untracked and ignored paths, the assigned subtree hash, a full source inventory with SHA-256 per file, and any path changed outside the prefix. The source subtree must equal the pinned tree, the worktree and index must be clean at start, and no path outside the prefix may differ. A dirty start, missing or mismatched subtree, or out-of-scope path blocks labels.

This is a first-action capture before mutation, not a host pre-model hook. The record says so.

The source directories have no independent `.git`. Git context is the combined parent, so branch names, index state, and repository metadata belong to CollisionGuard. This is a controlled setup limitation. Task work is judged only through the assigned prefix and source-relative patches.

## Collection and replay

Collection stages the entire final worktree through an alternate index with `git add --all --force`, so new, binary, symlink, ignored, and executable-mode files all enter the captured tree. It then:

- Diffs the final full tree against the parent tree and blocks any change outside the assigned prefix, including new empty directories.
- Extracts the final source subtree and writes a binary-capable patch relative to the original upstream tree. Patch paths are upstream paths without the `controlled_sources` prefix.
- Keeps generated and scratch files inside the patch and flags known artifact paths instead of removing them.
- Replays the complete source patch twice in fresh temporary repositories against the pinned upstream tree. Each replay must recreate the captured final source subtree exactly.
- Records the final index tree, final working tree, source tree, patch bytes and hashes, changed paths, inventories, and command transcripts separately.

A pair is replayed only when both starts share the same original source tree and parent snapshot, both live run records confirm a start, both outputs exist and are nonempty and distinct, both patch replays match, HEAD did not move, and the time budget and provenance checks pass. Git 2.43.0 runs `merge-tree --write-tree` twice from side commits that share the pinned upstream commit as parent. Only identical repeats label a pair: exit 0 is `clean`; exit 1 with a conflict report is `conflict`. Errors, timeouts, missing evidence, differing repeats, empty or identical outputs, unequal starts, source drift, out-of-scope edits, and provenance contradictions stay unlabelled.

Every pair stays in the denominator of five, and every task stays in the denominator of ten, including missing outputs. The feasibility gate passes only if all five pairs are attempted and at least three pairs across at least three repositories qualify. It is not evaluated before all five are attempted.

## Budgets and limits

Each child is asked to finish within 480 seconds. T3 does not enforce that target, so the record keeps the instruction separate from measured duration. Dependency preparation is limited to 300 seconds and one focused test command to 180 seconds. Tests run in a task-specific virtual environment outside the source tree, with `PYTHONPATH` pointed at the assigned source subtree and an import-path check recorded before the test command. The work uses one child and one heavy shell job at a time.

The private evidence root is `data/private/research/controlled-single-project-v3/`, outside every child worktree. It holds prompts, the plan, live run records, captures, final patches, replay records, job logs, and anchor provenance. Fixture tests use a separate namespace and cannot write there. No prompt text, source patch, or transcript is public. No model training, upstream submission, push of third-party code, or final-test claim is part of this pilot.

## Reproduction and current state

The recorder, tests, protocol, and results are new files. The old pilot plan, recorder, tests, datasets, protocols, results, and captured attempts are unchanged. The plan and prompts were frozen before any coding launch: plan SHA-256 `a3c17bee0d254a1490e454ac8d630119463b4aa5e2a147af70212a2107dfc9fc`, run id `csp-run-20261116-2ef8b5`.

Fixture tests cover anchor construction without touching the original branch or index, subtree equality, dirty and unequal starts, missing subtrees, out-of-prefix edits, new binary and executable files, artifact retention, real two-repeat source replay, clean and conflict merge labels, empty and error labels, live-metadata starts, and evidence namespace isolation. They pass with `python3 -m unittest tests.test_controlled_single_project -v`.

At the v3 freeze, 2026-11-16T02:57:24.297Z, no coding child had started. All ten subsequently completed. The results document separates the frozen full-directory target from the supplementary Git-visible diagnostic defined after inspecting artifacts. These five repositories are development examples, with no held-out test claim.


## Recorded execution limits and amendments

Root corrected the provider identifier and UTC deadline logging before any coding output, then rebuilt the anchor and froze v3. Earlier v1 and v2 plans remain private evidence and did not produce these coding runs. The v3 producer is unchanged throughout collection. The 17 original setup fixtures passed; three relevant amended fixtures passed after the binding and logging corrections.

The 480-second task duration is a prompt target checked against actual T3 start and completion metadata, not a host-enforced kill deadline for a model session. Recorder shell commands have process-group deadlines. Dependency and test retries occurred and remain in the job records. A passing duration gate does not prove that each task obeyed the requested single-test-run instruction.

T3 prepends an implementation-role instruction and trims terminal whitespace. Root checked the two Click task bodies against actual first user messages after accounting for that envelope. This transport check was retrospective and does not establish a byte-for-byte audit of every runtime prompt. Sibling source visibility is restricted by instructions, without a filesystem sandbox.

The frozen collector force-includes ignored files. Its raw labels therefore answer whether complete captured directories merge, including caches and bytecode. They are retained exactly as produced and are unsuitable as ordinary Git-change training targets. A separately named post-hoc diagnostic uses ordinary Git staging from the pinned tree and keeps repository content, docs, tests and nonignored scratch files. It is development analysis, not a replacement primary label or a prospective validation. Its method, producer and evidence are in the results and supplementary records. A future fresh cohort needs this capture policy frozen before generation.
