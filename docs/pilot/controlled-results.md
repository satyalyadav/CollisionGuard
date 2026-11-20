# Controlled five-repository pilot: stopped

As of 2026-11-15T23:36:50Z, the source selection, all ten exact task prompts, prompt hashes, pinned commits, and the Kiro model selection are frozen in the private plan (`0a888d174ef3faaca089ca97f25ec4acc44523ac0e4b09eb1e9a6fb364a2718c`). No coding child started, so there are no child outputs or merge labels. All five pairs remain in the denominator as unattempted.

## Work completed

- Reused and verified the five clean T3 source-project clones and their pinned default-branch commits. The requested `python-dateutil/dateutil` path returned 404; the official canonical repository `dateutil/dateutil` is recorded with that resolution.
- Froze two distinct researcher-authored tasks for each repository before any coding output. Every task requests Kiro `claude-haiku-5.5` with `mode: vibe`; the coordinator remains Codex `gpt-6-luna` at `max` / `default`.
- Implemented full-tree capture, bounded job records, repeated Git 2.43.0 replay, and unlabelled failure rows. The recorder fixtures passed: `timeout -k 10s 180s .venv/bin/python -m unittest discover -s tests -p 'test_controlled_pilot.py' -v` (8 tests, 0.900s).

## Launch blocker

Three `delegate_task` submissions for the first frozen task returned T3 `invalid_request` before creating a task. The error was unchanged when the registered project ID included or omitted its `mcp:` prefix, and when `target.environmentId` was included or omitted. The five source projects have no active threads, the source repositories have no child worktrees, and no matching task process is running. The frozen queue records all three rejected submissions with null task, thread, and run IDs; none counts as a coding run.

The user chose to stop after preserving the prepared pilot. The coordinator is interrupted, has no active run or pending background tasks, and no coding threads will be launched. The prepared files and source clones remain locally. No model or provider fallback was used.

## Current gate

Zero of ten coding runs started; zero of five pairs attempted. The feasibility gate was not evaluated. No coding-model usage or cost is available because no coding run began. The user stop supersedes the original deadline; no automatic restart is authorized.

Source facts and frozen selection are in `data/controlled-pilot/repositories.json` and `data/controlled-pilot/selection.json`. Public interim pair results are in `data/controlled-pilot/results.json`; private prompts, queue, and evidence are under ignored `data/private/research/controlled-pilot/`.

## Preservation note

Stopped by user at 2026-11-15T23:39:58+00:00. Files remain on local disk and are not committed or externally backed up. Pre-stop copies and hashes are in ignored `data/private/research/controlled-pilot/stop-records/`. The interrupted interim `results.json` contained attempted/output fields despite no confirmed coding launch. That export is preserved as unverified; the current public status records all five pairs as unattempted with no accepted outputs or labels. The preparation code and any interim captures require review before future use. No additional review or coding job was started after the user stop.

## Direct-root retry

At 2026-11-16T02:17:49+00:00, the user requested direct root delegation and allowed DeepSeek V4.1 Flash at max through OpenCode. A read-only worktree access probe submitted by the root with that model was rejected before task or worktree creation. T3 returned: "A local task runs in this thread's project. Omit target.projectId, or pass target.environmentId to run it in that environment's project." This reproduces the project-scope restriction without nested delegation or Haiku. No coding run started, no frozen prompt or output changed, and no top-level thread was created. The exact probe is retained in ignored `data/private/research/controlled-pilot/root-direct-launch-probe.json`. The earlier stop and pre-stop exports remain historical records; the current launch status is blocked after this direct-root retry.
