# Fresh single-project cohort with ordinary Git staging

This protocol covers the second controlled single-project cohort. It reuses the isolation, capture and replay machinery of the [v3 pilot](controlled-single-project-protocol.md) but freezes a different final-tree policy before any coding output. This document was written from the frozen plan; the plan, prompts and recorder hash, not this account, define the run.

## Purpose and change from v3

The v3 pilot staged every file in each final worktree with `git add --all --force`. That included pytest caches and bytecode, so the captured target measured full-directory merges rather than ordinary Git changes. A post-hoc diagnostic showed the difference: three clean and two conflicts under ordinary staging, against five conflicts in the raw target.

This cohort applies ordinary Git staging as the primary, pre-registered capture policy. Ignored paths are outside the target by construction. The five repositories are new; none appeared in v3, the twelve-pair release, or the earlier controlled five-project pilot. They are development data for the construction and prediction workflow, not a held-out test set.

## Frozen choices

- Run id `csp-run-20261120-4f2a9c`, plan SHA-256 `c71cedd639c3107c80875083188feb4a4255f353a0fdbf322ec4da2965c8247c`.
- Capture policy `ordinary-git-staging-v1`. Each final source tree is derived twice from its pinned tree in a fresh temporary Git directory: `read-tree <pinned tree>`, then `git add --all` without `--force`, then `write-tree`. The parent object database is a read-only alternate. Both derivations must match.
- A full-worktree tree is also staged with the same policy for the out-of-prefix scope check. Tracked files stay tracked even when an ignore rule matches them.
- Five repositories, two tasks each, ten tasks and five pairs. All task text was authored before any coding output.
- Model selection `opencode-go/deepseek-v4.1-flash` through provider instance `opencode`, `variant: max`, reasoning effort `max`, service tier default, no fast or priority processing.
- One child at a time, each in a T3 worktree created from the private parent anchor. Root launches no child in the shell and makes no child checkout itself.

## Repositories

| repo | upstream commit | tree | default branch | license |
| --- | --- | --- | --- | --- |
| pytest-dev/pluggy | `93de545c3a31880feaf0f6bb8870b30d602cf681` | `8f60ba3a590b47405612c86938cb016f62c34ebd` | main | MIT |
| psf/requests | `3c7baaa05ab4aa49cc819ce3a819d260de19c157` | `0c8b989695d73c087123936657c0fbfe3034471f` | main | Apache-2.0 |
| encode/httpx | `7cff5f79bc78649bbcd3fd9aa7a74c86e0f63016` | `bd96f1f1df8ba79defc46792d1044cd4abd96b7b` | master | BSD-3-Clause |
| urllib3/urllib3 | `d9f9b0ad5b99247e06aa9a50b7a5747aa5c2e35d` | `97e7a7bad2bb3113e2a0ae930cd9480b94ab481c` | main | MIT |
| python-jsonschema/jsonschema | `64b62de5df4ec52d7679c770427329e86a22c395` | `1c501a4dab7aeaa13407bcc7affe70a3da0d0a1f` | main | MIT |

Each source subtree sits at `controlled_sources/<repo_id>/` in the anchor and must equal its pinned tree at capture and replay.

## Task design

Each pair touches one module and one test file in its repository. The two tasks in a pair add distinct helpers in the same area, so either clean or conflicting merges can result; labels are computed, not prescribed.

| repo | arm A | arm B | focused target |
| --- | --- | --- | --- |
| pluggy | `PluginManager.iter_plugins` | `PluginManager.plugin_names` | `testing/test_pluginmanager.py` |
| requests | `redact_url_auth` | `split_url_auth` | `tests/test_utils.py` |
| httpx | `is_ip_address` | `is_local_hostname` | `tests/test_utils.py` |
| urllib3 | `to_bool` | `to_int` | `test/test_util.py` |
| jsonschema | `chunks` | `flatten` | `jsonschema/tests/test_utils.py` |

Every acceptance block names its required tests. The focused command selects only those tests. Children install dependencies into task-specific virtual environments under a scratch directory outside the repository, for example `<scratch>/controlled-single-project-venvs/`, and prove the imported module path through the recorder.

## Isolation and capture

The v3 rules apply unchanged: the first tool action is the recorder's `capture`; a dirty start, a source-tree mismatch, an out-of-prefix change or a moved HEAD blocks the pair. The child may read only its own subtree's contribution guidance. Sibling sources are restricted by instruction, not a filesystem sandbox.

Collection stages the final worktree with ordinary Git rules, derives the source tree twice, extracts a binary-capable patch against the pinned tree, and replays it twice in fresh temporary repositories. Any difference in the two derivations or the two replays blocks the label.

Ignored paths remain on disk and are recorded as `filesystem_only_paths`; they do not enter the target. A file that was committed before an ignore rule matched it stays tracked and remains in the tree.

## Labelling and gate

A pair qualifies only when both starts share the same source tree and parent snapshot, both runs are confirmed started, both outputs are nonempty and distinct, both patch replays match, the derived trees repeat, HEAD did not move, and the time and provenance checks pass. `git merge-tree --write-tree` runs twice from side commits over the pinned upstream commit. Identical exit 0 is `clean`; identical exit 1 with a conflict report is `conflict`. Everything else stays unlabelled.

The feasibility gate passes when all five pairs are attempted and at least three pairs across at least three repositories qualify. It is evaluated only after all five are attempted. Every task stays in the denominator.

## Budgets

Each child is asked to finish within 480 seconds. Dependency preparation is limited to 300 seconds and one focused test command to 180 seconds, both through the recorder. The work uses one child and one heavy shell job at a time.

## Evidence and limits

Private evidence lives in the ignored local root `data/private/research/controlled-single-project-fresh-2026-11-20/`. The public results will report trees, paths, commands and counts without prompt text, patches or transcripts.

The design remains instruction-bound sibling isolation with coordinator-authored prompts, one model, five repositories and two tasks each. A clean merge does not establish semantic independence or coding correctness. This cohort is not training-ready and supports no accuracy, held-out or generalization claim.

## Freeze state

The anchor ref is `refs/research/controlled-single-project-2026-11-20-fresh-v1`; the parent commit is `6b7c1dbd20da30b50fb7244572e39cc4e739f798`. The recorder hash, test hash, spec hash and prompt hashes are recorded in the private freeze manifest before the first launch. No coding output existed at freeze time.

## Amendment: first attempt stopped by a symlink inventory defect

The first attempt (`csp-run-20261120-4f2a9c`) stopped at the requests capture. The pinned requests tree contains two directory symlinks, `tests/certs/mtls/client/ca` and `tests/certs/valid/ca`. The recorder's filesystem inventory walked directories with `os.walk(followlinks=False)`, which reports symlinks to directories under `dirnames`, so both paths were recorded as missing on disk. The capture correctly refused to proceed; no requests files were edited.

The defect is in the recorder, not in the staging policy. `fs_inventory` now records symlinked directories without descending into them. A fixture test covers a pinned source tree with a directory symlink. The first attempt produced one clean pluggy pair under its own frozen plan; that attempt is retained privately and is not combined with this cohort.

The corrected attempt is `csp-run-20261120-9b7d2e`, plan SHA-256 `d7274fbb5d1443c7bd2fea65b40247f3988b7d73ee9b50467f4b1f1784d16ee7`, parent commit `61fab1d84511550272ab1d1a69dcadfcfbfbb854`, anchor commit `1b6a81b3516b6c18884bbeff231885e5a34145e0`, ref `refs/research/controlled-single-project-2026-11-20-fresh-v2`, with a separate evidence root. Its manifest is frozen in that root before the first launch.

