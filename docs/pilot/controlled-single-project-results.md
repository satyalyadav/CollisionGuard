# Controlled single-project post-hoc Git-visible diagnostic

This report covers a separately named development analysis of the five existing controlled pairs. It does not relabel, replace or reinterpret the frozen full-directory captures. The original raw labels remain `conflict` for all five pairs. The post-hoc work asks a narrower question: what happens if the final source directories are staged as ordinary Git-visible files, with ignored pytest caches and bytecode dropped mechanically by the repository's own ignore rules?

The result is 3 clean merges and 2 conflicts across the five pairs. Those counts are computed from this method, not prescribed, and they are not accuracy, generalization or training evidence. All five repositories are development controls now.

## Provenance and starting snapshots

The parent anchor is commit `b40b3dced15f1f5a83593c42e3860ec24e3291cf` with tree `e1a019b7989a568d63b93580283ceed2475d5513`. All ten tasks started in separate T3 worktrees from that anchor and received no partner context. The captured source subtree matched the pinned upstream tree for every task: click `9f278790733eb087a591b95189e188094c3ac14f`, itsdangerous `ef4287f82d8234404b58c7b29d38197e1f38e207`, attrs `f03d83ddabaad2ea3700f305b96db2240843f46d`, packaging `85c13f4c4e3eda5334b389b1501e1995727ff685`, dateutil `da9176cc76597098f4b2927996f52d3b8cf0b9aa`.

Every raw pair replay recorded `starting_snapshots_equal: true` and `merge_repeats_identical: true`. The post-hoc merge step repeated each `merge-tree --write-tree` twice in a fresh temporary Git directory. Both runs returned identical exit codes and identical stdout bytes for every pair: clean pairs `[0, 0]`, conflict pairs `[1, 1]`. The ten coding tasks used `opencode-go/deepseek-v4.1-flash` through provider `opencode`, with option `variant: max`, service tier default, no fast or priority processing. The tasks are ten independent coordinator-authored prompts, two per repository, never a multi-agent collaboration.

## Method separation

The frozen raw method comes from `scripts/controlled_single_project.py`, which collected every file in each source directory, including ignored pytest caches and `.pyc` files. The original preregistered gate passed its formal provenance and repeated-replay checks, but its raw full-directory target measures Git merge conflicts under a full-directory capture policy. Generated files contribute conflicts; two pairs also conflict on repository content under ordinary staging. Its five `conflict` labels are retained unchanged in the replay logs and in this report's raw column. `E/artifact-conflict-audit.json` is an imperfect post-hoc baseline-ignore scan whose baseline-only checks are incomplete because generated pytest `.gitignore` files appear after capture. It was not used to infer labels, and no labels were copied from it.

The post-hoc method `posthoc-ordinary-git-staging-v1` derives a tree for each task from the actual final source directory using ordinary Git staging:

1. Create a new temporary Git directory and index with no shared index with any coding worktree.
2. Add the parent repository's object directory as a read-only alternate.
3. `git read-tree <pinned tree>`.
4. `git --git-dir TEMP --work-tree ACTUAL_SOURCE add -A`.
5. `git write-tree`.

System and global Git configs are disabled, `GIT_OPTIONAL_LOCKS=0` is set, hooks cannot run in the fresh Git directory, and no external filters exist in these trees. Committed and generated `.gitignore` rules apply as ordinary Git applies them. There is no per-case selection and no manual file-category filter. Any nonignored scratch, docs, tests or binary remains included; ignored files drop out only because Git ignores them.

Each derived tree was compared with the frozen captured final tree at every included path. All ten staged trees are subsets of their captures and every staged blob and mode matches the captured blob and mode. This checks included content and modes; subset validation alone cannot rule out post-capture deletions. Inventory equality covers only the analysis interval. It does not establish original-index preservation, which is supported by the isolated-Git-directory implementation rather than an index comparison. Root then materialized all ten frozen final trees in fresh temporary directories and independently applied ordinary Git staging from their pinned trees. All ten resulting trees equal the retained diagnostic trees. This additional check binds the diagnostic to the complete saved captures without reading mutable coding worktrees. Evidence is `data/private/research/controlled-single-project-v3/frozen-staging-verification.json`.

Binary patches from the pinned tree to each derived tree were written privately, then applied independently to a fresh pinned tree in a separate temporary Git directory. All ten replayed trees equal their derived trees exactly. Patch bodies are not public.

## Results

| Repository | Raw full-directory label | Derived trees (A, B) | Post-hoc merge | Post-hoc conflict paths |
| --- | --- | --- | --- | --- |
| click | conflict | `febb736e4866c0a1df0d41634027eb437d4e5069`, `a1255722f485f89244be3f2d2924ccd39db09dc2` | clean `3c1b14da04b35fa76f53ebb3be9486857576626a` | none |
| itsdangerous | conflict | `0c1a8bfb3daa63424a93ee880d2621591b0e2ec1`, `b9dadde754cb8c2176e689cebbdeb722ba96758e` | conflict `f2184c31de03e73183f7ca0de00be8aee7c2352f` | `CHANGES.rst` |
| attrs | conflict | `bcc972c80efa02eeec0676860d550e39fc90ae68`, `c871003c3e5a048215ba2c5ed69ef4e8dcda13ef` | clean `3cbd9ce68069141da1e5f8af0ede5edce27927e6` | none |
| packaging | conflict | `a07caf04245b04ca0a7eb7d9b0447cd0323f21d6`, `165f4ac1da5dfa402b05464cd4c9363f53b2b881` | conflict `5cdd9a786dea13ce203a6ac8f603deaa7ddaf03b` | `CHANGELOG.rst`, `tests/test_utils.py` |
| dateutil | conflict | `5ee21c0a8c5234f7a1615ce519baf5691aefc3d3`, `06f51ed9228b89411d2adbdc4d6a2ff6f74e6123` | clean `44d9ebec7467d30a9c3172f3faf337bb8e9ee76b` | none |

Ignored paths removed by ordinary staging numbered 20 and 21 for click, 14 and 14 for itsdangerous, 22 and 46 for attrs, 19 and 19 for packaging, and 22 and 24 for dateutil. They are listed individually in the public JSON. Dateutil's `.gitattributes` sets CRLF checkout for `NEWS` and `*.bat`; staged blobs normalize those files back to their captured LF blobs, so on-disk bytes and staged bytes differ there by design. The captured comparison uses the staged blobs.

## Retained test and failure evidence

The targeted-test record audit confirms the raw streams against retained base64 bytes. Outcomes are reported as found:

- click A ran its focused file twice, 22 passed both times. click B reported 7 passed.
- itsdangerous A reported 40 passed. itsdangerous B reported 11 passed.
- attrs A used the frozen `-k fields_dict` selection, which selected one existing test and skipped its new `test_instance` and `test_handler_non_attrs_instance` tests; it reported 1 passed and 280 deselected. A separate direct sanity check ran, but the new tests were not selected. attrs B first exited 4 with no stdout, then reported 4 passed and 35 deselected.
- packaging A reported 11 passed and 71 deselected. packaging B ran the same focused selection twice, 8 passed and 77 deselected both times.
- dateutil A reported 9 passed and 582 deselected. dateutil B ran three times: a failed marker collection exited 3 with no tests, a second run reported 9 passed with the new cases skipped, and a third run after test renaming reported 16 passed and 589 deselected.

Earlier import-proof failures, dependency and setup failures and the attrs first-job failure are retained, not corrected. dateutil needed src-layout and SCM environment workarounds. Typing checks were not run. No test run was repeated by this analysis.

## Limits and uncertainties

The design is instruction-bound sibling isolation, not an interaction study. Tasks are coordinator-authored, all outputs came from one model, and the sample is small and purposive: five repositories and two tasks each. The post-hoc method changes which pairs conflict, but a clean merge does not establish semantic independence, coding correctness, or that the two tasks are safe to train on together. Conflict paths show ordinary Git conflicts only; they are not semantic conflict labels.

Ordinary Git staging still includes any nonignored scratch, documentation, test or binary file that happens to be present. No source-only filtering was applied at any stage. The artifact scan was not used as a label source. This work is not training-ready and makes no held-out, generalization or accuracy claim. The root protocol at `docs/pilot/controlled-single-project-protocol.md` was written by root and was not edited here. `E/root-activity-excerpts.json` is a bounded, truncated T3 transcript from positions 512 to 615 only, not a full transcript.

## Recommendation

Freeze an ordinary Git staging policy prospectively before any fresh expansion, keep the raw full-directory captures and labels unchanged, and collect a genuinely fresh test cohort later. Do not treat this development diagnostic as a held-out or generalization result or as accuracy evidence. The first independent Astra review accepted generation feasibility with reporting corrections. Root applied those corrections, restored main and integrated the local files. The trail includes retrospective and batched entries; timestamps do not prove contemporaneous append order. Review coverage is bounded, not a full transcript or corpus audit.

## Reproduction

- Original analysis producer, preserved at `data/private/research/controlled-single-project-v3/supplemental/original-analysis-producer.py`, SHA-256 `b25b0936c72d15023704470178e6b7a7d62c866d17de3892e77709371e722a46`.
- Focused tests: `python3 -m unittest tests.test_controlled_analysis -v` passed 5 of 5.
- Local real-data run: `python3 scripts/analyze_controlled_pilot.py --work-root <scratch>/controlled-posthoc-work2 --out data/controlled-single-project/posthoc-git-visible.json` completed in 11.4 s with no network or package installs.
- Public facts: `data/controlled-single-project/posthoc-git-visible.json`, original SHA-256 `bbc654d58479f89478f297dc3e32eaa1513ebcd464b948bf50971fbc1acd6ee8` before root reporting corrections. The original export is preserved privately. Current public SHA-256 `b9e753864ff40b23960e3dfef23564c8771e3602ef4613ed086df73f40e28374`. The public copy records the producer as the repository-relative path `scripts/analyze_controlled_pilot.py`; the original local worktree path is not published. Labels and trees are unchanged.
- Private supplement: `data/private/research/controlled-single-project-v3/supplemental/posthoc-full.json` plus the ten patch files under `supplemental/patches/`. These contain command records, full hashes, exclusions, conflicts and patch bytes.

Root changed only reporting strings in the analysis script after the recorded run. Current script SHA-256 `6e1ca41022bb17ada952205d83962844d55d8ab63d2644a8c92bce2e31759c01`; the original producer hash above identifies the executed version. No labels or merge results changed.

## Independent review

Astra at low effort accepted the generation-feasibility conclusion and required narrower preservation and target-language claims. Root applied those corrections. A separate bounded trail review found the post-outcome policy change disclosed, but timestamps include retrospective and batched entries. The trail review covered selected root activity at positions 512 through 615 and author activity at positions 111 through 122. Early setup and generation rows were not independently audited. Neither review reran the corpus. Root's additional frozen-capture reconstruction matched all ten derived trees.

Private review records are `data/private/research/controlled-single-project-v3/conclusion-review.json` and `trail-review.json`. All generated source worktrees and raw records remain local. Main and its original index tree are restored; the integrated pilot files are uncommitted.
