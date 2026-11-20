# SWE-rebench import and replay pilot results

Run on 15 November 2026 UTC under the [frozen protocol](swe-rebench-protocol.md), with [scripts/swe_rebench_pilot.py](../../scripts/swe_rebench_pilot.py) and [tests/test_swe_rebench_pilot.py](../../tests/test_swe_rebench_pilot.py). Public facts are in [data/swe-rebench-pilot/](../../data/swe-rebench-pilot/): [selection](../../data/swe-rebench-pilot/selection.json), [cases](../../data/swe-rebench-pilot/cases.json), [summary](../../data/swe-rebench-pilot/summary.json) and [harness](../../data/swe-rebench-pilot/harness.json). The decision trail is [.audit/swe-rebench-pilot.tsv](../../.audit/swe-rebench-pilot.tsv). Raw bodies, ledgers, job logs and checkpoints are in the ignored `data/private/research/swe-rebench-pilot/`.

## Result

No pair qualifies as a strict primary example, and the expansion gate fails. All six cases (one development control and five fresh) are declared-base diagnostics at most. No ready feature or target record was written (the private `ready/` files are empty lists). Published-image tree inspection was not implemented or collected, and the released records do not bind an original run to an image digest. The collector therefore has no path that sets either snapshot verification flag to true. Zero primary records is a result of those evidence and implementation limits, not proof that the source contains no usable pairs under a different, explicitly named study setting.

| Group | Count |
| --- | --- |
| Strict primary pairs (fresh) | 0 of 5, in 0 repositories |
| Published-snapshot verified | 0 of 6 |
| Original snapshot verified | 0 of 6 |
| Snapshot evidence unavailable | 6 of 6 |
| Declared-base diagnostic labels, fresh | 1 clean, 3 conflict, 1 unavailable |
| Declared-base diagnostic label, control | 1 clean |
| Access or capacity exclusions (fresh) | 1 (MetPy) |
| Contradictions | 0 |
| Repositories sampled | 6 (yarl, MetPy, conan, attune, numba, python-markdownify) |

The implemented gate needs 3 strict primary pairs in 3 repositories, at most 1 access or capacity exclusion and no recorded contradictions. It passes the last two checks and fails the first two. Its contradiction classification misses some inner integrity errors, and it does not explicitly enforce the protocol's all-limits condition or every error exclusion. No such integrity error occurred in this run; these checks require correction before any future collection. Both-class coverage cannot be judged for primary labels because there are none. The diagnostic labels do contain both classes, but they are not training labels. The pilot stops here and does not launch expansion.

## Cases

Diagnostic labels come from Git 2.43.0 `merge-tree --write-tree`, identical on two runs, after each released patch applied separately to the tree rebuilt from the declared commit. The tree matched GitHub's tree identity in every case that has a label. They show replay relative to the declared base, not equality with the original runtime tree.

| Case | Declared-base diagnostic | Conflict paths | Snapshot evidence |
| --- | --- | --- | --- |
| Yarl 1413 and 1414 (control) | clean | none | unavailable, two distinct image digests |
| MetPy 2006 and 2007 | none, capacity exclusion | not run | unavailable, task records declare no image |
| conan 10941 and 10943 | conflict | `conan/tools/cmake/toolchain/toolchain.py`, also edited by the reference patches | unavailable, two distinct image digests |
| attune 122 and 123 | clean | none | unavailable, two distinct image digests |
| numba 5624 and 5627 | conflict | `reproduce_issue.py`, a scratch file added by both outputs | unavailable, two distinct image digests |
| python-markdownify 120 and 150 | conflict | `demo_fix.py` and `reproduce_issue.py`, scratch files added by both outputs | unavailable, two distinct image digests |

Only conan's conflict is in an existing repository source file. The numba and markdownify conflicts come from identically named scratch files that both agents created. The OpenHands prompt explicitly asks agents to create a reproduction script, and eight of the twelve outputs add `reproduce_issue.py`. The implementation narrowed the coordinating brief's stop rule to conflicts confined to `.openhands/` paths. Its `artifact_only_conflicts: 0` therefore describes that narrow path check, not the absence of prompt-induced artifact conflicts. The two scratch-only conflicts are grounds to stop expansion under the broader brief. Three outputs contain `.openhands/TASKS.md`, but the partner output never adds the same file. Both numba trajectories ended at the maximum of 100 iterations; numba-5624 edits no existing repository source, adding nine scratch files and `.openhands/TASKS.md` instead. The retained-patch Git labels stay unchanged. Any source-only label must be a separately defined diagnostic before collecting a new sample; applying it to these inspected cases would be retrospective analysis.

## What was verified

- Selection followed the frozen rule. Recomputing it from the retained catalog and trace IDs reproduces the five fresh pairs (a test does this).
- For all six cases, each task row matched the pinned catalog ID, repository and base. Each trace row matched its task, contained one user message that included the task statement, had a nonempty final patch, and contained neither the partner instance ID nor the partner statement.
- Declared commit trees: Yarl, conan, attune and markdownify archives matched the GitHub tree directly. The numba archive differed in `numba/_version.py`. Independent review confirmed that the retained archive's `.gitattributes` declares `numba/_version.py export-subst`. Replacing the archive file with the raw blob, whose Git hash and mode match the tree entry, gave the declared tree. MetPy's archive exceeded the 64 MiB cap, so its tree and replay are unverified. The repair record keeps counts rather than a full path/before/after-hash inventory; add that inventory before future collections.
- Released patch text has no final line feed in all twelve outputs. Independent review checked the ten replayed raw patches: four fail raw application, Yarl's two, conan-10943 and attune-123. The other six apply without normalization. Replay appends one line feed when absent and changes nothing else; both hashes are stored. The source of the missing final line feed is unverified, and the retained stock runner does not strip it.
- The retained OpenHands 0.54.0 runner at [commit 4aae68ae](https://github.com/All-Hands-AI/OpenHands/blob/4aae68ae53477d05010a509f1f1e3f02e61b1831/evaluation/benchmarks/swe_bench/run_infer.py) runs `git reset --hard` (line 373), `git add -A` (line 524) and `git diff --no-color --cached <base_commit>` (line 549). The [dataset card](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories/blob/35455389ab51bf5e2306bfd436ef72d0f98bf882/README.md) names OpenHands v0.54.0. That stock runner generates staged diffs against the declared base, including scratch and `.openhands` files. Its binary-removal steps mean the released form cannot represent every binary change. That the dataset runs used this runner file unmodified is not established.

## Unsolved evidence

- Image layers were not inspected. Each available task image is 1.2 to 2.5 GB compressed and has four layers above the 64 MiB layer cap. The largest retained layer declaration is 1,178,086,244 bytes for attune-123, not the previously reported 592 MB. The Yarl configuration history shows the repository clone inside the environment build step. Manifest, config, history and push dates (all 5 August 2025) are retained, with each tag resolved to an immutable digest. HEAD and tracked-tree equality with the declared tree, overlay and whiteout accounting, and untracked files are all unchecked.
- The two task images of each pair have different digests. Nothing ties either digest to the original run, since the dataset card gives a harness version but no image digest. `original_snapshot_verified` is false for all six cases.
- MetPy task records declare no image, and its source archive is over the cap. It stays in the denominator as a capacity exclusion.
- The viewer rows are not pinned. Instance ID, repository and base were checked against the pinned catalog, and trace IDs against the pinned list, but statements, patches and trajectories were not compared with the pinned Parquet bytes.
- Environment setup commits and test patches were recorded for each task but not compared against image test files.

## Limits and jobs

- Received response bytes: 79,788,069 of 512 MiB across 81 requests, including a 67,108,865-byte MetPy archive stopped at the 64 MiB cap and its partial body. Cached re-reads are counted separately (about 13.9 MB) and not charged. No image layer was requested. The largest per-task image scope was manifests and configs only.
- Jobs ran one at a time under `timeout -k` with an internal deadline. The first Yarl run, the Yarl rerun, the five-case collection, the six-case rerun (which crashed on a missing image field in MetPy and logged exit 0 by mistake; the script now logs the crash) and the final rerun are in `jobs.jsonl` with owner, PID, start, deadline and end. No watchdog or background job remains. The tests ran once after the final change in under 3 seconds.
- Git 2.43.0 was checked before any replay. No container was pulled or run, and no downloaded code, test or hook ran.
- The first-pass fresh labels and conflict paths were viewed at 22:09:48 UTC. Repair and snapshot-stage changes followed at 22:10:13-22:10:23. Their written protocol amendment followed at 22:12:52, after the final collection ended at 22:11:15. These were post-inspection changes; calling labels not yet final does not make the amendment prospective. No existing label changed, and numba had no first-pass label. The trail's 22:13:18 entries were written after the events they summarize.
- The crash-log fix and deletion of unused layer-scanner code happened after the final collection. No producing-script hash was retained, so the current script is not an exact collection-time producer. Yarl's retained final checkpoint came from crashed job 71285; the later successful job skipped that completed checkpoint. Its replay was independently reproduced in review.

## Tested and untested

Fixtures cover selection and exclusions, first-trace offsets, join and drift failures, partner leaks, replay status classification (errors and unrepeatable results never get a label), artifact-only conflicts, primary versus diagnostic separation, gate arithmetic, public-record stripping, ready-record export, budget accounting, capped transfers, cache accounting, no refetch after a cap, HTTP errors, archive caps, atomic checkpoint writes and the Git version gate. They use a local HTTP server and make no network call.

Only the live run exercised the registry token and manifest flow, the GitHub tree repair, the real `git merge-tree` replay, and the successful viewer reads. The viewer retry path never fired. The conflict-path parser has fixture coverage for the stage-line format only. The image layer and tar-overlay branches do not exist yet.

## Recommendation

Do not expand this pilot. Increasing image budgets could support a future implementation of current published-image inspection, but cannot recover the missing link between original runs and image digests. Fresh controlled runs that capture the initial tree and outputs by construction are the practical next route for retaining the agreed strict research question.

A declared-base cohort is a defensible different study setting: it asks whether two released final patch states merge relative to a declared tree. It must stay separate from strict labels and ParallACT, disclose binary and ignored-file limits, and define any source-only secondary diagnostic before collecting a new sample. It does not establish that both agents originally started from that tree. Such a scope change needs an explicit project decision; this pilot does not make it.

## Independent review

Opus 5.5 high on Kiro independently rebuilt all five labeled base trees by a second method and reproduced their repeated merge outputs and paths. It also recomputed selection and the byte ledger and checked the numba export substitution. It accepted the diagnostic labels and failed gate with the reporting corrections above. Its transcript review covered bounded excerpts of activity items 0-77, three items more fully, and omitted items 78-79; it was not a complete transcript read. The review did not validate unexecuted rename, deletion, mode-change or binary paths on real records. No labels or collected evidence were changed during these documentation corrections. Gate/contradiction handling, producer hashes, detailed repair records and the missing repair/end-to-end fixtures remain required before any future collection. There are no running pilot jobs.
