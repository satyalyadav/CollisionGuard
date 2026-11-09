# ParallACT local import pilot protocol

Frozen before new case selection and run collection on 8 November 2026 UTC. This is a controlled-data import pilot, separate from the inconclusive historical AIDev pilot. No models or new coding-agent outputs are required.

## Scope and sample

Pin ParallACT source revision `c212deb174fbc8980212cc1bde5b3f047941f332`. Verify the cached recursive-tree response against the hash in `data/source-audit/benchmarks/selection.json`; archive it privately. Enumerate all instance JSON paths under `dataset/`, excluding tooling. Report counts by version, seed/generated origin, family and repository. Parse repository names using the 40-character commit suffix, since repository names can contain hyphens.

Recover all six previously audited run files and seeds first. Require exact matches to their recorded compressed-run and seed SHA-256 values. A mismatch is source drift, not permission to overwrite the old hash. These six are known-label retention checks, not new evidence of predictive performance.

Freeze 12 additional distinct instance paths before fetching their contents or outcomes. Exclude the six known cases. Use two cases per available version/origin/family stratum, stable path ordering and seed 39. Prefer repository diversity with a deterministic global cap of two new cases per repository; record any shortage rather than replacing cases after seeing outcomes. Save the exact selection, source/protocol hashes and algorithm before downloads. Family is for selection/audit only and is never a predictor.

## Private inputs and public evidence

Keep exact compressed runs, seed JSON, source archives, extracted task descriptions, patches and text-derived artifacts under `/home/satyal/.cache/collisionguard-parallact-pilot`, outside the public repository. Preserve successful responses before parsing with atomic writes and hashes. Resume only after verifying cached bytes and matching protocol, selection and script identities. Record failures and do not silently replace examples.

Use only the `parallel_unaware` scenario from the released `api--claude_code--opus-4.8` configuration and the instance's source version. Verify the actual backing-data URL convention in first-party site code before collection; if a version has no corresponding run, record it as unavailable. Preserve the inspected site code privately with hashes. Check two distinct nonempty initial prompts, matching assigned A/B statements, no inter-agent messages, separate nonempty agent outputs, and differences from reference patches. Record timing evidence and exact run-producing revision as verified, source-reported or unknown, never inferred from a source-code pin. A prompt containing later instructions or unexpected structure requires a flag.

Export a private feature file using an explicit allowlist of initial task descriptions, IDs, repository and base SHA. Put outcomes in a separate private target file. Exclude family, gold/reference patches, actual touched files, reconciliation, explanations, tests, evaluator results and run timing from predictor records. No model training is part of this import run. Report duplicate task/pair hashes and group related variants and repeated runs by repository for future splits.

## Replay and gates

Reuse the existing isolated full-tree replay helper and cached source archives when their identities verify. Reconstruct the base tree and require equality with the pinned commit's tree. Restore archive-omitted tracked files by verified Git blob identity if feasible. Apply each released agent patch independently to that same tree; repeat the Git merge and compare output/tree identities. Reject shallow, missing or ambiguous base evidence. Do not execute downloaded project code, hooks, builds or tests. Record clean, conflict, unavailable and unverified separately. Exported labels and family names never substitute for a replay label.

Attempt the frozen cases in deterministic order within the budget. A successful import-feasibility gate requires all six old run/seed hash matches, at least 10 of 12 new cases with valid prompt/output association across at least five repositories, and at least four new complete-tree repeated replays across at least three repositories containing both clean and conflict outcomes. Any unresolved integrity or predictor-leakage failure blocks a pass. Missing or unfinished cases remain in their original denominators. Distinguish failure of these feasibility criteria from proof that the source cannot work. Unknown exact runner revision prevents a fully verified execution-provenance claim even if import feasibility passes.

## Bounds and execution record

Run one collection job at a time, with a 30-minute self-terminating process-tree deadline. Log owner, purpose, PID, UTC start/deadline and checkpoint path before work. Use request and subprocess timeouts. Cap newly received response bodies at 256 MiB total and 64 MiB per source repository, including source restoration; cap each individual metadata/run body at 8 MiB and decompression at 16 MiB. Count source bodies delivered to the reader, including bytes rejected at a limit; transport overhead is outside this body budget and must be disclosed. Existing cached bytes are reported separately. Stop a source after three consecutive non-rate-limit access failures; rate limits pause collection without invalidating a pair. Record remaining cases as unfinished rather than absent.

Use atomic checkpoints and a persistent byte ledger; retries consume the same cumulative budget. Record exact commands, Python/Git versions, script SHA-256, protocol hash, selection hash, start/end times and failures. Public outputs contain only our code, small factual audit metadata, labels and a concise report. Keep a private decision trail for review and update the project progress log with a short milestone. Opus 5.5 at high effort reviews the finished evidence before a final verdict.
