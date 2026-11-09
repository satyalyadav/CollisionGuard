# Project progress

Summary for reports. Dates use America/Phoenix time.

## Current status

- The [public repository](https://github.com/satyalyadav/CollisionGuard) holds code, reports and metadata. Student IDs and unfiltered local workspaces are excluded. Thirty-six helper tests pass.
- The [resource recovery](docs/pilot/parallact-recovery-results.md) produced twelve verified pairs across eight repositories, with seven clean and five conflict labels. Matching private records live in ignored `data/private/parallact/recovery/`. Opus 5.5 accepted the records.
- The recovery repaired collection controls and verified tree reconstruction. It reuses the same twelve cases; earlier failures and unknown runner/site provenance remain.
- The [release assessment](docs/research/parallact-public-release.md) recommends conditional public release of the twelve task pairs and labels with existing licenses, source notices and credit. The blanket private-only advice was too cautious. No model or new agent outputs were generated.
- CooperBench's inspected outputs form a communicating condition. Other corpora lack verified task/base joins. The [AIDev pilot](docs/pilot/results.md) remains inconclusive because original historical records were not queried. Sol access is reported but unverified; project `AGENTS.md` remains a suggestion.

## Milestones

### 2026-11-07: Preserve the proposal

Converted the PDF to [Markdown](docs/proposal/original-proposal.md). Removed redundant conversion files as requested. The unchanged private copy remains local; the public copy removes student IDs.

### 2026-11-07: Research and audit sources

Reviewed novelty, data and evaluation. Prediction before either task starts is the proposed contribution. The [source audit](docs/research/data-source-audit.md) reproduced six ParallACT pairs and one CooperBench pair. Workflow/corpus evidence remained incomplete. Opus confirmed the replay evidence.

### 2026-11-07: Close the AIDev pilot

Sampled PR pairs and attempted Git diagnostics. Unqueried historical records leave feasibility unassessed. Opus review prompted clearer statuses and disclosure of unretained script revisions.

### 2026-11-08: Publish and run the first import pilot

Published scripts, reports and metadata, then checked reuse terms. Six retention checks matched. Seven of twelve new cases replayed, with two clean and five conflict labels. Four unsupported v2 cases and a whitespace false negative prevented a pass. Fixed future whitespace matching while preserving the failed result.

### 2026-11-08: Run the v1-only follow-up

All twelve associations passed; four replays completed, with two clean and two conflict labels. Two cases hit the repository download budget and six exceeded the archive decompression limit. Opus confirmed the evidence. Recorded collection limitations without changing frozen records. That collector was superseded by the recovery.

### 2026-11-08: Recover useful local records

Reused verified caches with separate JSON/archive limits. All twelve pairs now have repeatable exact-tree labels and synchronized private records. Preserved producer history and the interrupted first job's unknown exit; continuations succeeded. Opus 5.5 accepted all twelve records. No model was trained.

### 2026-11-08: Preserve durable local storage

Moved all three ParallACT workspaces into ignored `data/private/parallact/`, verifying unchanged file hashes. Cache paths remain symlinks. No backup or sharing was created.

### 2026-11-08: Clarify public release terms

A targeted source check and Opus review support a curated release under existing terms. Preserve component licenses and notices; credit alone is insufficient. No raw data was published during this investigation.

## Maintaining this log

Record decisions and results, link evidence, distinguish plans from completed work and correct mistakes explicitly. Aim for roughly 500 words; consolidate at phase boundaries.
