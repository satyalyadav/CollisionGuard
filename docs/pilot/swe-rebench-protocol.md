# SWE-rebench import and replay pilot protocol

The initial protocol was frozen on 15 November 2026 UTC, before any new patch or outcome was read. Later amendments and review corrections are dated below; they were not all prospective. The implementation is [scripts/swe_rebench_pilot.py](../../scripts/swe_rebench_pilot.py). The background is in the [SWE-rebench verification](../research/swe-rebench-verification-2026-11.md) and the [local record format](../data/local-record-format.md).

## Purpose and non-claims

The pilot checks whether SWE-rebench tasks and released OpenHands trajectories can be imported into the same pair records as the ParallACT data, with the same replay rules. It makes no semantic, scheduling or predictive claim, trains nothing and selects no final test set. Every task and repository that this pilot actually samples is a development case. The metadata inventory of 76 candidate repositories does not assign the other repositories to development.

## Inputs and pins

- Task catalog [nebius/SWE-rebench at revision 89cdfbab4ab1bd8f5a658bb212d1b63624f4f881](https://huggingface.co/datasets/nebius/SWE-rebench/tree/89cdfbab4ab1bd8f5a658bb212d1b63624f4f881). Retained catalog metadata (21,336 task IDs, repository, base) came from that revision.
- Trajectories [nebius/SWE-rebench-openhands-trajectories at revision 35455389ab51bf5e2306bfd436ef72d0f98bf882](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories/tree/35455389ab51bf5e2306bfd436ef72d0f98bf882). Retained trace IDs (67,074 rows, 6,306 distinct tasks) came from that revision.
- Exact records come from the dataset viewer `/rows` endpoint at row offsets derived from the retained ordered ID lists. The viewer is mutable and not tied to the pin. The collector verifies instance ID, repository and base commit against the pinned catalog, and the trace instance ID against the pinned trace ID list. It retains and hashes every response. Other payload fields (problem statement, patch, trajectory) are not checked against pinned Parquet bytes. This pin limit is reported in the results.
- Git 2.43.0 is required. The collector refuses to label under any other version.

## Primary rules (unchanged)

1. The task text and pre-start repository information are the only prediction inputs.
2. The two tasks are genuinely distinct instance IDs with different problem statements.
3. Each output is the final patch of one released trace, produced without the partner plan or any communication. The collector checks that neither trace's prompt contains the partner instance ID or partner problem statement and that each trace has one user message.
4. The common initial repository snapshot is verified identical for both tasks. This needs the shared declared base commit, a verified tree and static evidence about the images that ran the tasks (below).
5. A label is `conflict` when Git 2.43.0 `merge-tree --write-tree` exits 1 (content, rename/delete, modify/delete or other conflicts) and `clean` when it exits 0 twice with identical output. Any error, unknown exit status, patch failure or unrepeatable result has no label and is never clean.
6. Released patches are retained byte for byte, including `.openhands/TASKS.md` and scratch files. Replay uses only the documented final-line-feed normalization below. No filtered replacement labels are made. No gold, reference or reconciliation patch is used as an agent output.
7. If harness-only artifacts (paths under `.openhands/`) cause every conflict in a pair, the pair has no primary label, the raw Git result is kept as a diagnostic, and the pilot recommends stopping expansion. It is never presented as task-only risk.

Review correction: rule 7 records the implementation's narrower rule, not the broader coordinating brief, which required stopping expansion if harness-only artifacts caused a conflict. The reproduction-script instructions also induce scratch files. The observed scratch-only conflicts therefore support stopping expansion even though the `.openhands/` path check returned zero. This correction changes no retained Git label and does not introduce a source-only replacement label.

## Case selection

Six cases in total.

1. Development control: `aio-libs__yarl-1413` and `aio-libs__yarl-1414`, chosen earlier by repository/base order. Its inputs were inspected before this protocol. Its outcome has not been replayed or known. It is excluded from the expansion gate.
2. Five fresh cases, one candidate pair from each of five other repositories, chosen as follows.
   - Candidate pairs are all unordered pairs of distinct task IDs that share a case-folded repository and exact base commit and both have at least one released trace (144 pairs, 121 groups, 76 repositories in the retained inventory).
   - Excluded repositories (actually inspected before): the eight ParallACT repositories (`NodeBB/NodeBB`, `ansible/ansible`, `flipt-io/flipt`, `future-architect/vuls`, `gravitational/teleport`, `internetarchive/openlibrary`, `navidrome/navidrome`, `protonmail/webclients`), `element-hq/element-web`, `dottxt-ai/outlines`, `stanfordnlp/dspy`, `connectbot/connectbot`, `ARMmbed/mbed-tools`, `PlasmaFAIR/sdf-xarray`, `aio-libs/yarl`, `apache/cassandra`, `apache/hive`, `jdbi/jdbi`, `apache/maven`, `apache/maven-release`, `mongodb/mongo-java-driver`. Matching is case-insensitive.
   - Pair key: the two instance IDs sorted, joined by a newline. Pair hash: SHA256 of `572\n` followed by the pair key (seed constant 572).
   - Each remaining repository contributes its pair with the smallest pair hash. The five repositories whose contributed hashes are smallest are the fresh cases, in ascending hash order.
   - No replacement. A case that cannot be collected stays in the denominator as an access or capacity exclusion.
3. For each task the trace is the first stored trace row (lowest row offset) with that instance ID, chosen without reading success or failure labels.

The selection is written to `data/swe-rebench-pilot/selection.json` by `select` before any new row, patch or image is fetched.

## Layered evidence

Each case keeps three separate groups of fields. They never overwrite each other.

- Declared-base diagnostics. Archive the exact declared commit from GitHub, rebuild its Git tree from archive bytes, compare with the tree identity that the GitHub commit API reports, apply each patch independently to that tree, and run `merge-tree` twice. This proves replay relative to the declared base, not equality with the original runtime starting tree. Results stay when image evidence is incomplete.
- Published-snapshot evidence (static). Resolve each task image tag to an immutable OCI digest. Retain manifest, config, history and push-date evidence. Inspect layers as tar bytes only. Never pull or run a container, and never execute downloaded code. Show that the repository HEAD and tracked tree in each image equal the declared tree T, and account for overlay layers, whiteouts and the runtime workspace creation and reset. Both images must carry T, and tests must match T's file identities. Tracked setup or test differences exclude the pair from primary. Untracked extra files are recorded by path and hash before any other judgment, are left out of tracked-tree equality, and make the pair ambiguous only when they touch a path in either agent patch or test patch. The result is `published_snapshot_verified`.
- Original snapshot. `original_snapshot_verified` is true only with a source-bound association between the published image digest or version and the original run. Published-image evidence alone never sets it.
- Harness source. The collector retains the pinned OpenHands harness source that creates the workspace and generates the patch, when it can be found from the dataset card. If not found, that item is reported as unresolved.

An image that is missing, too large for the budgets or ambiguous means snapshot evidence is unavailable. If task, base, output and replay are independently valid, the declared-base diagnostic is kept with primary label null. A contradiction, patch failure or error also gives primary label null.

## Strict primary eligibility

All of these must hold: distinct tasks, matched IDs and prompts, independent nonempty outputs, shared declared base, tree verified against GitHub, twice-identical Git 2.43.0 replay, `published_snapshot_verified` true, `original_snapshot_verified` true, no contradictions, and no artifact-only conflict. The last two image conditions are not relaxed. If historical proof is unrecoverable the strict gate legitimately fails while declared-base diagnostics remain useful.

## Expansion gate (five fresh cases only)

Pass needs all of these: at least 3 strictly eligible primary pairs from at least 3 repositories, at most 1 access or capacity exclusion, no trace, image or preimage contradiction, and all limits respected. Both labels must appear before the sample is called ready for comparative training, and no case is added or dropped to balance classes. The pilot stops after six cases even if the gate passes and recommends expansion instead of starting it. If only published-snapshot or declared-base diagnostics pass, they are reported separately, and a later explicit decision on the evidence standard is needed.

## Limits

- Whole assignment 45 minutes. Network and collection scripts 30 minutes total. Fixture tests 3 minutes. One heavy job at a time, one replay worker, no autoscaling, no orphan or watchdog jobs. Each long script runs under `timeout -k` and logs owner, PID, start, deadline, purpose, checkpoint, end and exit code.
- New HTTP response-body budget 512 MiB total, 128 MiB per task image, 64 MiB per compressed layer or source archive. Decoded archive cap 512 MiB, member cap 64 MiB. Source metadata and run JSON cap 8 MiB per response. Partial, error and boundary-probe bytes count. Cached reads are counted separately and not charged again. A transfer stops at its cap.
- Anonymous public registry tokens and GETs only. No credentials, gated or private access, paid model API runs, container pulls or runs. No hooks, filters, builds, submodules, tests or agent code run.
- Unsafe paths, symlink traversal, unsupported modes, gitlinks and omitted archive entries are rejected as in the existing helpers.
- Checkpoints are atomic per case, so finished cases survive a later failure. After two material implementation failures, the work is replanned and logged before another attempt.

## Outputs

- `data/swe-rebench-pilot/` holds public facts only: selection, per-case statuses, hashes, labels and the summary. No task text, patches, trajectories or source archives.
- `data/private/research/swe-rebench-pilot/` (ignored) holds raw bodies, job logs, checkpoints and the budget ledger.
- Ready `features.json` and `targets.json` are written to the ignored private directory only for strictly qualified pairs, with matching IDs. Diagnostics go in a separate file.

## Amendments

- 2026-11-15 about 22:05:35 UTC, after the Yarl control's first failed patch application and before the fresh run. The first run rejected a released patch as corrupt at its final line. Replay was amended to append one line feed when absent, recording released and normalized hashes and changing nothing else. The source of the missing line feed is unverified; the retained stock runner does not strip its patch output. Review found that four of the ten replayed raw patches fail without normalization; absence of a final line feed does not make every patch corrupt. The failed control attempt remains in `superseded-first-attempt-*.json`. The previous amendment timestamp of 22:08 was inaccurate.
- The Yarl image configuration showed a large environment layer containing the repository clone, above the layer and image budgets. The collector retained manifests, configs, histories and push dates instead of layers. No layer/overlay verifier was completed. Bigger budgets alone would not prove which digest an original run used.
- 2026-11-15 22:10:13-22:10:23 UTC, after the first-pass fresh labels and conflict paths had been printed at 22:09:48. Code changes added raw-blob repair of rewritten archive entries, subject to Git blob hash/mode checks, the existing 32-file bound and final full-tree equality. Numba's differing `numba/_version.py` was repaired; review later confirmed its `export-subst` attribute. Snapshot evidence collection was moved outside the declared-base success path, conflict-path details were added, and capped transfers were made non-retryable. Reference patches classify paths only and never replace agent outputs. The collection was rerun; labels agree wherever both passes completed, and numba had no first-pass label. Earlier records remain in `superseded-run1-*`.
- The preceding code changes were documented in the amendment text at 22:12:52, after the final collection ended at 22:11:15. They were post-inspection amendments, not rules fixed before viewing fresh labels. The worker's 22:13:18 trail entries likewise describe earlier events after the fact. The subsequent crash-log fix and unused scanner deletion mean the current script is not byte-identical to every producing revision. No collection-time producer hash was retained. Yarl's final checkpoint came from the crashed job 71285 and was retained by the subsequent successful job. Independent review reproduced its label.

## Review disposition

Opus 5.5 high on Kiro accepted the five declared-base diagnostic labels and failed gate after independently reconstructing their trees and merges. The [results](swe-rebench-results.md) record its corrections, limited transcript coverage and checks required before future collection. The implementation never establishes published or original snapshot verification. Raising budgets could enable future published-image inspection, but cannot supply missing original-run digest provenance. The original strict study question therefore remains unmet; a declared-base cohort would be a separately named study setting requiring an explicit project decision. Pre-review copies of both documents and their hashes are retained in the ignored private `review-records/` directory.
