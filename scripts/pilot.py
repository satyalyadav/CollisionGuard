#!/usr/bin/env python3
"""Collect a frozen AIDev sample and audit current GitHub evidence."""
import datetime as dt
from array import array
import struct
import hashlib
import json
import os
import random
import re
import shutil
import select
import socket
import socketserver
import threading
import tempfile
import subprocess
from pathlib import Path
import sys
import time

import requests

REV = 'b8dc67df93e7c11f6f20c84129db7232eb1ec253'
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/pilot'
CACHE = Path(os.environ.get('PILOT_CACHE', Path.home() / '.cache/collisionguard-pilot'))
LIMIT = 2 * 1024**3
FILES = ('pull_request.parquet', 'issue.parquet', 'related_issue.parquet')
PROVENANCE_FIELDS = ('description_provenance', 'prestart_eligibility', 'historical_head_provenance', 'prestart_base_provenance')
SOURCE_HASHES = {
    'pull_request.parquet': 'a9341e2ef692ae4220830b046da228000becc623a1591c5634728d78c331c32b',
    'issue.parquet': 'fc45ba381ca3566a88ffce91272dd0a37eba3fa31e681a333ef2ded85e9c3a30',
    'related_issue.parquet': '16a22395a2572b29345888c76aba4c39e98dc1cf79b54685a521451c469e7aef',
}
APPROVED_PROTOCOL_ADDENDUM = (
    '13ebc4e1bd792dc7236ff4cd60cf35254c38107fd02500a083d770bbd543abb6',
    'd5ee70877055b03bfadf09220ca08332bf03ac51d4c087974ae39e1b9d27fca7',
)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    with tmp.open() as f:
        json.load(f)
    os.replace(tmp, path)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def download():
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = []
    previous_path = OUT / 'sources.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    known = {f['name']: f for f in previous.get('files', [])} if previous.get('revision') == REV else {}
    for name in FILES:
        url = f'https://huggingface.co/datasets/hao-li/AIDev/resolve/{REV}/{name}'
        path = CACHE / name
        if not path.exists():
            inflight_source = OUT / 'source-transfer-inflight.json'
            if inflight_source.exists():
                raise RuntimeError('Previous source transfer interrupted; budget requires reconciliation')
            save(inflight_source, {'name': name, 'started_at': now()})
            with requests.get(url, stream=True, timeout=(20, 90)) as r:
                r.raise_for_status()
                length = r.headers.get('Content-Length')
                used = sum(p.stat().st_size for p in CACHE.glob('*.parquet'))
                if length is None or int(length) > LIMIT - used:
                    raise RuntimeError(f'No usable content length or budget exceeded: {name} {length}')
                tmp = path.with_suffix('.part')
                total = 0
                try:
                    with tmp.open('wb') as f:
                        for chunk in r.iter_content(1024 * 1024):
                            total += len(chunk)
                            if total > int(length) or total + used > LIMIT:
                                raise RuntimeError('Download exceeded declared size or budget')
                            f.write(chunk)
                    if total != int(length):
                        raise RuntimeError('Incomplete download')
                    os.replace(tmp, path)
                    inflight_source.unlink()
                finally:
                    tmp.unlink(missing_ok=True)
        checksum = digest(path)
        if name in known and checksum != known[name]['sha256']:
            raise RuntimeError('Cached immutable file differs from recorded hash: ' + name)
        manifest.append(known.get(name) or dict(name=name, url=url, bytes=path.stat().st_size, sha256=checksum, recorded_at=now()))
        save(OUT / 'sources.json', dict(revision=REV, files=manifest))
    return manifest

def choose_candidates(candidates, seed=39, limit=20, per_repo=4):
    """Shuffle stable pair IDs, then greedily enforce repo and PR caps."""
    candidates = sorted(candidates, key=lambda x: (x['repo_id'], x['pr1_id'], x['pr2_id']))
    random.Random(seed).shuffle(candidates)
    picked, used, counts = [], set(), {}
    for item in candidates:
        repo = item['repo_id']
        if counts.get(repo, 0) >= per_repo or item['pr1_id'] in used or item['pr2_id'] in used:
            continue
        if set(item['issue1_ids']) & set(item['issue2_ids']):
            continue
        picked.append(item)
        used.update((item['pr1_id'], item['pr2_id']))
        counts[repo] = counts.get(repo, 0) + 1
        if len(picked) == limit:
            break
    return picked


def strict_eligibility(record):
    """All fields require independently verified evidence and a repeated primary label."""
    primary = record.get('primary_replay', {})
    snapshot = record.get('prestart_base_provenance', {}).get('sha')
    return (all(record.get(k, {}).get('status') == 'verified' for k in PROVENANCE_FIELDS)
            and bool(snapshot) and primary.get('merge_bases') == [snapshot]
            and primary.get('expected_base') == snapshot
            and primary.get('heads') == record.get('historical_head_provenance', {}).get('heads')
            and len(primary.get('heads', [])) == 2
            and primary.get('status') in ('CLEAN', 'CONFLICT')
            and primary.get('repeat_status') == primary.get('status')
            and bool(primary.get('tree_id'))
            and primary.get('repeat_tree_id') == primary.get('tree_id')
            and primary.get('repeated') is True)


def git(repo, *args, timeout=90):
    env = os.environ.copy()
    for key in ('NO_PROXY', 'no_proxy', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT',
                'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        env.pop(key, None)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1', GIT_NO_LAZY_FETCH='1')
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never', '-c', 'http.proxy=' + os.environ.get('PILOT_HTTP_PROXY', ''), '-C', str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, env=env)


def replay(repo, head1, head2, primary=False, expected_base=None):
    """Replay fixed objects and retain ambiguity and operational errors."""
    result = {'heads': [head1, head2], 'command': 'git merge-tree --write-tree --messages HEAD1 HEAD2', 'git_version': subprocess.check_output(['git', '--version'], text=True).strip()}
    if result['git_version'] != 'git version 2.43.0':
        result.update(status='ERROR', reason='Git version differs from pinned 2.43.0')
        return result
    try:
        shallow = git(repo, 'rev-parse', '--is-shallow-repository')
        if shallow.returncode:
            raise RuntimeError(shallow.stderr.strip())
        result['shallow'] = shallow.stdout.strip() == 'true'
        bases = git(repo, 'merge-base', '--all', head1, head2)
        result['merge_bases'] = bases.stdout.splitlines()
        if bases.returncode != 0 or not result['merge_bases'] or (primary and len(result['merge_bases']) != 1):
            result.update(status='ERROR', reason='missing base, or multiple bases for a primary replay', detail=bases.stderr[:1000])
            return result
        if primary:
            result['expected_base'] = expected_base
            if not expected_base or result['merge_bases'] != [expected_base]:
                result.update(status='ERROR', reason='primary base differs from verified pre-start snapshot')
                return result
            if any(git(repo, 'merge-base', '--is-ancestor', expected_base, head).returncode for head in (head1, head2)):
                result.update(status='ERROR', reason='primary heads do not descend from verified snapshot')
                return result
        merged = git(repo, 'merge-tree', '--write-tree', '--messages', head1, head2)
        result.update(exit_code=merged.returncode, stdout=merged.stdout[:12000], stderr=merged.stderr[:2000], output_truncated=len(merged.stdout) > 12000 or len(merged.stderr) > 2000)
        lines = merged.stdout.splitlines()
        result['tree_id'] = lines[0] if lines and re.fullmatch(r'[0-9a-f]{40,64}', lines[0]) else None
        result['conflict_paths'] = sorted({line.split('\t', 1)[1] for line in lines[1:] if '\t' in line and re.match(r'^[0-7]{6} [0-9a-f]+ [123]\t', line)})
        result['conflict_messages'] = [line for line in lines if line.startswith('CONFLICT (')]
        if merged.returncode not in (0, 1):
            result.update(status='ERROR', reason='merge-tree operational error')
        elif result['shallow']:
            result.update(status='ERROR', reason='shallow history: merge base completeness unverified', provisional_status='CLEAN' if merged.returncode == 0 else 'CONFLICT')
        else:
            result['status'] = 'CLEAN' if merged.returncode == 0 else 'CONFLICT'
        if primary and result['status'] in ('CLEAN', 'CONFLICT'):
            repeated = git(repo, 'merge-tree', '--write-tree', '--messages', head1, head2)
            result['repeat_status'] = {0: 'CLEAN', 1: 'CONFLICT'}.get(repeated.returncode, 'ERROR')
            result['repeat_tree_id'] = repeated.stdout.splitlines()[0] if repeated.stdout else None
            result['repeated'] = bool(result['tree_id']) and result['repeat_status'] == result['status'] and result['repeat_tree_id'] == result['tree_id']
            if not result['repeated']:
                result.update(status='ERROR', reason='primary replay did not reproduce label and tree')
        result['conflict_types'] = 'Git merge-tree reports textual and non-text conflicts; output retained above' if merged.returncode == 1 else None
        return result
    except (subprocess.TimeoutExpired, OSError, RuntimeError) as e:
        result.update(status='ERROR', reason=str(e))
        return result


CUTOFF = '2026-03-31T23:59:59Z'


def validate_frozen(sample):
    current_protocol = digest(ROOT / 'docs/pilot/protocol.md')
    frozen_protocol = sample.get('protocol_sha256')
    if sample.get('revision') != REV or (current_protocol != frozen_protocol and
            (frozen_protocol, current_protocol) != APPROVED_PROTOCOL_ADDENDUM):
        raise RuntimeError('Frozen sample source revision or protocol changed; explicit new pilot required')
    sources = json.loads((OUT / 'sources.json').read_text())
    recorded = {f['name']: f['sha256'] for f in sources['files']}
    expected = sample.get('source_sha256') or SOURCE_HASHES
    if sources.get('revision') != REV or recorded != expected:
        raise RuntimeError('Frozen sample source hashes changed')
    for name, checksum in expected.items():
        if digest(CACHE / name) != checksum:
            raise RuntimeError('Cached source hash changed: ' + name)


def freeze():
    import duckdb
    path = OUT / 'sample.json'
    if path.exists():
        sample = json.loads(path.read_text())
        validate_frozen(sample)
        return sample
    con = duckdb.connect()
    con.execute("SET memory_limit='256MB'; SET threads=1; SET TimeZone='UTC'")
    con.execute("SET temp_directory=?", [str(CACHE / 'duckdb-tmp')])
    pr, links = (str(CACHE / name) for name in ('pull_request.parquet', 'related_issue.parquet'))
    con.execute("""CREATE TEMP TABLE linked AS
        SELECT pr_id, list_sort(list_distinct(list(issue_id))) AS issues
        FROM read_parquet(?) WHERE issue_id IS NOT NULL GROUP BY pr_id""", [links])
    con.execute("""CREATE TEMP TABLE population AS
        SELECT p.id, p.number, p.repo_id, p.repo_url, p.agent, try_cast(p.created_at AS TIMESTAMPTZ) AS created_at,
        least(coalesce(try_cast(p.closed_at AS TIMESTAMPTZ), cast(? AS TIMESTAMPTZ)), cast(? AS TIMESTAMPTZ)) AS endpoint, l.issues
        FROM read_parquet(?) p JOIN linked l ON p.id=l.pr_id
        WHERE p.repo_id IS NOT NULL AND p.id IS NOT NULL
          AND try_cast(p.created_at AS TIMESTAMPTZ) IS NOT NULL
          AND (p.closed_at IS NULL OR try_cast(p.closed_at AS TIMESTAMPTZ) IS NOT NULL)""", [CUTOFF, CUTOFF, pr])
    cursor = con.execute("""SELECT a.repo_id, a.id, b.id
        FROM population a JOIN population b ON a.repo_id=b.repo_id AND a.id < b.id
        WHERE a.created_at < a.endpoint AND b.created_at < b.endpoint
          AND a.created_at < b.endpoint AND b.created_at < a.endpoint
          AND NOT list_has_any(a.issues,b.issues)
        ORDER BY a.repo_id,a.id,b.id""")
    frame_path = CACHE / 'candidate-frame.bin'
    frame_size = 0
    with frame_path.open('wb') as frame:
        while batch := cursor.fetchmany(10000):
            frame.writelines(struct.pack('>QQQ', *row) for row in batch)
            frame_size += len(batch)
    indices = array('I', range(frame_size))
    random.Random(39).shuffle(indices)
    chosen_ids, used, counts = [], set(), {}
    with frame_path.open('rb') as frame:
        for index in indices:
            frame.seek(index * 24)
            repo, a, b = struct.unpack('>QQQ', frame.read(24))
            if counts.get(repo, 0) >= 4 or a in used or b in used:
                continue
            chosen_ids.append((repo, a, b))
            counts[repo] = counts.get(repo, 0) + 1
            used.update((a, b))
            if len(chosen_ids) == 20:
                break
    selected = []
    for repo, a, b in chosen_ids:
        records = con.execute('SELECT id,number,repo_url,agent,CAST(created_at AS VARCHAR),CAST(endpoint AS VARCHAR),issues FROM population WHERE id IN (?, ?)', [a,b]).fetchall()
        by_id = {r[0]: r for r in records}
        one, two = by_id[a], by_id[b]
        selected.append(dict(repo_id=repo, pr1_id=a, pr2_id=b, pr1_number=one[1], pr2_number=two[1], repo_url=one[2], agent1=one[3], agent2=two[3], start1=one[4], end1=one[5], start2=two[4], end2=two[5], issue1_ids=one[6], issue2_ids=two[6]))
    protocol = ROOT / 'docs/pilot/protocol.md'
    result = {'protocol_version': 2, 'protocol_sha256': digest(protocol), 'frozen_at': now(), 'revision': REV,
              'cutoff': CUTOFF, 'frame_size': frame_size, 'selection': 'stable numeric repo/pr/pr sort; Python random.Random(39).shuffle; greedy cap 4/repo and no PR reuse',
              'python_version': sys.version, 'selected': selected,
              'source_sha256': {name: digest(CACHE / name) for name in FILES if (CACHE / name).exists()},
              'repository_visitation_order': list(dict.fromkeys(p['repo_id'] for p in selected))}
    save(path, result)
    return result


def fetch_json(url, counters):
    with requests.get(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'CollisionGuard-feasibility-pilot'}, timeout=(10, 25), stream=True) as r:
        data = bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            counters['github_response_bytes'] += len(chunk)
            if len(data) > 2 * 1024 * 1024:
                raise RuntimeError('API response exceeds 2 MiB')
        message = bytes(data).lower()
        if r.status_code == 429 or (r.status_code == 403 and
                (r.headers.get('X-RateLimit-Remaining') == '0' or b'rate limit' in message or r.headers.get('Retry-After'))):
            raise RuntimeError('RATE_LIMIT reset=' + r.headers.get('X-RateLimit-Reset', 'unknown'))
        r.raise_for_status()
        return json.loads(data)


def audit():
    sample = freeze()
    if len(sample['selected']) != 20 or len(sample['repository_visitation_order']) < 5:
        save(OUT / 'run.json', {'status': 'NOT_ASSESSABLE', 'reason': 'incomplete sampling frame or sample'})
        return
    counters_path = OUT / 'counters.json'
    counters = json.loads(counters_path.read_text()) if counters_path.exists() else {'github_response_bytes': 0, 'git_transfer_bytes': 'NOT_VERIFIED', 'git_budget': 'NOT_VERIFIED'}
    failures = 0
    # The selected PR API contains current heads; this is never evidence for original run outputs.
    for item in sample['selected']:
        name = f"{item['repo_id']}-{item['pr1_id']}-{item['pr2_id']}"
        path = OUT / 'pairs' / (name + '.json')
        if path.exists() and not json.loads(path.read_text()).get('collection_interrupted'):
            continue
        record = {'sample': item, 'audited_at': now(), 'collector_script_sha256': digest(Path(__file__)),
                  **{key: {'status': 'not_checked', 'reason': 'Historical evidence not queried in this pilot'} for key in PROVENANCE_FIELDS},
                  'primary_replay': {'status': 'UNAVAILABLE', 'reason': 'Original run heads and pre-start snapshot unverified'},
                  'current_replay': {'status': 'UNAVAILABLE', 'reason': 'Not attempted'}, 'strict_valid': False}
        try:
            repo_url = item['repo_url']
            prs = [fetch_json(repo_url + '/pulls/' + str(item[f'pr{i}_number']), counters) for i in (1, 2)]
            record['current_heads'] = [{'sha': p['head']['sha'], 'base_sha': p['base']['sha'], 'observed_at': now(), 'api_url': p['url']} for p in prs]
            record['current_replay']['reason'] = 'Git diagnostic not attempted'
            failures = 0
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as e:
            record['current_replay']['reason'] = 'API access failed: ' + str(e)[:500]
            failures += 1
            if 'RATE_LIMIT' in str(e):
                record['collection_interrupted'] = True
        save(path, record)
        save(counters_path, counters)
        if record.get('collection_interrupted') or failures >= 3:
            break
    paths = list((OUT / 'pairs').glob('*.json')) if (OUT / 'pairs').exists() else []
    save(OUT / 'run.json', {'status': 'NOT_ASSESSABLE', 'collection_status': 'current_metadata_collected' if len(paths) == 20 else 'incomplete', 'selected': 20, 'completed_records': len(paths), 'github_response_bytes': counters['github_response_bytes'], 'script_sha256': digest(Path(__file__)), 'finished_at': now()})


def enrich():
    import duckdb
    con = duckdb.connect()
    con.execute("SET memory_limit='256MB'; SET threads=1")
    for path in sorted((OUT / 'pairs').glob('*.json')):
        record = json.loads(path.read_text())
        if 'issue_evidence' in record:
            continue
        item = record['sample']
        evidence = []
        for i in (1, 2):
            links = con.execute("SELECT issue_id, source FROM read_parquet(?) WHERE pr_id=? ORDER BY issue_id,source", [str(CACHE / 'related_issue.parquet'), item[f'pr{i}_id']]).fetchall()
            entries = []
            for issue_id, source in links:
                row = con.execute("SELECT id,number,title,body,created_at,html_url FROM read_parquet(?) WHERE id=?", [str(CACHE / 'issue.parquet'), issue_id]).fetchone()
                if row is None:
                    entries.append({'id': issue_id, 'link_source': source, 'issue_row': 'missing'})
                    continue
                payload = json.dumps({'title': row[2], 'body': row[3]}, sort_keys=True, ensure_ascii=False).encode()
                entries.append({'id': issue_id, 'number': row[1], 'link_source': source, 'url': row[5], 'created_at': row[4], 'title_body_sha256': hashlib.sha256(payload).hexdigest(), 'source_revision': REV, 'historical_revision': 'unknown; no edit history in source table', 'link_time': 'unknown'})
            evidence.append({'pr_id': item[f'pr{i}_id'], 'issues': entries})
        record['issue_evidence'] = evidence
        save(path, record)


class MeteredTunnel(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(10)
        header = b''
        while b'\r\n\r\n' not in header and len(header) < 16384:
            data = client.recv(4096)
            if not data:
                return
            header += data
        if not header.startswith(b'CONNECT github.com:443 '):
            client.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
            return
        try:
            with socket.create_connection(('github.com', 443), timeout=10) as remote:
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                while True:
                    ready, _, _ = select.select([client, remote], [], [], 30)
                    if not ready:
                        return
                    for src in ready:
                        chunk = src.recv(32768)
                        if not chunk:
                            return
                        # Count encrypted traffic in both directions, a conservative upper bound
                        # on response-body transfer including failed and partial attempts.
                        with self.server.lock:
                            if self.server.used + len(chunk) > self.server.cap:
                                self.server.exhausted = True
                                return
                            self.server.used += len(chunk)
                        (remote if src is client else client).sendall(chunk)
        except (OSError, TimeoutError):
            return


class TunnelServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def diagnose():
    sample = json.loads((OUT / 'sample.json').read_text())
    validate_frozen(sample)
    inflight = OUT / 'git-transfer-inflight.json'
    if inflight.exists():
        raise RuntimeError('Previous Git transfer interrupted; wire budget cannot be safely resumed')
    counters_path = OUT / 'counters.json'
    counters = json.loads(counters_path.read_text())
    counters.setdefault('git_wire_bytes', 0)
    counters.setdefault('git_by_repository', {})
    source_bytes = sum(f['bytes'] for f in json.loads((OUT / 'sources.json').read_text())['files'])
    # Preserve sample order and stop after three consecutive transport failures.
    failures = counters.get('git_consecutive_failures', 0)
    if failures >= 3:
        raise RuntimeError('Git source paused after three failures; investigate before resetting counter')
    for item in sample['selected']:
        pairpath = OUT / 'pairs' / f"{item['repo_id']}-{item['pr1_id']}-{item['pr2_id']}.json"
        if not pairpath.exists():
            continue
        record = json.loads(pairpath.read_text())
        if 'current_heads' not in record or record.get('diagnostic_attempted'):
            continue
        repo = str(item['repo_id'])
        already = counters['git_by_repository'].get(repo, 0)
        cap = min(64 * 1024**2 - already, LIMIT - source_bytes - counters['github_response_bytes'] - counters['git_wire_bytes'])
        if cap <= 0:
            record['current_replay'] = {'status': 'UNAVAILABLE', 'reason': 'Network budget exhausted'}
            record['diagnostic_attempted'] = now()
            save(pairpath, record)
            continue
        save(inflight, {'repo_id': repo, 'started_at': now(), 'remaining_wire_cap': cap})
        server = TunnelServer(('127.0.0.1', 0), MeteredTunnel)
        server.lock = threading.Lock()
        server.used = 0
        server.cap = cap
        server.exhausted = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ['PILOT_HTTP_PROXY'] = 'http://127.0.0.1:' + str(server.server_address[1])
        record['diagnostic_attempted'] = now()
        record['diagnostic_script_sha256'] = digest(Path(__file__))
        try:
            with tempfile.TemporaryDirectory(prefix='collisionguard-git-', dir=CACHE) as tmp:
                init = git(tmp, '-c', 'init.templateDir=', 'init', '--bare', '-q', '--template=', tmp, timeout=10)
                if init.returncode:
                    raise RuntimeError(init.stderr)
                heads = [x['sha'] for x in record['current_heads']]
                url = item['repo_url'].replace('https://api.github.com/repos/', 'https://github.com/') + '.git'
                fetch = git(tmp, '-c', 'http.version=HTTP/1.1', 'fetch', '--no-tags', '--no-recurse-submodules', '--depth=50', url, *heads, timeout=100)
                if fetch.returncode:
                    record['current_replay'] = {'status': 'ERROR', 'reason': 'repository transfer budget exhausted' if server.exhausted else 'bounded Git fetch failed', 'exit_code': fetch.returncode, 'stderr': fetch.stderr[-2000:]}
                else:
                    record['current_replay'] = replay(tmp, *heads)
                record['current_replay']['fetch_command'] = 'git fetch --no-tags --no-recurse-submodules --depth=50 URL HEAD1 HEAD2'
                record['current_replay']['fetch_url'] = url
                record['current_replay']['history'] = 'Depth 50; incomplete histories cannot establish complete merge bases.'
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            record['current_replay'] = {'status': 'ERROR', 'reason': str(e)}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            os.environ.pop('PILOT_HTTP_PROXY', None)
            counters['git_wire_bytes'] += server.used
            counters['git_by_repository'][repo] = already + server.used
            record['git_wire_bytes'] = server.used
            record['git_cap_exhausted'] = server.exhausted
            if server.exhausted:
                record['current_replay']['reason'] = 'repository transfer budget exhausted'
            elif record['current_replay'].get('reason') == 'bounded Git fetch failed':
                failures += 1
            else:
                failures = 0
            counters['git_consecutive_failures'] = failures
            save(counters_path, counters)
            save(pairpath, record)
            inflight.unlink()
        if failures >= 3:
            break


def assess(sample, records):
    """Keep unchecked primary evidence separate from failed secondary diagnostics."""
    def key(item):
        return item['repo_id'], item['pr1_id'], item['pr2_id']
    selected = {key(item) for item in sample['selected']}
    by_pair = {key(record['sample']): record for record in records}
    structural = (len(sample['selected']) == len(selected) == len(records) == len(by_pair) == 20
                  and set(by_pair) == selected and len({item[0] for item in selected}) >= 5)
    unfinished = not structural or any(
        record.get('collection_interrupted') or any(
            record.get(field, {}).get('status') in (None, 'not_checked') for field in PROVENANCE_FIELDS)
        or (all(record.get(field, {}).get('status') == 'verified' for field in PROVENANCE_FIELDS)
            and record.get('primary_replay', {}).get('status') not in ('CLEAN', 'CONFLICT', 'ERROR'))
        for record in records)
    strict = [record for record in records if strict_eligibility(record)]
    labels = {record['primary_replay']['status'] for record in strict}
    repos = {record['sample']['repo_id'] for record in strict}
    verdict = 'NOT_ASSESSABLE' if unfinished else ('GO' if len(strict) >= 10 and len(repos) >= 5 and labels == {'CLEAN', 'CONFLICT'} else 'NO_GO')
    return dict(status=verdict, selected=len(sample['selected']), completed_records=len(records),
                strict_valid=len(strict), strict_repositories=len(repos), strict_labels=sorted(labels),
                reason='Primary evidence collection is incomplete' if unfinished else 'Primary evidence assessed against the fixed gate')


def summarize():
    sample = json.loads((OUT / 'sample.json').read_text())
    records = [json.loads(p.read_text()) for p in (OUT / 'pairs').glob('*.json')]
    counters = json.loads((OUT / 'counters.json').read_text())
    previous_path = OUT / 'run.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    save(previous_path, {**assess(sample, records), 'github_response_bytes': counters['github_response_bytes'],
         'git_wire_bytes': counters.get('git_wire_bytes', 0), 'summary_script_sha256': digest(Path(__file__)),
         'collection_script_sha256': previous.get('collection_script_sha256'),
         'original_summary_at': previous.get('original_summary_at', previous.get('finished_at')),
         'finished_at': now()})


if __name__ == '__main__':
    if sys.argv[1:] == ['download']:
        download()
    elif sys.argv[1:] == ['diagnose']:
        enrich()
        diagnose()
        summarize()
    elif sys.argv[1:] == ['summarize']:
        summarize()
    elif sys.argv[1:] == ['run']:
        download()
        audit()
        summarize()
    else:
        raise SystemExit('usage: pilot.py download|run|diagnose|summarize')
