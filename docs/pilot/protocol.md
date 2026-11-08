# Data-feasibility pilot protocol

Version 2, recorded on 7 November 2026 after Opus 5.5 protocol review and before candidate selection or outcome inspection. Version 1 allowed immutable source discovery and downloads; this amendment makes the selection, validity, and target rules explicit. Record the version and document hash with the frozen sample. This pilot tests data feasibility, not classifier performance or population conflict rates.

## Candidate population and selection

Use an immutable AIDev v5 revision and its complete AIDev-pop PR and issue-link tables. Record URLs, revision, retrieval time, hashes, file sizes, and failures. No timeline-table download is planned. Build candidates without examining replay labels or success in recovering historical text.

For sampling only, a PR activity window is the half-open interval from `created_at` to `closed_at`, or to the dataset creation cutoff of 2026-03-31T23:59:59Z when it is still open. Clip later closure times to that cutoff. Reject malformed, empty, or reversed windows. Two windows overlap when the later creation time is strictly before the earlier endpoint. These are retrospective PR windows, not coding-start evidence or prediction features.

Aggregate every linked issue ID for each PR. A candidate has two distinct PRs in the same repository, nonempty issue sets on both sides, no issue ID shared between the sets, and overlapping windows. Canonicalize pair order by numeric PR ID. Sort candidates by stable repository ID and ordered PR IDs, apply a seed-39 permutation, then accept greedily with at most four pairs per repository and each PR appearing in at most one selected pair. Freeze the first 20 accepted pairs and their source IDs before collecting outcomes. The selected set must span at least five repositories. Keep failures in the selected denominator; never replace difficult pairs.

This pilot uses a pooled sample without oversampling agent categories. Report the realized same-agent/cross-agent composition as source annotations; it need not contain both. Their association with conflicts is not a causal estimate. If the complete frame cannot be enumerated or fewer than 20 pairs across five repositories can be selected, report NOT_ASSESSABLE and no expansion. Do not substitute an easier cohort or scale down the gate.

## Accepted pre-start evidence

The decision time `t` must satisfy `max(ready_A, ready_B) <= t < min(start_lower_bound_A, start_lower_bound_B)`. Readiness requires timestamped task instructions and a timestamped record that the task was available for dispatch, with agent identity only if its assignment was already known. Issue creation alone does not establish readiness. If several issues define a task, all required instructions need coverage.

Accept a start lower bound only from a verifiable original dispatch/run record or workflow event whose documented semantics establish that the particular agent execution could not have begun earlier. A routine issue-assignment event is insufficient unless additional evidence establishes that it initiated this execution and no prior execution occurred. First commits and PR openings provide upper bounds on start, not lower bounds. Missing readiness or lower-bound evidence is UNKNOWN and cannot establish strict eligibility.

Accept task wording from an authenticated source record of the original dispatch, a versioned archive captured before `t`, or complete accessible GitHub content-edit and title-rename history that reconstructs the wording at `t`. A current field is acceptable only with reliable field-specific evidence that it was unchanged after `t`; a missing or null edit-history field alone is not proof. A revision edited before `t` is allowed. Edits after `t` require recovering the earlier wording. Record inaccessible, deleted, truncated, or incomplete histories as UNKNOWN. `updated_at`, creation timestamps, current issue bodies, and PR descriptions alone are not accepted historical-text evidence.

The issue-to-task association must be known at `t`. Later links from the completed PR may be used only to associate an outcome with that task, with uncertainty recorded; a future PR identifier or its link need not exist before dispatch and must not become a predictive feature. An agent label inferred from a later PR signature is retrospective metadata, not verified pre-start identity.

Accept the repository snapshot at `t` only from an immutable SHA anchored to an original dispatch/checkout record or a timestamped branch/push record establishing the ref state at `t`. Git author/committer dates or a later observed PR `base.sha` alone do not establish that state. Missing snapshot evidence is UNKNOWN.

## Primary target and secondary diagnostics

The primary target merges the output head captured at the first documented completion of each task's original agent run, excluding later review edits or reruns. Each head needs a timestamped completion record or equivalent immutable event evidence, not a present-day ref or commit date alone. Both tasks must start from the same verified snapshot at `t`. The two pinned heads must descend from that snapshot and have it as their sole merge base. Rebased heads, inherited upstream merges, or multiple bases make primary provenance UNKNOWN unless complete event evidence establishes equivalence to the original run output. Do not reconstruct an uncertain primary target silently.

Replay with pinned Git version and `git merge-tree --write-tree --messages HEAD_A HEAD_B`, default merge strategy and rename detection, with no repository-specific merge drivers or attributes executed as commands. Record the heads, the output of `git merge-base --all`, Git configuration, exit status, tree ID, conflict paths/types, and stderr. Label exit 0 CLEAN, exit 1 CONFLICT, and other statuses ERROR. Detect non-text conflicts and report this as Git-reported merge conflict unless the narrower textual subset is independently established. Run a valid primary replay twice on the same pinned objects and require matching label and tree ID.

Pre-register a secondary diagnostic tier: observe today's PR heads, pin those SHAs and retrieval times, and merge them using their actual common base. Permit different original PR bases and Git's default recursive handling of multiple bases, recording all bases and inherited-history caveats. This diagnoses fixed-head merge feasibility only. PR-open time may be reported as an explicitly unverified start proxy; it does not relax eligibility or historical-text requirements. Secondary labels never count toward the strict gate, regardless of reproducibility.

Use isolated Git object stores and empty config, with `GIT_CONFIG_NOSYSTEM=1`, an empty global config, `core.hooksPath=/dev/null`, `protocol.file.allow=never`, no submodule recursion, and `GIT_LFS_SKIP_SMUDGE=1`. Do not check out or execute repository code, hooks, builds, tests, or external merge drivers. Fetch only required refs/objects with blobless fetches where possible. Network needed for blobs must be explicit and budgeted before replay; disable implicit lazy fetches during the merge. Missing objects and truncated-history failures are unknown/error, never clean.

## Mechanical validity gate

A fully valid pair requires all of these verified conditions:

1. Historical task instructions and issue-to-task associations are established at `t`.
2. Both readiness/start intervals and the common repository snapshot establish strict pre-start eligibility.
3. The primary run-output heads and their sole common base are immutable, pinned, and satisfy the primary provenance rules.
4. The primary replay returns CLEAN or CONFLICT twice with the same label and tree ID.

Every UNKNOWN, ERROR, unvisited, or budget-interrupted selected pair is not fully valid. Maintain these component statuses separately. Expand only with at least 10 fully valid pairs of the original 20, spanning at least five repositories, including at least one valid CLEAN and one valid CONFLICT. Otherwise report NO_GO, or NOT_ASSESSABLE if collection cannot finish. These are planning gates, not statistical guarantees, and may not be relaxed after results.

## Budgets, checkpoints, and stop rules

Keep automated execution within a 30-minute wall-clock job deadline and manual recovery within six person-hours. Record both separately. Use one data or replay job at a time and one explicit query/fetch worker. The overall runner must terminate its process tree at the deadline, including finite subprocess and network timeouts. Log owner, purpose, PID, start, deadline, and checkpoint. Save validated completed-pair records atomically for safe resumption.

The total source/Git transfer budget is 2 GiB. Count downloaded response-body bytes, failed/partial attempts, and explicit blob fetches, including projected/range reads; identify protocol overhead or transport bytes not measured. Source Parquet transfers have known-length checks and a streamed byte counter. Each repository has a 64 MiB Git-transfer cap, independent of the total budget. If Git transport cannot be metered hard, use an explicitly described conservative limiter or mark the fetch budget NOT_VERIFIED; disk size alone is not network transfer. Do not silently claim hard enforcement from object-store size. No implicit lazy-fetch exemption is allowed. Record dependencies and their install sizes separately from source/Git data.

Freeze a deterministic repository visitation order from the selected pairs. Stop a source after three consecutive non-rate-limit failures, saving the unfinished sample. A GitHub rate limit pauses collection and records a resume time; it does not prove a pair invalid. Unfinished pairs stay in the denominator and block a pass. An exhausted repository budget leaves its remaining pairs unfinished rather than replacing them. Stop the full run when the total budget/deadline is reached. Reuse immutable cached files and completed outcomes; do not repeat them without a recorded reason.

## Deliverables

Keep a reusable collector/replay script, small selected evidence and outcome records, and one concise results report. Raw Parquet/Git caches remain outside the deliverable. Report exact commands, pins, selection funnel, pair-level reasons, separate strict and secondary outcomes, measured and unverified budgets, tests, and the gate conclusion. Do not train models or submit Sol jobs on a failed gate. Opus 5.5 at high effort will review the final code, evidence, and claims before the milestone closes.

## Evidence references and access limits

The [pinned AIDev v5 documentation](https://huggingface.co/datasets/hao-li/AIDev/blob/b8dc67df93e7c11f6f20c84129db7232eb1ec253/README.md) describes the historical tables. Public viewer samples help inspect fields but do not independently pin the viewer's current revision. Collection must verify its actual pinned Parquet schema.

GitHub documents issue edit fields in its [Issue schema](https://docs.github.com/en/graphql/reference/issues#issue) and edit records in [UserContentEdit](https://docs.github.com/en/graphql/reference/users#usercontentedit). These fields are possible evidence sources, not a guarantee that every task's earlier wording is recoverable. The independent audit's unauthenticated GraphQL probe hit an egress-IP rate limit; it did not inspect actual edit histories. Record unqueried or inaccessible evidence separately from confirmed absence. A timestamped [cross-reference event](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types#cross-referenced) can date a reference but does not establish task readiness or execution start. A current [PR head OID](https://docs.github.com/en/graphql/reference/pulls#pullrequest) likewise does not establish a historical run-output head.
