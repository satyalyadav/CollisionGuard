"""Build the natural-mix cohort from the agentic-PR replication package.

The pair list and merge labels come from the public CC-BY package for
"Concurrent AI-Agent Pull Requests on GitHub" (Zenodo 10.5281/zenodo.21186464).
Task text comes from the AIDev pull-request, issue and repository tables. The
joined table contains task text, so it stays under the ignored private root.
The public summary carries counts, hashes and provenance only.

    python3 scripts/build_natural_cohort.py
    python3 scripts/build_natural_cohort.py --check

Protocol notes:
- Only evaluable rows are kept (labels CLEAN and CONFLICT).
- A pair is kept only when both PRs are present in the AIDev table.
- PR title and body are stored separately. Bodies often name changed files and
  are treated as a leaky upper bound, never as the primary input.
- At most one linked issue is chosen per PR, preferring explicit body links,
  then the lowest issue id. Pairs with a linked issue on both sides form the
  stricter issue-text subset.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private/research/natural-cohort-2026-11"
RAW = PRIVATE / "raw"
CSV = RAW / "rq3_merge_replay_full.csv"
PULLS = RAW / "pull_request.parquet"
ISSUES = RAW / "issue.parquet"
LINKS = RAW / "related_issue.parquet"
REPOS = RAW / "repository.parquet"
TABLE_OUT = PRIVATE / "table.json"
PUBLIC_OUT = ROOT / "data/natural-cohort-2026-11/summary.json"

PROTOCOL_VERSION = "natural-cohort-table-1"
EXPECTED_EVALUABLE = 716
EXPECTED_MATCHED = 673
EXPECTED_REPOS = 616


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def table_body_digest(table):
    body = {key: value for key, value in table.items()
            if key not in ("table_sha256", "built_at")}
    return _sha256_bytes(_canonical_json(body))


def verify_table(table):
    expected = table.get("table_sha256")
    actual = table_body_digest(table)
    if expected != actual:
        raise ValueError(f"table digest mismatch: saved {expected}, computed {actual}")


def _connect():
    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=2")
    con.execute("SET temp_directory='/tmp/opencode/ducktmp'")
    return con


def _require_inputs():
    for path in (CSV, PULLS, ISSUES, LINKS, REPOS):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")


def _load_pairs(con):
    con.execute(f"""
        CREATE TEMP TABLE replay AS
        SELECT * FROM read_csv_auto('{CSV}', header=true)
    """)
    con.execute("""
        CREATE TEMP TABLE pr AS
        SELECT
            number,
            title,
            body,
            agent,
            created_at,
            merged_at,
            state,
            id AS pr_id,
            regexp_replace(repo_url, '^https://api\\.github\\.com/repos/', '') AS slug
        FROM read_parquet(?)
    """, [str(PULLS)])
    duplicates = con.execute("""
        SELECT count(*) FROM (
            SELECT slug, number FROM pr GROUP BY 1, 2 HAVING count(*) > 1
        )
    """).fetchone()[0]
    if duplicates:
        raise ValueError(f"pull_request table has {duplicates} duplicate repo/number keys")

    con.execute("""
        CREATE TEMP TABLE linked AS
        SELECT pr_id, issue_id, source FROM read_parquet(?)
    """, [str(LINKS)])
    con.execute("""
        CREATE TEMP TABLE issue AS
        SELECT id AS issue_id, number AS issue_number, title AS issue_title,
               body AS issue_body, created_at AS issue_created_at
        FROM read_parquet(?)
        WHERE title IS NOT NULL AND length(trim(title)) > 0
    """, [str(ISSUES)])
    con.execute("""
        CREATE TEMP TABLE issue_choice AS
        SELECT pr_id, issue_id, source FROM (
            SELECT l.pr_id, l.issue_id, l.source,
                   row_number() OVER (
                       PARTITION BY l.pr_id
                       ORDER BY (l.source = 'body') DESC, l.issue_id
                   ) AS rn
            FROM linked l
            JOIN issue i ON i.issue_id = l.issue_id
        ) WHERE rn = 1
    """)

    con.execute(f"""
        CREATE TEMP TABLE joined AS
        SELECT
            r.repo, r.prA, r.prB, r.agentA, r.agentB, r.label, r.stratum,
            r.n_files, r.files, r.types,
            a.title AS title_a, a.body AS body_a, a.agent AS agent_a,
            a.created_at AS created_a, a.merged_at AS merged_a,
            b.title AS title_b, b.body AS body_b, b.agent AS agent_b,
            b.created_at AS created_b, b.merged_at AS merged_b,
            ia.issue_title AS issue_title_a, ia.issue_body AS issue_body_a,
            ia.issue_number AS issue_number_a, ia.issue_created_at AS issue_created_a,
            ca.source AS issue_source_a,
            ib.issue_title AS issue_title_b, ib.issue_body AS issue_body_b,
            ib.issue_number AS issue_number_b, ib.issue_created_at AS issue_created_b,
            cb.source AS issue_source_b
        FROM replay r
        LEFT JOIN pr a ON a.slug = r.repo AND a.number = r.prA
        LEFT JOIN pr b ON b.slug = r.repo AND b.number = r.prB
        LEFT JOIN issue_choice ca ON ca.pr_id = a.pr_id
        LEFT JOIN issue ia ON ia.issue_id = ca.issue_id
        LEFT JOIN issue_choice cb ON cb.pr_id = b.pr_id
        LEFT JOIN issue ib ON ib.issue_id = cb.issue_id
        WHERE r.label IN ('CLEAN', 'CONFLICT')
    """)
    return con


def _rows(con):
    rows = con.execute("""
        SELECT j.*, rp.language, rp.license, rp.stars, rp.is_forked
        FROM joined j
        LEFT JOIN read_parquet(?) rp ON rp.full_name = j.repo
        WHERE j.title_a IS NOT NULL AND j.title_b IS NOT NULL
        ORDER BY j.repo, j.prA, j.prB
    """, [str(REPOS)]).fetchall()
    columns = [d[0] for d in con.description]
    return [dict(zip(columns, row)) for row in rows]


def _instance_id(repo, pr_a, pr_b):
    digest = _sha256_bytes(f"{repo}#{pr_a}#{pr_b}".encode("utf-8"))[:12]
    return f"nc-{digest}"


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _paths(value):
    if not value:
        return []
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _pair(row):
    title_a, title_b = _clean(row["title_a"]), _clean(row["title_b"])
    if not title_a or not title_b:
        return None
    label = "conflict" if row["label"] == "CONFLICT" else "clean"
    issue_title_a, issue_title_b = _clean(row["issue_title_a"]), _clean(row["issue_title_b"])
    return {
        "instance_id": _instance_id(row["repo"], row["prA"], row["prB"]),
        "repo": row["repo"],
        "pr_a": int(row["prA"]),
        "pr_b": int(row["prB"]),
        "label": label,
        "stratum": row["stratum"],
        "agent_a": _clean(row["agent_a"]) or _clean(row["agentA"]),
        "agent_b": _clean(row["agent_b"]) or _clean(row["agentB"]),
        "created_a": _clean(row["created_a"]),
        "created_b": _clean(row["created_b"]),
        "title_a": title_a,
        "title_b": title_b,
        "body_a": _clean(row["body_a"]),
        "body_b": _clean(row["body_b"]),
        "issue_number_a": row["issue_number_a"],
        "issue_number_b": row["issue_number_b"],
        "issue_source_a": _clean(row["issue_source_a"]),
        "issue_source_b": _clean(row["issue_source_b"]),
        "issue_created_a": _clean(row["issue_created_a"]),
        "issue_created_b": _clean(row["issue_created_b"]),
        "issue_title_a": issue_title_a,
        "issue_title_b": issue_title_b,
        "issue_body_a": _clean(row["issue_body_a"]),
        "issue_body_b": _clean(row["issue_body_b"]),
        "language": _clean(row["language"]),
        "license": _clean(row["license"]),
        "stars": int(row["stars"]) if row["stars"] is not None else None,
        "is_forked": bool(row["is_forked"]) if row["is_forked"] is not None else None,
        "conflict_paths": _paths(row["files"]),
        "conflict_types": _paths(row["types"]),
    }


def _summary(table):
    pairs = table["pairs"]
    labels = [pair["label"] for pair in pairs]
    both_issue = [pair for pair in pairs
                  if pair["issue_title_a"] and pair["issue_title_b"]]
    both_body = [pair for pair in pairs if pair["body_a"] and pair["body_b"]]
    languages = {}
    for pair in pairs:
        key = pair["language"] or "unknown"
        languages[key] = languages.get(key, 0) + 1
    licenses = {}
    for pair in pairs:
        key = pair["license"] or "unknown"
        licenses[key] = licenses.get(key, 0) + 1
    strata = {}
    for pair in pairs:
        strata[pair["stratum"]] = strata.get(pair["stratum"], 0) + 1
    repos = {pair["repo"] for pair in pairs}
    return {
        "protocol_version": PROTOCOL_VERSION,
        "pairs": len(pairs),
        "clean": labels.count("clean"),
        "conflict": labels.count("conflict"),
        "prevalence": labels.count("conflict") / len(pairs) if pairs else None,
        "repositories": len(repos),
        "pairs_per_repo": {
            "one": sum(1 for repo in repos
                       if sum(1 for p in pairs if p["repo"] == repo) == 1),
            "more_than_one": sum(1 for repo in repos
                                 if sum(1 for p in pairs if p["repo"] == repo) > 1),
        },
        "strata": strata,
        "both_pr_bodies": len(both_body),
        "both_linked_issues": len(both_issue),
        "both_linked_issue_conflicts": sum(1 for p in both_issue if p["label"] == "conflict"),
        "languages": dict(sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))),
        "licenses": dict(sorted(licenses.items(), key=lambda kv: (-kv[1], kv[0]))),
        "source": table["source"],
        "table_sha256": table["table_sha256"],
        "task_text_public": False,
        "note": ("Pair list and labels from the CC-BY replication package. "
                 "Task text joined from AIDev and kept private; public summary "
                 "carries counts, provenance and hashes only."),
    }


def build():
    _require_inputs()
    con = _connect()
    _load_pairs(con)
    rows = _rows(con)
    pairs = [pair for pair in (_pair(row) for row in rows) if pair is not None]
    pairs.sort(key=lambda pair: (pair["repo"].casefold(), pair["pr_a"], pair["pr_b"]))
    if len(pairs) != EXPECTED_MATCHED:
        raise ValueError(f"expected {EXPECTED_MATCHED} matched pairs, got {len(pairs)}")
    repos = {pair["repo"] for pair in pairs}
    if len(repos) != EXPECTED_REPOS:
        raise ValueError(f"expected {EXPECTED_REPOS} repositories, got {len(repos)}")

    source = {
        "replication_package": {
            "doi": "10.5281/zenodo.21186464",
            "repository": "Quantum535/concurrent-agentic-prs-replication",
            "license": "CC-BY-4.0",
            "file": "rq3_merge_replay_full.csv",
            "sha256": _sha256_file(CSV),
            "evaluable_rows": EXPECTED_EVALUABLE,
        },
        "task_text": {
            "dataset": "hao-li/AIDev",
            "revision": "main as retrieved 2026-11-21",
            "files": {
                path.name: {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
                for path in (PULLS, ISSUES, LINKS, REPOS)
            },
        },
    }
    table = {
        "protocol_version": PROTOCOL_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "counts": {
            "evaluable_pairs": EXPECTED_EVALUABLE,
            "matched_pairs": len(pairs),
            "repositories": len(repos),
            "clean": sum(1 for p in pairs if p["label"] == "clean"),
            "conflict": sum(1 for p in pairs if p["label"] == "conflict"),
            "both_linked_issues": sum(1 for p in pairs
                                      if p["issue_title_a"] and p["issue_title_b"]),
        },
        "pairs": pairs,
    }
    table["table_sha256"] = table_body_digest(table)
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the saved table instead of rebuilding it")
    args = parser.parse_args(argv)
    if args.check:
        table = json.loads(TABLE_OUT.read_text(encoding="utf-8"))
        verify_table(table)
        summary = json.loads(PUBLIC_OUT.read_text(encoding="utf-8"))
        if summary["table_sha256"] != table["table_sha256"]:
            raise ValueError("public summary does not match the private table")
        if summary["pairs"] != len(table["pairs"]):
            raise ValueError("public summary pair count does not match the table")
        print(f"table ok: {len(table['pairs'])} pairs, sha256 {table['table_sha256']}")
        return

    table = build()
    TABLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TABLE_OUT.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    summary = _summary(table)
    PUBLIC_OUT.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    print(f"wrote {TABLE_OUT.relative_to(ROOT)} ({len(table['pairs'])} pairs)")
    print(f"wrote {PUBLIC_OUT.relative_to(ROOT)}")
    print(f"conflict {summary['conflict']} / {summary['pairs']} "
          f"({summary['prevalence']:.3f}); repositories {summary['repositories']}; "
          f"both-linked issues {summary['both_linked_issues']}")


if __name__ == "__main__":
    main()
