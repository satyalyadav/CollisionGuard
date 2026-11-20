#!/usr/bin/env python3
"""Bounded SWE-rebench import and replay pilot (see docs/pilot/swe-rebench-protocol.md).

Subcommands: select (offline), collect (network + local replay), summarize (offline).
Nothing downloaded is executed. Run long commands under `timeout -k`.
Reuses scripts/audit_benchmark_sources.py (archive replay, Git environment) by import.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_benchmark_sources as audit  # noqa: E402  (sets NO_PROXY, Git environment)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'data/private/research/swe-rebench-verification-2026-11'
RAW = ROOT / 'data/private/research/swe-rebench-pilot'
PUBLIC = ROOT / 'data/swe-rebench-pilot'
SEED = 572
GIT_VERSION = 'git version 2.43.0'
TASK_REV = '89cdfbab4ab1bd8f5a658bb212d1b63624f4f881'
TRACE_REV = '35455389ab51bf5e2306bfd436ef72d0f98bf882'
TASK_SET, TRACE_SET = 'nebius/SWE-rebench', 'nebius/SWE-rebench-openhands-trajectories'
MIB = 1024 * 1024
TOTAL_BUDGET, IMAGE_BUDGET, LAYER_CAP, META_CAP = 512 * MIB, 128 * MIB, 64 * MIB, 8 * MIB
DECODED_CAP, MEMBER_CAP = 512 * MIB, 64 * MIB
CONTROL = ['aio-libs__yarl-1413', 'aio-libs__yarl-1414']
EXCLUDED_REPOS = {x.casefold() for x in [
    'NodeBB/NodeBB', 'ansible/ansible', 'flipt-io/flipt', 'future-architect/vuls', 'gravitational/teleport',
    'internetarchive/openlibrary', 'navidrome/navidrome', 'protonmail/webclients', 'element-hq/element-web',
    'dottxt-ai/outlines', 'stanfordnlp/dspy', 'connectbot/connectbot', 'ARMmbed/mbed-tools',
    'PlasmaFAIR/sdf-xarray', 'aio-libs/yarl', 'apache/cassandra', 'apache/hive', 'jdbi/jdbi', 'apache/maven',
    'apache/maven-release', 'mongodb/mongo-java-driver']}
ARTIFACT_PREFIXES = ('.openhands/',)


class Stop(Exception): pass
class Capacity(Stop): pass
class Integrity(Exception): pass
class Unavailable(Exception): pass


def sha(data): return hashlib.sha256(data).hexdigest()
def git_blob(data): return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def read(path): return json.loads(Path(path).read_bytes())


def save(path, value):
    audit.save(Path(path), value)


# ---------------------------------------------------------------- selection (pure)

def candidate_pairs(catalog, trace_ids):
    """Unordered same-repo, same-base pairs where both tasks have a released trace."""
    traced = set(trace_ids)
    groups = {}
    for iid, repo, base in catalog:
        if iid in traced:
            groups.setdefault((repo.casefold(), base), set()).add(iid)
    out = []
    for (repo, base), ids in sorted(groups.items()):
        for a, b in itertools.combinations(sorted(ids), 2):
            out.append({'repo_key': repo, 'base_commit': base, 'instances': [a, b]})
    return out


def pair_hash(instances, seed=SEED):
    return hashlib.sha256(f'{seed}\n'.encode() + '\n'.join(sorted(instances)).encode()).hexdigest()


def select_fresh(pairs, n=5, excluded=EXCLUDED_REPOS, seed=SEED):
    """One pair per repository (smallest pair hash), then the n repositories with the smallest hashes."""
    best = {}
    for p in pairs:
        if p['repo_key'] in excluded:
            continue
        h = pair_hash(p['instances'], seed)
        if p['repo_key'] not in best or h < best[p['repo_key']][0]:
            best[p['repo_key']] = (h, p)
    ranked = sorted(best.values(), key=lambda x: x[0])
    return [{**p, 'pair_sha256': h} for h, p in ranked[:n]], len(best)


def offsets(catalog, trace_ids):
    task = {row[0]: i for i, row in enumerate(catalog)}
    trace = {}
    for i, iid in enumerate(trace_ids):
        trace.setdefault(iid, i)
    return task, trace


def cmd_select(_args):
    catalog, trace_ids = read(INPUT / 'catalog-metadata.json'), read(INPUT / 'trace-instance-ids.json')
    pairs = candidate_pairs(catalog, trace_ids)
    chosen, eligible_repos = select_fresh(pairs)
    index = {r[0]: r for r in catalog}
    task_off, trace_off = offsets(catalog, trace_ids)
    cases = []
    def case(role, instances, extra):
        rows = [index[i] for i in instances]
        return {'case_id': instances[0] + '+' + instances[1].split('__', 1)[1], 'role': role, 'instances': instances,
                'repo': rows[0][1], 'base_commit': rows[0][2], 'task_row_offsets': [task_off[i] for i in instances],
                'first_trace_row_offsets': [trace_off[i] for i in instances], **extra}
    cases.append(case('development_control', CONTROL, {'pair_sha256': pair_hash(CONTROL)}))
    for c in chosen:
        cases.append(case('fresh', c['instances'], {'pair_sha256': c['pair_sha256']}))
    record = {'frozen_utc': now(), 'seed': SEED, 'rule': 'protocol docs/pilot/swe-rebench-protocol.md, Case selection',
              'candidate_pairs': len(pairs), 'candidate_repositories': len({p['repo_key'] for p in pairs}),
              'eligible_repositories_after_exclusion': eligible_repos, 'excluded_repositories': sorted(EXCLUDED_REPOS),
              'task_revision': TASK_REV, 'trace_revision': TRACE_REV, 'cases': cases}
    out = PUBLIC / 'selection.json'
    if out.exists():
        old = read(out)
        if old['cases'] != cases:
            raise SystemExit('selection already frozen and differs; refusing to overwrite')
        print('selection unchanged')
        return
    save(out, record)
    print(json.dumps([[c['role'], c['repo'], c['instances']] for c in cases], indent=1))


# ---------------------------------------------------------------- budget and fetcher

class Budget:
    def __init__(self, path, total=TOTAL_BUDGET):
        self.path, self.total = Path(path), total
        self.state = read(path) if Path(path).exists() else {'received_bytes': 0, 'cached_bytes': 0, 'scopes': {}, 'requests': 0}
    def used(self, scope=None):
        return self.state['received_bytes'] if scope is None else self.state['scopes'].get(scope, 0)
    def room(self, scope, scope_cap, item_cap):
        return min(self.total - self.used(), scope_cap - self.used(scope), item_cap)
    def charge(self, scope, n):
        self.state['received_bytes'] += n
        self.state['scopes'][scope] = self.state['scopes'].get(scope, 0) + n
    def flush(self): save(self.path, self.state)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


class Fetcher:
    """Capped, hash-ledgered GETs. Bodies live in RAW/bodies. Cached reads are counted separately."""
    def __init__(self, raw=RAW, budget=None, deadline=None, timeout=45):
        self.raw, self.deadline, self.timeout = Path(raw), deadline, timeout
        (self.raw / 'bodies').mkdir(parents=True, exist_ok=True)
        self.budget = budget or Budget(self.raw / 'budget.json')
        self.opener = urllib.request.build_opener(NoRedirect)

    def _log(self, rec):
        with (self.raw / 'ledger.jsonl').open('a') as f:
            f.write(json.dumps(rec, sort_keys=True) + '\n')

    def _open(self, url, headers):
        for _ in range(5):
            req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-swe-rebench-pilot/1.0', **headers})
            try:
                return self.opener.open(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308) and exc.headers.get('Location'):
                    url = urllib.parse.urljoin(url, exc.headers['Location'])
                    if not url.startswith('https://'):
                        raise Integrity('redirect to non-https URL')
                    headers = {k: v for k, v in headers.items() if k.lower() != 'authorization'}
                    continue
                return exc
        raise Integrity('too many redirects')

    def get(self, name, url, cap, scope, scope_cap=TOTAL_BUDGET, headers=None, ok=(200,), retry=False):
        """Return (status, response headers, body). Raises Capacity when a cap is hit; partial bytes are kept and charged."""
        path = self.raw / 'bodies' / name
        if path.exists() and (path.with_suffix(path.suffix + '.meta')).exists():
            body = path.read_bytes()
            self.budget.state['cached_bytes'] += len(body); self.budget.flush()
            meta = read(path.with_suffix(path.suffix + '.meta'))
            return meta['status'], meta['headers'], body
        ledger = self.raw / 'ledger.jsonl'
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                old = json.loads(line)
                if old['name'] == name and old.get('capacity_stop') and old.get('cap', 0) >= cap and old['url'] == url:
                    raise Capacity('previously stopped at cap, not refetched: ' + old['capacity_stop'])
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            if self.deadline and time.monotonic() > self.deadline:
                raise Stop('collection deadline reached')
            rec = {'name': name, 'url': url, 'scope': scope, 'started': now(), 'attempt': attempt + 1, 'cap': cap}
            data, start = bytearray(), time.monotonic()
            self.budget.state['requests'] += 1
            try:
                resp = self._open(url, headers or {})
                status = resp.status if hasattr(resp, 'status') else resp.code
                rec['status'], rec['headers'] = status, {k: v for k, v in resp.headers.items() if k.lower() in (
                    'content-length', 'content-type', 'docker-content-digest', 'etag', 'last-modified', 'x-ratelimit-remaining', 'content-range')}
                declared = resp.headers.get('Content-Length')
                limit = self.budget.room(scope, scope_cap, cap)
                if limit <= 0 or (declared and int(declared) > limit):
                    rec['capacity_stop'] = 'declared %s over limit %d' % (declared, limit)
                    resp.close()
                    raise Capacity(rec['capacity_stop'])
                with resp:
                    while True:
                        if time.monotonic() - start > 120 or (self.deadline and time.monotonic() > self.deadline):
                            raise Stop('wall deadline during transfer')
                        room = self.budget.room(scope, scope_cap, cap) - len(data) + 1
                        chunk = resp.read(min(1 * MIB, max(room, 1)))
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > self.budget.room(scope, scope_cap, cap):
                            rec['capacity_stop'] = 'body exceeded limit'
                            raise Capacity(rec['capacity_stop'])
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                rec['error'] = repr(exc)
                status = None
            finally:
                self.budget.charge(scope, len(data))
                rec.update(bytes=len(data), sha256=sha(bytes(data)), seconds=round(time.monotonic() - start, 2))
                self._log(rec)
                self.budget.flush()
                if rec.get('capacity_stop') or rec.get('error') or (rec.get('status') not in ok):
                    (self.raw / 'bodies' / (name + '.error')).write_bytes(bytes(data))
            if status in ok:
                path.write_bytes(bytes(data))
                save(path.with_suffix(path.suffix + '.meta'), {'status': status, 'headers': rec['headers'], 'sha256': rec['sha256'], 'url': url})
                return status, rec['headers'], bytes(data)
            if attempt + 1 < attempts and (status is None or status >= 500):
                time.sleep(3)
                continue
            raise Unavailable(f'{name}: HTTP {status} {rec.get("error", "")}'.strip())


# ---------------------------------------------------------------- join checks (pure)

def message_text(m):
    c = m.get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
    return ''


def validate_join(expected, partner_id, task_row, trace_row, partner_task_row):
    """Join one task record to its trace. `expected` is the pinned catalog row (id, repo, base)."""
    t, tr, cells = task_row['row'], trace_row['row'], (task_row.get('truncated_cells'), trace_row.get('truncated_cells'))
    problems = []
    if any(cells):
        problems.append('truncated_cells')
    if [t.get('instance_id'), t.get('repo'), t.get('base_commit')] != list(expected):
        problems.append('task_row_differs_from_pinned_catalog')
    if tr.get('instance_id') != expected[0]:
        problems.append('trace_instance_mismatch')
    if tr.get('repo') != expected[1]:
        problems.append('trace_repo_mismatch')
    msgs = tr.get('trajectory')
    if not isinstance(msgs, list):
        problems.append('trajectory_not_a_list')
        msgs = []
    users = [message_text(m) for m in msgs if m.get('role') == 'user']
    statement = (t.get('problem_statement') or '').strip()
    if len(users) != 1:
        problems.append('user_message_count_%d' % len(users))
    if not statement or not users or statement not in users[0]:
        problems.append('task_text_not_in_first_prompt')
    patch = tr.get('model_patch') or ''
    if not patch.strip():
        problems.append('empty_output_patch')
    full = json.dumps(msgs, ensure_ascii=False)
    partner_statement = ((partner_task_row['row'].get('problem_statement') or '').strip())
    leaks = []
    if partner_id and partner_id in full:
        leaks.append('partner_instance_id')
    if partner_statement and partner_statement in full:
        leaks.append('partner_problem_statement')
    if leaks:
        problems.append('partner_leak:' + ','.join(leaks))
    if partner_statement == statement:
        problems.append('identical_task_statements')
    return {'ok': not problems, 'problems': problems, 'user_messages': len(users), 'patch_bytes': len(patch.encode()),
            'patch_sha256': sha(patch.encode()), 'exit_status': tr.get('exit_status'), 'trajectory_id': tr.get('trajectory_id'),
            'task_text_sha256': sha(statement.encode())}


# ---------------------------------------------------------------- replay classification (pure)

CONFLICT_PATH = re.compile(r'^\d{6} [0-9a-f]{40} [123]\t(.+)$', re.M)


def conflict_paths(stdout):
    return sorted(set(CONFLICT_PATH.findall(stdout)))


def classify_replay(result):
    """Turn an audit.replay result into declared-base diagnostic fields. Unknown or error never gives clean."""
    status = result.get('status')
    out = {'replay_status': status, 'diagnostic_label': None, 'conflict_paths': [], 'artifact_only_conflict': False}
    if status != 'complete' or not result.get('repeat_identical'):
        return out
    code = result['merge']['exit']
    if code == 0:
        out['diagnostic_label'] = 'clean'
    elif code == 1:
        out['diagnostic_label'] = 'conflict'
        paths = conflict_paths(result['merge']['stdout'])
        out['conflict_paths'] = paths
        out['artifact_only_conflict'] = bool(paths) and all(p.startswith(ARTIFACT_PREFIXES) for p in paths)
        out['conflict_paths_unparsed'] = not paths
    else:
        out['replay_status'] = 'unknown_exit_' + str(code)
    return out


def primary_label(rec):
    """Strict primary label. All conditions must hold; otherwise None. Never relaxed."""
    d, s = rec.get('declared_base', {}), rec.get('snapshot', {})
    ok = (rec.get('join', {}).get('ok') and d.get('tree_verified') and d.get('repeat_identical')
          and d.get('diagnostic_label') in ('clean', 'conflict') and not d.get('artifact_only_conflict')
          and s.get('published_snapshot_verified') is True and s.get('original_snapshot_verified') is True
          and not rec.get('contradictions'))
    return d['diagnostic_label'] if ok else None


def normalize_patch(patch):
    """Restore the one trailing LF that the released text lost (stored patches are stripped). No other change."""
    return patch if patch.endswith(b'\n') else patch + b'\n'


def check_git():
    out = subprocess.run(['git', '--version'], stdout=subprocess.PIPE, text=True, timeout=20).stdout.strip()
    if out != GIT_VERSION:
        raise SystemExit(f'Git protocol requires {GIT_VERSION}; found {out}')
    return out


# ---------------------------------------------------------------- archives

def precheck_archive(path, decoded_cap=DECODED_CAP, member_cap=MEMBER_CAP):
    """Reject over-cap archives from tar headers before audit.replay reads any member content."""
    total, count = 0, 0
    with tarfile.open(path, 'r:gz') as tf:
        for m in tf:
            count += 1
            if m.isfile():
                if m.size > member_cap:
                    raise Capacity('archive member over %d bytes: %s' % (member_cap, m.name))
                total += m.size
                if total > decoded_cap:
                    raise Capacity('decoded archive over %d bytes' % decoded_cap)
    return {'members': count, 'decoded_bytes': total}


def repair_additions(fetcher, repo, commit, expected_tree, archive_entries_list, scope, max_missing=32):
    """Add files that the codeload archive omitted (export-ignore) using the immutable tree API and raw blobs."""
    url = f'https://api.github.com/repos/{repo}/git/trees/{expected_tree}?recursive=1'
    _, _, body = fetcher.get(f'tree-{expected_tree}.json', url, META_CAP, scope)
    data = json.loads(body)
    if data.get('truncated'):
        raise Integrity('recursive tree truncated')
    wanted = {x['path']: x for x in data['tree'] if x['type'] != 'tree'}
    if any(x['type'] != 'blob' for x in wanted.values()):
        raise Integrity('tree has gitlink or unsupported entry')
    have = {n: (m, git_blob(d)) for n, m, d in archive_entries_list}
    extra = sorted(have.keys() - wanted.keys())
    if extra:
        raise Integrity('archive has %d entries absent from declared tree; first: %s' % (len(extra), extra[:5]))
    changed = sorted(n for n, v in have.items() if (wanted[n]['mode'], wanted[n]['sha']) != v)
    missing = sorted(wanted.keys() - have.keys()) + changed  # omitted (export-ignore) or rewritten (export-subst) files
    if len(missing) > max_missing:
        raise Capacity(f'{len(missing)} omitted or rewritten files exceeds {max_missing}')
    adds = []
    for n in missing:
        item = wanted[n]
        if n == '.git' or n.startswith('.git/') or any(x in ('', '.', '..') for x in n.split('/')):
            raise Integrity('unsafe omitted path')
        if item['mode'] not in ('100644', '100755', '120000') or item.get('size', MEMBER_CAP + 1) > MEMBER_CAP:
            raise Integrity('unsupported omitted entry')
        raw_url = f'https://raw.githubusercontent.com/{repo}/{commit}/' + urllib.parse.quote(n, safe='/')
        _, _, blob = fetcher.get('blob-' + item['sha'], raw_url, MEMBER_CAP, scope)
        if git_blob(blob) != item['sha']:
            raise Integrity('omitted blob hash mismatch')
        adds.append((n, item['mode'], blob))
    return adds, {'omitted_files': len(missing) - len(changed), 'rewritten_files': len(changed), 'tree_api_sha256': sha(body)}


def declared_base(fetcher, case, patches):
    """Archive the declared commit and replay both patches against it. Returns diagnostic fields only."""
    repo, commit = case['repo'], case['base_commit']
    scope = 'repo:' + repo
    out = {'repo': repo, 'base_commit': commit, 'tree_verified': False}
    _, _, body = fetcher.get(f'commit-{commit}.json', f'https://api.github.com/repos/{repo}/git/commits/{commit}', META_CAP, scope)
    cd = json.loads(body)
    if cd.get('sha') != commit:
        raise Integrity('commit API returned a different revision')
    expected = cd['tree']['sha']
    out.update(commit_api_sha256=sha(body), expected_tree=expected)
    arch_url = f'https://codeload.github.com/{repo}/tar.gz/{commit}'
    name = 'archive-' + repo.replace('/', '__') + '-' + commit + '.tar.gz'
    _, _, _ = fetcher.get(name, arch_url, LAYER_CAP, scope)
    archive = fetcher.raw / 'bodies' / name
    out.update(archive_sha256=sha(archive.read_bytes()), archive_bytes=archive.stat().st_size, archive_url=arch_url)
    out.update(precheck_archive(archive))
    audit.CACHE = fetcher.raw / 'tmp'
    audit.CACHE.mkdir(exist_ok=True)
    result = audit.replay(archive, expected, patches)
    if result['status'] == 'unverified_tree':
        out['initial_archive_tree'] = result['snapshot_tree']
        entries = audit.archive_entries(archive)
        try:
            adds, info = repair_additions(fetcher, repo, commit, expected, entries, scope)
        except (Integrity, Capacity, Unavailable) as exc:
            out['repair_error'] = str(exc)[:300]
            out.update(classify_replay(result))
            out['replay_status'] = 'unverified_tree'
            return out
        out['repair'] = info
        result = audit.replay(archive, expected, patches, adds)
    out['tree_verified'] = result['status'] not in ('unverified_tree',)
    out['snapshot_tree'] = result.get('snapshot_tree')
    out['repeat_identical'] = bool(result.get('repeat_identical'))
    if result.get('merge'):
        out['merge_exit'] = result['merge']['exit']
        out['merge_stdout_sha256'] = sha(result['merge']['stdout'].encode())
        out['merge_stderr_sha256'] = sha(result['merge']['stderr'].encode())
    if result.get('error'):
        out['replay_error'] = result['error'][:300]
    out.update(classify_replay(result))
    return out


def diff_paths(patch_text):
    return set(re.findall(r'^diff --git a/(\S+) b/', patch_text, re.M))


def conflict_detail(declared, raw_patches, task_rows):
    """Describe each Git-reported conflicting path. Reference patches are used only to classify paths, never as outputs."""
    out = []
    added = [set(re.findall(r'^diff --git a/(\S+) b/\S+\nnew file mode', p.decode('utf-8', 'replace'), re.M)) for p in raw_patches]
    ref = set().union(*[diff_paths(t['row'].get('patch') or '') for t in task_rows])
    tests = set().union(*[diff_paths(t['row'].get('test_patch') or '') for t in task_rows])
    for path in declared.get('conflict_paths') or []:
        out.append({'path': path, 'new_file_in_both_outputs': path in added[0] and path in added[1],
                    'harness_artifact': path.startswith(ARTIFACT_PREFIXES), 'in_reference_patches': path in ref, 'in_test_patches': path in tests})
    return out


# ---------------------------------------------------------------- image evidence (static)

MANIFEST_ACCEPT = ', '.join([
    'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'])


def image_evidence(fetcher, image, tag='latest'):
    """Resolve a tag to an immutable digest and retain manifest, config and history. No layer is pulled here."""
    scope = 'image:' + image
    ns_repo = image
    out = {'image': image, 'tag': tag}
    _, _, tok = fetcher.get('token-' + image.replace('/', '__') + '.json',
                            'https://auth.docker.io/token?service=registry.docker.io&scope=repository:%s:pull' % ns_repo, META_CAP, scope)
    auth = {'Authorization': 'Bearer ' + json.loads(tok)['token']}
    base = f'https://registry-1.docker.io/v2/{ns_repo}'
    status, hdr, body = fetcher.get('manifest-' + image.replace('/', '__') + '-' + tag, f'{base}/manifests/{tag}', META_CAP, scope,
                                    headers={**auth, 'Accept': MANIFEST_ACCEPT})
    top_digest = 'sha256:' + sha(body)
    if hdr.get('Docker-Content-Digest') not in (None, top_digest) and hdr.get('docker-content-digest') not in (None, top_digest):
        raise Integrity('manifest digest header differs from body hash')
    manifest = json.loads(body)
    out['tag_resolved_digest'] = top_digest
    if 'manifests' in manifest:
        pick = [m for m in manifest['manifests'] if m.get('platform', {}).get('os') == 'linux' and m['platform'].get('architecture') == 'amd64']
        if len(pick) != 1:
            raise Unavailable('no unique linux/amd64 manifest')
        digest = pick[0]['digest']
        _, _, body = fetcher.get('manifest-' + digest.replace(':', '-'), f'{base}/manifests/{digest}', META_CAP, scope,
                                 headers={**auth, 'Accept': MANIFEST_ACCEPT})
        if 'sha256:' + sha(body) != digest:
            raise Integrity('platform manifest hash mismatch')
        manifest = json.loads(body)
        out['platform_manifest_digest'] = digest
    else:
        out['platform_manifest_digest'] = top_digest
    cfg_digest = manifest['config']['digest']
    _, _, cfg_body = fetcher.get('config-' + cfg_digest.replace(':', '-'), f'{base}/blobs/{cfg_digest}', META_CAP, scope, headers=auth)
    if 'sha256:' + sha(cfg_body) != cfg_digest:
        raise Integrity('config hash mismatch')
    cfg = json.loads(cfg_body)
    layers = manifest['layers']
    out.update(config_digest=cfg_digest, config_created=cfg.get('created'), layer_count=len(layers),
               layers=[{'digest': x['digest'], 'size': x['size']} for x in layers],
               compressed_bytes=sum(x['size'] for x in layers), history_entries=len(cfg.get('history', [])),
               empty_layer_history=sum(1 for h in cfg.get('history', []) if h.get('empty_layer')),
               diff_ids=len(cfg.get('rootfs', {}).get('diff_ids', [])),
               fits_image_budget=sum(x['size'] for x in layers) <= IMAGE_BUDGET,
               largest_layer=max([x['size'] for x in layers] or [0]), env_workdir=cfg.get('config', {}).get('WorkingDir'))
    return out, cfg, manifest, auth, base


def hub_push_date(fetcher, image, tag='latest'):
    ns, repo = image.split('/', 1)
    url = f'https://hub.docker.com/v2/repositories/{ns}/{repo}/tags/{tag}'
    try:
        _, _, body = fetcher.get('hubtag-' + image.replace('/', '__') + '-' + tag, url, META_CAP, 'image:' + image)
    except Unavailable as exc:
        return {'hub_tag_error': str(exc)[:200]}
    d = json.loads(body)
    return {'hub_tag_last_pushed': d.get('tag_last_pushed'), 'hub_tag_digest': d.get('digest'), 'hub_tag_sha256': sha(body)}


def snapshot_evidence(fetcher, case, task_rows):
    """Static image evidence for both tasks. Layers are not downloaded: every pilot image is far over the 128 MiB image budget."""
    result = {'published_snapshot_verified': None, 'original_snapshot_verified': False, 'images': [], 'reasons': []}
    digests = []
    for row in task_rows:
        image = row['row'].get('image_name') or row['row'].get('docker_image')
        if not image:
            result['images'].append({'image': None, 'error': 'no image declared in task record'})
            result['reasons'].append('no_image_declared:' + row['row']['instance_id'])
            continue
        try:
            ev, cfg, manifest, auth, base = image_evidence(fetcher, image)
            ev.update(hub_push_date(fetcher, image))
        except (Unavailable, Integrity, Capacity, KeyError, ValueError) as exc:
            result['images'].append({'image': image, 'error': str(exc)[:300]})
            result['reasons'].append('image_unavailable:' + image)
            continue
        digests.append(ev['platform_manifest_digest'])
        ev['layers_over_64MiB_cap'] = [i for i, x in enumerate(ev['layers']) if x['size'] > LAYER_CAP]
        ev['history_mentions_repo_clone'] = any('Cloning' in (h.get('created_by') or '') for h in cfg.get('history', []))
        if not ev['fits_image_budget']:
            ev['layer_inspection'] = 'not_attempted_image_over_128MiB_budget'
            result['reasons'].append('image_over_budget:' + image)
        result['images'].append(ev)
    result['distinct_image_digests'] = len(set(digests))
    if result['reasons']:
        result['published_snapshot_verified'] = None
        result['status'] = 'unavailable'
    return result


# ---------------------------------------------------------------- case collection

def viewer_rows(fetcher, dataset, split, offset, name, scope):
    url = ('https://datasets-server.huggingface.co/rows?dataset=%s&config=default&split=%s&offset=%d&length=1'
           % (urllib.parse.quote(dataset, safe=''), split, offset))
    _, _, body = fetcher.get(name, url, META_CAP, scope, retry=True)
    rows = json.loads(body)['rows']
    if len(rows) != 1 or rows[0]['row_idx'] != offset:
        raise Integrity('viewer returned wrong row for offset %d' % offset)
    return rows[0], sha(body)


def run_case(fetcher, case, catalog_index):
    cid = case['case_id']
    rec = {'case_id': cid, 'role': case['role'], 'repo': case['repo'], 'base_commit': case['base_commit'],
           'instances': case['instances'], 'started': now(), 'contradictions': [], 'exclusion': None}
    scope = 'case:' + cid
    try:
        task_rows, trace_rows, hashes = [], [], []
        for i, iid in enumerate(case['instances']):
            r, h = viewer_rows(fetcher, TASK_SET, 'test', case['task_row_offsets'][i], f'{cid}-task{i}.json', scope)
            task_rows.append(r); hashes.append(h)
            r, h = viewer_rows(fetcher, TRACE_SET, 'train', case['first_trace_row_offsets'][i], f'{cid}-trace{i}.json', scope)
            trace_rows.append(r); hashes.append(h)
        rec['viewer_response_sha256'] = hashes
        checks = [validate_join(catalog_index[case['instances'][i]], case['instances'][1 - i], task_rows[i], trace_rows[i], task_rows[1 - i])
                  for i in range(2)]
        rec['per_task'] = checks
        rec['join'] = {'ok': all(c['ok'] for c in checks) and task_rows[0]['row']['base_commit'] == task_rows[1]['row']['base_commit'],
                       'problems': [c['problems'] for c in checks],
                       'pin_limit': 'viewer payload (statement, patch, trajectory) not checked against pinned Parquet; ID, repo, base checked against pinned catalog'}
        raw_patches = [t['row']['model_patch'].encode() for t in trace_rows]
        patches = [normalize_patch(p) for p in raw_patches]
        rec['patch_sha256'] = [sha(p) for p in raw_patches]
        rec['patch_sha256_replayed'] = [sha(p) for p in patches]
        rec['patch_trailing_lf_appended'] = [a != b for a, b in zip(raw_patches, patches)]
        rec['patch_has_artifact_paths'] = [bool(re.search(rb'^diff --git a/\.openhands/', p, re.M)) for p in patches]
        if not rec['join']['ok']:
            rec['exclusion'] = 'join_failed'
            rec['contradictions'].append('join:' + json.dumps(rec['join']['problems']))
        else:
            try:
                rec['declared_base'] = declared_base(fetcher, case, patches)
                rec['declared_base']['conflict_detail'] = conflict_detail(rec['declared_base'], raw_patches, task_rows)
            except Capacity as exc:
                rec['exclusion'] = 'capacity:' + str(exc)[:200]
            except Unavailable as exc:
                rec['exclusion'] = 'access:' + str(exc)[:200]
            except (Integrity, KeyError, ValueError, RuntimeError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
                rec['exclusion'] = 'error:' + type(exc).__name__ + ':' + str(exc)[:300]
            rec['snapshot'] = snapshot_evidence(fetcher, case, task_rows)
            rec['snapshot']['same_base_both_tasks'] = task_rows[0]['row']['base_commit'] == task_rows[1]['row']['base_commit']
            rec['task_metadata'] = [{'environment_setup_commit': t['row'].get('environment_setup_commit'), 'image': t['row'].get('image_name'),
                                     'test_patch_sha256': sha((t['row'].get('test_patch') or '').encode())} for t in task_rows]
    except Capacity as exc:
        rec['exclusion'] = 'capacity:' + str(exc)[:200]
    except Unavailable as exc:
        rec['exclusion'] = 'access:' + str(exc)[:200]
    except (Integrity, KeyError, ValueError, RuntimeError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        rec['exclusion'] = 'error:' + type(exc).__name__ + ':' + str(exc)[:300]
        if isinstance(exc, Integrity):
            rec['contradictions'].append(str(exc)[:200])
    rec['primary_label'] = primary_label(rec)
    rec['ended'] = now()
    return rec


def job_log(event, **kv):
    RAW.mkdir(parents=True, exist_ok=True)
    with (RAW / 'jobs.jsonl').open('a') as f:
        f.write(json.dumps({'ts': now(), 'event': event, 'owner': 'sonnet5.5 sub-agent', 'pid': os.getpid(), **kv}) + '\n')


def cmd_collect(args):
    check_git()
    sel = read(PUBLIC / 'selection.json')
    catalog_index = {r[0]: r for r in read(INPUT / 'catalog-metadata.json')}
    deadline = time.monotonic() + args.deadline_seconds
    job_log('start', purpose=args.purpose, deadline_seconds=args.deadline_seconds,
            deadline_utc=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=args.deadline_seconds)).isoformat(timespec='seconds'))
    fetcher = Fetcher(deadline=deadline)
    (RAW / 'checkpoints').mkdir(parents=True, exist_ok=True)
    code = 0
    try:
        for case in sel['cases']:
            if args.only and case['case_id'] not in args.only:
                continue
            cp = RAW / 'checkpoints' / (case['case_id'] + '.json')
            if cp.exists():
                job_log('checkpoint_skip', case=case['case_id'])
                continue
            job_log('case_start', case=case['case_id'])
            rec = run_case(fetcher, case, catalog_index)
            save(cp, rec)
            job_log('checkpoint', case=case['case_id'], exclusion=rec['exclusion'], received_bytes=fetcher.budget.used())
    except Stop as exc:
        job_log('stopped', reason=str(exc)); code = 3
    except BaseException as exc:
        job_log('crashed', error=repr(exc)[:300]); code = 1
        raise
    finally:
        job_log('end', exit=code, received_bytes=fetcher.budget.used(), cached_bytes=fetcher.budget.state['cached_bytes'])
    return code


# ---------------------------------------------------------------- public summary

PUBLIC_KEYS = ('case_id', 'role', 'repo', 'base_commit', 'instances', 'exclusion', 'primary_label')


def public_case(rec):
    out = {k: rec.get(k) for k in PUBLIC_KEYS}
    out['join'] = {'ok': rec.get('join', {}).get('ok'), 'problems': rec.get('join', {}).get('problems')}
    out['patch_sha256'] = rec.get('patch_sha256')
    out['patch_sha256_replayed'] = rec.get('patch_sha256_replayed')
    out['patch_trailing_lf_appended'] = rec.get('patch_trailing_lf_appended')
    out['patch_has_artifact_paths'] = rec.get('patch_has_artifact_paths')
    d = rec.get('declared_base')
    if d:
        out['declared_base'] = {k: d.get(k) for k in (
            'expected_tree', 'snapshot_tree', 'tree_verified', 'archive_sha256', 'archive_bytes', 'replay_status', 'repeat_identical',
            'merge_exit', 'diagnostic_label', 'conflict_paths', 'conflict_detail', 'artifact_only_conflict', 'repair_error', 'initial_archive_tree', 'omitted_files')}
        out['declared_base']['omitted_files'] = (d.get('repair') or {}).get('omitted_files')
        out['declared_base']['rewritten_files'] = (d.get('repair') or {}).get('rewritten_files')
    s = rec.get('snapshot')
    if s:
        out['snapshot'] = {'published_snapshot_verified': s.get('published_snapshot_verified'),
                           'original_snapshot_verified': s.get('original_snapshot_verified'), 'status': s.get('status'),
                           'reasons': s.get('reasons'), 'distinct_image_digests': s.get('distinct_image_digests'),
                           'images': [{k: i.get(k) for k in ('image', 'platform_manifest_digest', 'tag_resolved_digest', 'config_created',
                                                              'layer_count', 'compressed_bytes', 'largest_layer', 'layers_over_64MiB_cap', 'history_mentions_repo_clone', 'hub_tag_last_pushed', 'layer_inspection', 'error')}
                                      for i in s.get('images', [])]}
    out['contradictions'] = rec.get('contradictions')
    return out


def summarize(records, budget_state=None):
    fresh = [r for r in records if r['role'] == 'fresh']
    def diag(r): return (r.get('declared_base') or {}).get('diagnostic_label')
    primary = [r for r in fresh if r.get('primary_label')]
    summary = {
        'cases_total': len(records), 'fresh_cases': len(fresh), 'development_control_cases': len(records) - len(fresh),
        'strict_primary_all': sum(1 for r in records if r.get('primary_label')),
        'strict_primary_fresh': len(primary), 'strict_primary_fresh_repos': len({r['repo'].casefold() for r in primary}),
        'published_snapshot_verified': sum(1 for r in records if (r.get('snapshot') or {}).get('published_snapshot_verified') is True),
        'original_snapshot_verified': sum(1 for r in records if (r.get('snapshot') or {}).get('original_snapshot_verified') is True),
        'snapshot_unavailable': sum(1 for r in records if (r.get('snapshot') or {}).get('status') == 'unavailable'),
        'declared_base_diagnostic_labels': {k: sum(1 for r in records if diag(r) == k) for k in ('clean', 'conflict')},
        'declared_base_diagnostic_fresh': {k: sum(1 for r in fresh if diag(r) == k) for k in ('clean', 'conflict')},
        'artifact_only_conflicts': sum(1 for r in records if (r.get('declared_base') or {}).get('artifact_only_conflict')),
        'access_or_capacity_exclusions_fresh': sum(1 for r in fresh if (r.get('exclusion') or '').startswith(('access', 'capacity'))),
        'other_exclusions': sum(1 for r in records if r.get('exclusion') and not r['exclusion'].startswith(('access', 'capacity'))),
        'contradictions': sum(len(r.get('contradictions') or []) for r in records),
        'repositories': sorted({r['repo'] for r in records}),
    }
    summary['expansion_gate'] = gate(summary)
    if budget_state:
        summary['budget'] = {'received_bytes': budget_state['received_bytes'], 'cached_bytes': budget_state['cached_bytes'],
                             'requests': budget_state['requests'], 'limit_bytes': TOTAL_BUDGET}
    return summary


def gate(s):
    checks = {'at_least_3_primary_fresh': s['strict_primary_fresh'] >= 3, 'at_least_3_repos': s['strict_primary_fresh_repos'] >= 3,
              'at_most_1_access_or_capacity_exclusion': s['access_or_capacity_exclusions_fresh'] <= 1,
              'no_contradictions': s['contradictions'] == 0}
    return {'passes': all(checks.values()), 'checks': checks}


def export_ready(records, outdir):
    """Write private features/targets only for strictly qualified pairs. Diagnostics go elsewhere."""
    feats, targets = [], []
    for r in records:
        if r.get('primary_label'):
            feats.append({'instance_id': r['case_id'], 'repo': r['repo'], 'base_commit': r['base_commit']})
            targets.append({'instance_id': r['case_id'], 'status': 'verified', 'label': r['primary_label']})
    assert [f['instance_id'] for f in feats] == [t['instance_id'] for t in targets]
    save(Path(outdir) / 'features.json', feats)
    save(Path(outdir) / 'targets.json', targets)
    return feats, targets


HARNESS_PATTERNS = {'workspace_cd': r"cd /workspace/\{workspace_dir_name\}", 'reset': r"'git reset --hard'", 'stage_all': r"'git add -A'",
                    'diff_against_declared_base': r'git diff --no-color --cached \{instance\["base_commit"\]\}',
                    'binary_diff_removed': r'remove_binary_diffs\(git_patch\)'}


def cmd_harness(_args):
    """Retain the OpenHands 0.54.0 SWE-bench runner (version taken from the pinned dataset card) and record where it resets and diffs."""
    f = Fetcher(deadline=time.monotonic() + 300)
    _, _, card = f.get('trajectory-readme.md', f'https://huggingface.co/datasets/{TRACE_SET}/resolve/{TRACE_REV}/README.md', MIB, 'harness')
    repo = 'All-Hands-AI/OpenHands'
    _, _, ref = f.get('openhands-tag-All-Hands-AI__OpenHands.json', f'https://api.github.com/repos/{repo}/git/ref/tags/0.54.0', META_CAP, 'harness')
    commit = json.loads(ref)['object']['sha']
    path = 'evaluation/benchmarks/swe_bench/run_infer.py'
    _, _, src = f.get('openhands-run_infer-0.54.0.py', f'https://raw.githubusercontent.com/{repo}/{commit}/{path}', META_CAP, 'harness')
    lines = src.decode().splitlines()
    facts = {k: [i for i, l in enumerate(lines, 1) if re.search(pat, l)] for k, pat in HARNESS_PATTERNS.items()}
    save(PUBLIC / 'harness.json', {
        'dataset_card_url': f'https://huggingface.co/datasets/{TRACE_SET}/blob/{TRACE_REV}/README.md', 'dataset_card_sha256': sha(card),
        'dataset_card_scaffold': 'OpenHands (v0.54.0) with Qwen3-Coder-480B-A35B-Instruct' if b'v0.54.0' in card else 'not found',
        'source_url': f'https://github.com/{repo}/blob/{commit}/{path}', 'tag': '0.54.0', 'commit': commit, 'source_sha256': sha(src),
        'source_lines_matching': facts,
        'reads': 'The stock runner resets the tracked tree with git reset --hard, stages all files with git add -A, and writes git diff --cached against instance base_commit, so scratch files and .openhands files enter the patch.',
        'limits': ['The dataset card names a version, not an image digest or runner commit, so no published image is bound to the original run.',
                   'That the nebius SWE-rebench runs used this stock runner file unmodified is not established.',
                   'git reset --hard does not remove untracked files, and the runtime workspace copy step was not traced.']})
    print(json.dumps(facts))


def cmd_summarize(_args):
    sel = read(PUBLIC / 'selection.json')
    records = []
    for case in sel['cases']:
        cp = RAW / 'checkpoints' / (case['case_id'] + '.json')
        records.append(read(cp) if cp.exists() else {'case_id': case['case_id'], 'role': case['role'], 'repo': case['repo'],
                                                       'base_commit': case['base_commit'], 'instances': case['instances'],
                                                       'exclusion': 'not_collected', 'primary_label': None, 'contradictions': []})
    budget = read(RAW / 'budget.json') if (RAW / 'budget.json').exists() else None
    summary = summarize(records, budget)
    save(PUBLIC / 'cases.json', [public_case(r) for r in records])
    save(PUBLIC / 'summary.json', summary)
    export_ready(records, RAW / 'ready')
    print(json.dumps(summary, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('select').set_defaults(fn=cmd_select)
    c = sub.add_parser('collect')
    c.add_argument('--deadline-seconds', type=int, default=1500)
    c.add_argument('--purpose', default='six-case SWE-rebench pilot collection and replay')
    c.add_argument('--only', nargs='*')
    c.set_defaults(fn=cmd_collect)
    sub.add_parser('summarize').set_defaults(fn=cmd_summarize)
    sub.add_parser('harness').set_defaults(fn=cmd_harness)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == '__main__':
    sys.exit(main())
