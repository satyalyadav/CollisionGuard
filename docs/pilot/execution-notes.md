# Retained execution notes

These are historical execution artifacts, preserved after review. They ran against evolving earlier script versions. They are not instructions to rerun the data collection.

## Original job wrappers

### collisionguard-download-job.sh

```bash
#!/bin/bash
set -eu
cd /home/satyal/cse-572/Project
start=$(date -u +%FT%TZ)
deadline=$(date -u -d '+30 minutes' +%FT%TZ)
log=data/pilot/job.log
printf 'owner=%s purpose=download-and-inspect pid=%s start=%s deadline=%s checkpoint=%s\n' "$USER" "$$" "$start" "$deadline" 'data/pilot/sources.json' >> "$log"
timeout -k 20s 1800s /home/satyal/.cache/collisionguard-pilot/venv/bin/python scripts/pilot.py download >> "$log" 2>&1
printf 'finished=%s status=0\n' "$(date -u +%FT%TZ)" >> "$log"
```

### collisionguard-pilot-job.sh

```bash
#!/bin/bash
set -u
cd /home/satyal/cse-572/Project
start=$(date -u +%FT%TZ)
deadline=$(date -u -d '+30 minutes' +%FT%TZ)
log=data/pilot/job.log
printf 'owner=%s purpose=sample-and-audit pid=%s start=%s deadline=%s checkpoint=%s\n' "$USER" "$$" "$start" "$deadline" 'data/pilot/pairs/*.json' >> "$log"
timeout -k 20s 1800s /home/satyal/.cache/collisionguard-pilot/venv/bin/python scripts/pilot.py run >> "$log" 2>&1
status=$?
printf 'finished=%s status=%s\n' "$(date -u +%FT%TZ)" "$status" >> "$log"
exit "$status"
```

### collisionguard-diagnose-job.sh

```bash
#!/bin/bash
set -u
cd /home/satyal/cse-572/Project
start=$(date -u +%FT%TZ)
deadline=$(date -u -d '+30 minutes' +%FT%TZ)
log=data/pilot/job.log
printf 'owner=%s purpose=issue-evidence-and-git-diagnostics pid=%s start=%s deadline=%s checkpoint=%s\n' "$USER" "$$" "$start" "$deadline" 'data/pilot/pairs/*.json and counters.json' >> "$log"
timeout -k 20s 1800s /home/satyal/.cache/collisionguard-pilot/venv/bin/python scripts/pilot.py diagnose >> "$log" 2>&1
status=$?
printf 'finished=%s status=%s\n' "$(date -u +%FT%TZ)" "$status" >> "$log"
exit "$status"
```

## Evidence audit note

The original temporary note is retained below. Its first heading incorrectly calls PR-opening and first-commit timestamps lower-bound proxies. They are upper bounds on execution start, as the protocol states. The note did not retrieve issue edit histories.

````markdown
# CollisionGuard pre-start evidence notes

Read `docs/pilot/protocol.md`. Scope stayed to GitHub documentation and the AIDev v5 schema/API. No project files changed.

## Findings

1. **PR opening and first commit are lower-bound proxies, not task-start evidence.** AIDev v5 `pull_request` exposes `created_at`, but this marks PR creation. `pr_commits` contains `sha`, `pr_id`, `author`, `committer`, and `message`, with no commit timestamps. `pr_timeline` has `event`, `commit_id`, and `created_at`, but a probe's first row was a `committed` event with `created_at: null`. Even a non-null PR-open or commit-event timestamp only establishes a public GitHub event, not when work began. AIDev v5 sources: [pinned README](https://huggingface.co/datasets/hao-li/AIDev/blob/b8dc67df93e7c11f6f20c84129db7232eb1ec253/README.md), [first-rows API: pull_request](https://datasets-server.huggingface.co/first-rows?dataset=hao-li%2FAIDev&config=pull_request&split=train), [pr_commits](https://datasets-server.huggingface.co/first-rows?dataset=hao-li%2FAIDev&config=pr_commits&split=train), [pr_timeline](https://datasets-server.huggingface.co/first-rows?dataset=hao-li%2FAIDev&config=pr_timeline&split=train).

2. **AIDev's issue and PR rows are current snapshots, not version history.** The probed `issue` schema has `id, number, title, body, user, state, created_at, closed_at, html_url`; `pull_request` has current `title, body` and `created_at, closed_at, merged_at` among its fields. Neither schema has content revisions, `updated_at`, or task-start fields. Use the exact task wording only if a historical version can be recovered from GitHub edit history or an external snapshot whose capture time is known. AIDev tag `v5` resolved to revision `b8dc67df93e7c11f6f20c84129db7232eb1ec253` during this check.

3. **`updated_at` cannot identify the content change.** GitHub GraphQL describes `Issue.updatedAt` as when the object was last updated. The `Comment` interface implemented by `Issue` separately exposes `lastEditedAt` and `userContentEdits`. GitHub's `UserContentEdit` type exposes `editedAt`, `editor`, `diff`, and deletion metadata; docs call `diff` a summary of changes, not a complete historical body. `includesCreatedEdit` can be checked for creation data. These fields can place known text edits on a timeline, but the schema alone does not promise complete edit retention or guarantee the full original wording can be reconstructed. Sources: [GraphQL Issue](https://docs.github.com/en/graphql/reference/issues#issue), [Comment interface](https://docs.github.com/en/graphql/reference/issues#comment), [UserContentEdit](https://docs.github.com/en/graphql/reference/users#usercontentedit).

4. **The AIDev issue-link table has no link timestamp.** Its v5 schema is exactly `pr_id, issue_id, source`; a public first-rows probe returned `source: "body"` for sampled rows. This establishes a mapping and a source category, not when the link first existed. GitHub REST timeline `cross-referenced` events provide `created_at` (when the cross-reference was added), and GitHub GraphQL has `CrossReferencedEvent.referencedAt`. A specific event before both task starts is useful evidence that the reference was public by then; it does not prove the task was assigned or known then. Timeline event types and semantics: [GitHub REST issue event types](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types#cross-referenced), [GraphQL Issues](https://docs.github.com/en/graphql/reference/issues#crossreferencedevent). AIDev source: [first-rows API: related_issue](https://datasets-server.huggingface.co/first-rows?dataset=hao-li%2FAIDev&config=related_issue&split=train).

5. **Current PR head is not the original historical target.** GitHub GraphQL `PullRequest.headRefOid` identifies the head ref's OID, and REST `GET /repos/{owner}/{repo}/pulls/{pull_number}` returns the PR's head. Those represent the retrieved PR state, not the head at a past common pre-start time. AIDev's `pull_request` schema does not contain a head SHA; `pr_commits` lists SHAs but no times, so it cannot identify the target at the decision time. Preserve a current-head replay as a separate target and label original historical head unknown unless a timestamped historical ref/snapshot establishes it. Sources: [GraphQL PullRequest](https://docs.github.com/en/graphql/reference/pulls#pullrequest), [REST pull request endpoints](https://docs.github.com/en/rest/pulls/pulls).

## API probe and access note

Unauthenticated GraphQL probe command:

```sh
curl -sS -X POST https://api.github.com/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { __typename }"}' \
  -w '\nHTTP %{http_code}\n'
```

Result: HTTP 403, `API rate limit exceeded for 4.21.203.182`. This is an egress-IP rate-limit failure, so it did not test `userContentEdits` behavior. GitHub's GraphQL guide documents authenticated calls and token permissions, including read access for public repos: [Forming calls with GraphQL](https://docs.github.com/en/graphql/guides/forming-calls-with-graphql). No credentials were used.

The public AIDev probes were lightweight:

```sh
curl -sS 'https://datasets-server.huggingface.co/first-rows?dataset=hao-li/AIDev&config=related_issue&split=train'
for cfg in issue pull_request pr_timeline pr_commits; do
  curl -sS "https://datasets-server.huggingface.co/first-rows?dataset=hao-li/AIDev&config=$cfg&split=train"
done
```

The `related_issue` response schema was `pr_id:int64, issue_id:int64, source:string`. The other schemas and sample rows are listed in findings 1 and 2. No parquet data was downloaded.
````

## Summary and timestamp correction

The implementation activity record at position 131 shows one inline Python edit followed by `python scripts/pilot.py summarize` at approximately 2026-11-08 04:43:35 UTC. The inline edit added the summarizer and restored the three source manifest `recorded_at` fields to their earlier reported download timestamps. It did not invoke `download()`. This command was missing from the original job log. The source downloader start and finish are logged; the manifest timestamps were later corrected manually. Earlier collection script revisions were not retained with hashes. This limits exact reproduction of the historical run.
