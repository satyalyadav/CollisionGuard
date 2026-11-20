# Fresh single-project cohort: ordinary Git staging

This cohort repeats the controlled single-project construction on five repositories that were not used in the v3 pilot or the twelve-pair release. It freezes ordinary Git staging as the primary capture policy before any coding output. The [protocol](fresh-cohort-protocol.md) and the private plan, prompts and recorder hash define the run; this page reports what happened.

## Result

All five pairs qualified and the feasibility gate passed. Under ordinary Git staging every pair merged with a conflict:

| Repository | Tasks (A, B) | Changed by both | Conflict paths |
| --- | --- | --- | --- |
| pytest-dev/pluggy | `iter_plugins`, `plugin_names` | `src/pluggy/_manager.py`, `testing/test_pluginmanager.py` | `src/pluggy/_manager.py` |
| psf/requests | `redact_url_auth`, `split_url_auth` | `src/requests/utils.py`, `tests/test_utils.py` | `src/requests/utils.py` |
| encode/httpx | `is_ip_address`, `is_local_hostname` | `httpx/_utils.py`, `tests/test_utils.py` | `httpx/_utils.py`, `tests/test_utils.py` |
| urllib3/urllib3 | `to_bool`, `to_int` | `src/urllib3/util/util.py`, `test/test_util.py` | `src/urllib3/util/util.py`, `test/test_util.py` |
| python-jsonschema/jsonschema | `chunks`, `flatten` | `jsonschema/_utils.py`, `jsonschema/tests/test_utils.py` | `jsonschema/_utils.py`, `jsonschema/tests/test_utils.py` |

Each pair has `starting_snapshots_equal: true` and `merge_repeats_identical: true`. Every task patch replayed twice to its captured source tree. The public record is [summary.json](../../data/controlled-fresh-2026-11/summary.json).

## Method

- Run `csp-run-20261120-9b7d2e`, plan SHA-256 `d7274fbb5d1443c7bd2fea65b40247f3988b7d73ee9b50467f4b1f1784d16ee7`, captured with policy `ordinary-git-staging-v1`.
- One private parent anchor holds all five pinned trees. Each child started from that anchor in a separate T3 worktree and recorded its start before editing.
- Model `opencode-go/deepseek-v4.1-flash`, provider instance `opencode`, `variant: max`, reasoning effort `max`, service tier default, no fast or priority processing. One child at a time.
- Collection derived each final source tree twice with `read-tree <pinned tree>`, `git add --all` without `--force`, and `write-tree` in a fresh temporary Git directory. The repository's committed ignore rules decided which paths entered the tree.
- Patches were replayed twice against the pinned tree. Pair labels came from two identical `git merge-tree --write-tree` runs.

## Capture policy evidence

Ignored files stayed out of every target. The urllib3 tasks generated an ignored `src/urllib3/_version.py` during editable installation; it appears in the worktree inventory but not in either captured tree. Ignored pytest caches were treated the same way. Tracked files that match an ignore rule remain tracked because staging starts from the pinned tree.

The first attempt at this cohort stopped at the requests capture before any edit. `fs_inventory` used `os.walk(followlinks=False)`, which lists a symlink to a directory under `dirnames`, so the pinned certificate-directory symlinks were reported as missing on disk. The recorder correctly refused to proceed. The inventory now records symlinked directories without descending, a fixture test covers the case, and the cohort was refrozen from a new anchor. The stopped attempt and its one clean pluggy pair remain in separate private evidence and are not combined with this result.

## Test evidence

Focused commands ran through the recorder inside each source directory, with `PYTHONPATH` pointing at the assigned source and an import check before the test command. The final runs all exited 0:

- pluggy A: 2 passed, 79 deselected. pluggy B: 2 passed, 79 deselected.
- requests A: 3 passed, 229 deselected. requests B: 3 passed, 229 deselected.
- httpx A: 3 passed, 40 deselected. httpx B: 14 passed, 40 deselected.
- urllib3 A: 18 passed, 601 deselected after dependency retries. urllib3 B: 13 passed, 601 deselected after one failed selector run.
- jsonschema A: 3 passed, 38 deselected. jsonschema B: 2 passed, 38 deselected.

Earlier failed setup and selector runs are retained in the private job records. No test run was repeated by this analysis.

## Limits

The task design put both tasks in a pair on the same module and test file, so five conflicts do not estimate a base rate for arbitrary task pairs. A clean merge would not have established semantic independence. All tasks came from one model, the sample is small and purposive, and sibling isolation is instruction-bound rather than a filesystem sandbox. This cohort is construction evidence, not training data, and supports no prediction, held-out or accuracy claim.
