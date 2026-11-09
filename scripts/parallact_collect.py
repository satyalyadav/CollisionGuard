#!/usr/bin/env python3
"""Continue the frozen ParallACT pilot. All upstream content stays private."""
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import parallact_pilot as pilot
import audit_benchmark_sources as audit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = pilot.PRIVATE
PUBLIC = pilot.PUBLIC
SELECTION_HASH = '55310d468476b7cfd43c34960c1ec07d4b5681189836dc592118bd6a9b370bce'
PRODUCER_HASH = '1f016c8cb66e0ce8ed8b0833c2c082f601e6b4636f94ffb611a222ed85963ed1'
PROTOCOL_HASH = 'c9373b7b7af581b8f0d0b2d76f7cf76e3162654ac912b277f019a3432b3473b4'
CFG = 'api--claude_code--opus-4.8'
SOURCE = 'https://raw.githubusercontent.com/rm206/ParallACT_data_and_code/' + pilot.PIN + '/'
SITE = 'https://lingyunxiao18.github.io/ParallACT/'
META_CAP = 8 * 1024 * 1024
ARCHIVE_CAP = 64 * 1024 * 1024


def sha(data): return hashlib.sha256(data).hexdigest()
def git_blob(data): return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
def read_json(path): return json.loads(path.read_bytes())
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()


class StopCollection(Exception): pass
class IntegrityError(StopCollection): pass
class AccessError(Exception): pass


class Fetcher:
    """Persistent conservative accounting, including interrupted read reservations."""
    def __init__(self, private):
        self.private = private
        self.ledger_path = private / 'ledger.json'
        self.state = read_json(self.ledger_path)
        self.state.setdefault('phase2_cache_reuse_bytes', 0)
        self.state.setdefault('phase2_objects', {})
        self.state.setdefault('phase2_failures', {})

    def save(self): pilot.save(self.ledger_path, self.state)

    def fetch(self, url, repo, cap=META_CAP):
        key = sha(url.encode())
        path = self.private / 'phase2' / 'responses' / key
        item = self.state['phase2_objects'].get(key)
        if path.exists():
            if not item or item['url'] != url or sha(path.read_bytes()) != item['sha256']:
                raise IntegrityError('response cache identity mismatch')
            self.state['phase2_cache_reuse_bytes'] += path.stat().st_size
            self.save()
            return path.read_bytes()
        if item:
            raise IntegrityError('recorded response missing')
        source = urllib.parse.urlsplit(url).netloc
        if self.state['phase2_failures'].get(source, 0) >= 3:
            raise AccessError('source_stopped')
        entry = {'url': url, 'repo': repo, 'charged_bytes': 0, 'status': 'started'}
        self.state['requests'].append(entry)
        self.save()
        partial = path.with_suffix('.partial')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-local-pilot'})
            with urllib.request.urlopen(req, timeout=45) as response, partial.open('wb') as out:
                size = 0
                while True:
                    room = min(cap - size, pilot.TOTAL - self.state['charged_bytes'], pilot.REPO - self.state['repos'].get(repo, 0))
                    if room <= 0:
                        if self.state['charged_bytes'] >= pilot.TOTAL: raise StopCollection('global_body_limit')
                        raise AccessError('body_or_repository_limit')
                    n = min(room, 65536)
                    entry['charged_bytes'] += n
                    self.state['charged_bytes'] += n
                    self.state['repos'][repo] = self.state['repos'].get(repo, 0) + n
                    self.save()
                    chunk = response.read(n)
                    unused = n - len(chunk)
                    entry['charged_bytes'] -= unused
                    self.state['charged_bytes'] -= unused
                    self.state['repos'][repo] -= unused
                    self.save()
                    if not chunk: break
                    size += len(chunk)
                    out.write(chunk)
                out.flush(); os.fsync(out.fileno())
            os.replace(partial, path)
            body = path.read_bytes()
            record = {'url': url, 'sha256': sha(body), 'bytes': len(body)}
            self.state['phase2_objects'][key] = record
            entry.update(status='saved', sha256=record['sha256'])
            self.state['phase2_failures'][source] = 0
            self.save()
            return body
        except urllib.error.HTTPError as e:
            entry.update(status='http_error', http_status=e.code)
            if e.code == 429 or (e.code == 403 and e.headers.get('X-RateLimit-Remaining') == '0'):
                self.save(); raise StopCollection('rate_limit') from e
            self.state['phase2_failures'][source] = self.state['phase2_failures'].get(source, 0) + 1
            self.save(); raise AccessError('http_' + str(e.code)) from e
        except (StopCollection, AccessError):
            entry['status'] = 'limit'; self.save(); raise
        except Exception as e:
            entry.update(status='access_error', reason=type(e).__name__)
            self.state['phase2_failures'][source] = self.state['phase2_failures'].get(source, 0) + 1
            self.save(); raise AccessError(type(e).__name__) from e
        finally:
            partial.unlink(missing_ok=True)


def verify_frame(private=PRIVATE):
    raw = (private / 'selection.json').read_bytes()
    if sha(raw) != SELECTION_HASH: raise IntegrityError('selection hash mismatch')
    frame = json.loads(raw)
    if frame['script_sha256'] != PRODUCER_HASH or sha((private / 'scripts' / (PRODUCER_HASH + '.py')).read_bytes()) != PRODUCER_HASH:
        raise IntegrityError('original producer hash mismatch')
    if sha((ROOT / 'docs/pilot/parallact-protocol.md').read_bytes()) != PROTOCOL_HASH or frame['protocol_sha256'] != PROTOCOL_HASH:
        raise IntegrityError('protocol hash mismatch')
    if sha((private / 'manifest.json').read_bytes()) != frame['manifest_sha256']:
        raise IntegrityError('manifest mismatch')
    old = read_json(PUBLIC / 'retention.json')
    for c in old['cases']:
        original = read_json(ROOT / 'data/source-audit/benchmarks' / (Path(c['path']).stem + '.json'))
        if any(c['expected_' + k + '_sha256'] != original[k + '_sha256'] for k in ('seed', 'run')): raise IntegrityError('old evidence identity mismatch')
        for kind, suffix in [('seed', '.seed.json'), ('run', '.run.json.gz')]:
            raw = (private / 'responses' / (Path(c['path']).stem + suffix)).read_bytes()
            if sha(raw) != c['expected_' + kind + '_sha256']: raise IntegrityError('old retention drift')
    if len(old['cases']) != 6 or len(frame['new_paths']) != 12: raise IntegrityError('denominator mismatch')
    for name, expected in [('util.js', 'c4da88600ed955dcfa5d1e2afea882cb77338a217316e925819799dace265d12'), ('config.js', '47ce595287bdf2b4b050da4bbb9dfefa43dc51c78002c929ab50e988d8fc222c')]:
        if sha((private / 'site' / name).read_bytes()) != expected: raise IntegrityError('site code drift')
    return frame


def bounded_gunzip(body):
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream: raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024: raise IntegrityError('decompression limit')
    return json.loads(raw)


def association(seed, run, path, prefix):
    info = pilot.parse_path(path)
    iid = Path(path).stem
    checks = {'run_identity': all([run.get('cfg') == CFG, run.get('v') == info['version'], run.get('fam') == info['family'], run.get('iid') == iid, run.get('scen') == 'parallel_unaware', seed.get('instance_id') == iid, seed.get('repo', '').lower() == info['repo'].lower()]), 'no_messages': run.get('messages') == [], 'two_turns': len(run.get('turns', [])) == 2, 'timing_source_reported': bool(run.get('started_at')) and isinstance(run.get('wall'), (int, float)) and run['wall'] > 0}
    prompts, outputs = [], []
    for a in ('A', 'B'):
        statement = seed.get('agent' + a + '_problem_statement')
        matches = [t for t in run.get('turns', []) if t.get('agent') == a]
        prompt = matches[0].get('prompt', '') if len(matches) == 1 else ''
        output = run.get('outputs', {}).get(a, '')
        valid_statement = isinstance(statement, str) and bool(statement.strip())
        prompts.append(statement if valid_statement else '')
        outputs.append(output if isinstance(output, str) else '')
        checks[a + '_assignment'] = valid_statement and prompt.count(statement.strip()) == 1 and prompt.startswith(prefix) and prompt[len(prefix):].strip() == statement.strip()
        checks[a + '_output'] = bool(outputs[-1].strip()) and outputs[-1] != seed.get('agent' + a + '_solution')
    checks['distinct_prompts'] = bool(prompts[0]) and prompts[0].strip() != prompts[1].strip()
    checks['separate_outputs'] = bool(outputs[0]) and bool(outputs[1]) and outputs[0] != outputs[1]
    checks['base_sha'] = bool(re.fullmatch('[0-9a-f]{40}', seed.get('base_commit', '')))
    return checks, prompts, outputs


def safe_feature(seed, prompts):
    return {'instance_id': seed['instance_id'], 'repo': seed['repo'], 'base_commit': seed['base_commit'], 'task_a': prompts[0], 'task_b': prompts[1]}


def replay_with_gitlinks(archive, expected, patches, additions, links):
    """Construct the exact index including submodule object IDs; never access submodules."""
    import tempfile
    entries = audit.archive_entries(archive) + list(additions)
    with tempfile.TemporaryDirectory(prefix='collisionguard-replay-', dir=audit.CACHE) as directory:
        repo = Path(directory)
        empty = repo / 'empty-template'; empty.mkdir()
        audit.git(repo, 'init', '-q', '--template=' + str(empty))
        audit.git(repo, 'read-tree', '--empty')
        index = bytearray()
        for path, mode, data in entries:
            blob = audit.git(repo, 'hash-object', '-w', '--stdin', input=data).stdout.strip()
            index.extend(mode.encode() + b' ' + blob + b'\t' + os.fsencode(path) + b'\0')
        for path, commit in links:
            if not re.fullmatch('[0-9a-f]{40}', commit): raise IntegrityError('invalid gitlink')
            index.extend(b'160000 ' + commit.encode() + b'\t' + os.fsencode(path) + b'\0')
        audit.git(repo, 'update-index', '-z', '--index-info', input=bytes(index))
        tree = audit.git(repo, 'write-tree').stdout.decode().strip()
        if tree != expected: return {'status':'unverified_tree', 'snapshot_tree':tree, 'expected_tree':expected}
        base = audit.git(repo, 'commit-tree', tree, input=b'audit base\n').stdout.decode().strip()
        heads = []
        for patch in patches:
            audit.git(repo, 'read-tree', tree)
            if audit.git(repo, 'apply', '--cached', '--check', '-', input=patch, ok=(0,1,128)).returncode:
                return {'status':'patch_not_applicable', 'snapshot_tree':tree, 'expected_tree':expected, 'patch_index':len(heads)}
            audit.git(repo, 'apply', '--cached', '-', input=patch)
            changed = audit.git(repo, 'write-tree').stdout.decode().strip()
            heads.append(audit.git(repo, 'commit-tree', changed, '-p', base, input=b'audit agent\n').stdout.decode().strip())
        def merge():
            p = audit.git(repo, 'merge-tree', '--write-tree', *heads, ok=(0,1))
            return p.returncode, p.stdout, p.stderr
        first, second = merge(), merge()
        return {'status':'complete' if first == second else 'unrepeatable_label', 'snapshot_tree':tree, 'expected_tree':expected,
                'archive_entries':len(entries), 'gitlink_count':len(links), 'base_head':base, 'agent_heads':heads,
                'repeat_identical':first == second, 'label':'clean' if first[0] == 0 else 'conflict'}


def replay_case(fetcher, seed, outputs):
    repo, base = seed['repo'], seed['base_commit']
    url = f'https://api.github.com/repos/{repo}/git/commits/{base}'
    commit = json.loads(fetcher.fetch(url, repo))
    if commit.get('sha') != base or not re.fullmatch('[0-9a-f]{40}', commit.get('tree', {}).get('sha', '')):
        raise IntegrityError('commit identity mismatch')
    expected = commit['tree']['sha']
    archive_url = f'https://codeload.github.com/{repo}/tar.gz/{base}'
    archive_data = fetcher.fetch(archive_url, repo, ARCHIVE_CAP)
    archive = PRIVATE / 'phase2' / 'archives' / (sha(archive_url.encode()) + '.tar.gz')
    if not archive.exists(): pilot.atomic(archive, archive_data)
    elif sha(archive.read_bytes()) != sha(archive_data): raise IntegrityError('archive drift')
    audit.CACHE = PRIVATE / 'phase2' / 'work'
    audit.CACHE.mkdir(parents=True, exist_ok=True)
    result = audit.replay(archive, expected, [x.encode() for x in outputs])
    if result['status'] == 'unverified_tree':
        tree_url = f'https://api.github.com/repos/{repo}/git/trees/{expected}?recursive=1'
        tree_data = json.loads(fetcher.fetch(tree_url, repo))
        if tree_data.get('truncated') or tree_data.get('sha') != expected: return {'status': 'unverified_tree', 'reason': 'recursive_tree_unavailable_or_truncated', 'expected_tree': expected}
        original = {name: (mode, git_blob(data)) for name, mode, data in audit.archive_entries(archive)}
        entries = {x['path']: x for x in tree_data['tree'] if x['type'] != 'tree'}
        if any(x['type'] not in ('blob', 'commit') or (x['type'] == 'commit' and x['mode'] != '160000') for x in entries.values()) or original.keys() - entries.keys() or any((entries[n]['mode'], entries[n]['sha']) != val for n, val in original.items()):
            return {'status': 'unverified_tree', 'reason': 'archive_entries_mismatch_or_gitlink', 'expected_tree': expected}
        additions, links = [], []
        for name in sorted(entries.keys() - original.keys()):
            item = entries[name]
            if name == '.git' or name.startswith('.git/') or any(p in ('', '.', '..') for p in name.split('/')): raise IntegrityError('unsafe supplemental entry')
            if item['type'] == 'commit':
                links.append((name, item['sha']))
                continue
            if name == '.git' or name.startswith('.git/') or any(p in ('', '.', '..') for p in name.split('/')) or item['mode'] not in ('100644','100755','120000'):
                raise IntegrityError('unsafe supplemental entry')
            blob_url = f'https://raw.githubusercontent.com/{repo}/{base}/' + urllib.parse.quote(name, safe='/')
            blob = fetcher.fetch(blob_url, repo, ARCHIVE_CAP)
            if git_blob(blob) != item['sha'] or len(blob) != item.get('size'): raise IntegrityError('supplemental blob mismatch')
            additions.append((name, item['mode'], blob))
        result = replay_with_gitlinks(archive, expected, [x.encode() for x in outputs], additions, links) if links else audit.replay(archive, expected, [x.encode() for x in outputs], additions)
        result['supplemented_count'] = len(additions)
    allowed = ('status','snapshot_tree','expected_tree','archive_entries','base_head','agent_heads','repeat_identical','label','patch_index','supplemented_count','gitlink_count')
    safe = {key: result[key] for key in allowed if key in result}
    safe.update(archive_sha256=sha(archive_data), archive_bytes=len(archive_data), archive_url=archive_url, commit_url=url, patch_sha256=[sha(x.encode()) for x in outputs])
    return safe


def save_outputs(checkpoint, features, targets):
    pilot.save(PRIVATE / 'phase2' / 'checkpoint.json', checkpoint)
    pilot.save(PRIVATE / 'phase2' / 'features.json', features)
    pilot.save(PRIVATE / 'phase2' / 'targets.json', targets)
    pilot.save(PUBLIC / 'cases.json', {'cases': checkpoint['cases'], 'denominator': 12})


def main():
    frame = verify_frame()
    continuation = {'parent_selection_sha256': SELECTION_HASH, 'parent_protocol_sha256': PROTOCOL_HASH, 'parent_producer_sha256': PRODUCER_HASH, 'collector_sha256': sha(Path(__file__).read_bytes()), 'helper_sha256': sha((ROOT / 'scripts/audit_benchmark_sources.py').read_bytes()), 'started_at': now()}
    continuation_path = PRIVATE / 'phase2' / 'continuation.json'
    if continuation_path.exists():
        previous = read_json(continuation_path)
        if any(previous[k] != continuation[k] for k in continuation if k not in ('started_at', 'collector_sha256')): raise IntegrityError('continuation identity mismatch')
        if previous['collector_sha256'] != continuation['collector_sha256']:
            parent = previous['collector_sha256']
            if sha((PRIVATE / 'scripts' / (parent + '.py')).read_bytes()) != parent: raise IntegrityError('parent collector mismatch')
            revision = {**continuation, 'parent_collector_sha256': parent, 'reason': 'preserve gitlinks and correct source-stopped status'}
            revision_path = PRIVATE / 'phase2' / ('revision-' + continuation['collector_sha256'] + '.json')
            if revision_path.exists() and any(read_json(revision_path)[k] != revision[k] for k in revision if k != 'started_at'): raise IntegrityError('revision mismatch')
            if not revision_path.exists():
                pilot.save(revision_path, revision)
                pilot.save(PUBLIC / 'continuation-revision.json', revision)
                with (PRIVATE / 'decisions.tsv').open('a') as f: f.write(f"{now()}\tcontinuation\tRevise replay and stopped-source classification\tPreserve prior job evidence\t{continuation['collector_sha256']}\tparent {parent}\n")
        continuation = previous
    else:
        pilot.save(continuation_path, continuation)
        pilot.save(PUBLIC / 'continuation.json', continuation)
        with (PRIVATE / 'decisions.tsv').open('a') as f: f.write(f"{now()}\tcontinuation\tFreeze collector revision\tExtend implementation before new outcomes\t{continuation['collector_sha256']}\tparent {SELECTION_HASH}\n")
    manifest = read_json(PRIVATE / 'manifest.json')
    blobs = {x['path']: x['sha'] for x in manifest['tree']}
    old = read_json(PUBLIC / 'retention.json')['cases'][0]
    oldseed = read_json(PRIVATE / 'responses' / (Path(old['path']).stem + '.seed.json'))
    oldrun = bounded_gunzip((PRIVATE / 'responses' / (Path(old['path']).stem + '.run.json.gz')).read_bytes())
    statement = oldseed['agentA_problem_statement']; oldprompt = next(t['prompt'] for t in oldrun['turns'] if t['agent'] == 'A')
    if oldprompt.count(statement) != 1: raise IntegrityError('historical prompt template mismatch')
    prefix = oldprompt[:oldprompt.index(statement)]
    cp_path = PRIVATE / 'phase2' / 'checkpoint.json'
    checkpoint = read_json(cp_path) if cp_path.exists() else {'cases': [{'path': p, 'association': 'unfinished', 'replay': {'status': 'unfinished'}} for p in frame['new_paths']]}
    features = read_json(PRIVATE / 'phase2/features.json') if (PRIVATE / 'phase2/features.json').exists() else []
    targets = read_json(PRIVATE / 'phase2/targets.json') if (PRIVATE / 'phase2/targets.json').exists() else []
    fetcher = Fetcher(PRIVATE)
    for case in checkpoint['cases']:
        if case.get('reason') == 'source_stopped' and case['association'] == 'unavailable': case['association'] = 'unfinished'
        if case['replay'].get('reason') == 'archive_entries_mismatch_or_gitlink':
            case['prior_replay'] = case['replay']
            case['replay'] = {'status': 'unfinished'}
    stop = None
    for case in checkpoint['cases']:
        if case['association'] != 'unfinished': continue
        path = case['path']; info = pilot.parse_path(path); iid = Path(path).stem
        seed_url = SOURCE + path
        run_url = f"{SITE}data/runs/{CFG}/{info['version']}/{info['family']}/{iid}/parallel_unaware.json.gz"
        try:
            seed_raw = fetcher.fetch(seed_url, 'parallact')
            if git_blob(seed_raw) != blobs[path]: raise IntegrityError('seed git blob mismatch')
            run_raw = fetcher.fetch(run_url, 'parallact')
            seed, run = json.loads(seed_raw), bounded_gunzip(run_raw)
            checks, prompts, outputs = association(seed, run, path, prefix)
            case.update(seed_url=seed_url, seed_sha256=sha(seed_raw), run_url=run_url, run_sha256=sha(run_raw), repo=seed.get('repo'), base=seed.get('base_commit'), checks=checks, association='valid' if all(checks[k] for k in checks if k != 'timing_source_reported') else 'invalid', execution_revision='unknown', timing='source_reported' if checks['timing_source_reported'] else 'unknown')
            if case['association'] == 'valid':
                features.append(safe_feature(seed, prompts))
                case['task_sha256'] = [sha(x.encode()) for x in prompts]
                case['pair_sha256'] = sha(('\0'.join(prompts)).encode())
                targets.append({'instance_id': iid, 'status': 'unfinished'})
        except AccessError as e:
            case.update(association='unfinished' if str(e) == 'source_stopped' else 'unavailable', reason=str(e), seed_url=seed_url, run_url=run_url)
        except StopCollection as e:
            case['reason'] = str(e); stop = str(e)
        except (KeyError, ValueError, TypeError, gzip.BadGzipFile, json.JSONDecodeError) as e:
            case.update(association='invalid', reason=type(e).__name__)
        save_outputs(checkpoint, features, targets)
        print('association', iid, case['association'], case.get('reason',''), flush=True)
        if stop: break
    if not stop:
        for case in checkpoint['cases']:
            if case['association'] != 'valid' or case['replay']['status'] != 'unfinished': continue
            path = case['path']; iid = Path(path).stem
            try:
                seed = json.loads(fetcher.fetch(case['seed_url'], 'parallact'))
                run = bounded_gunzip(fetcher.fetch(case['run_url'], 'parallact'))
                result = replay_case(fetcher, seed, [run['outputs'][a] for a in ('A','B')])
                case['replay'] = result
                target = next(t for t in targets if t['instance_id'] == iid)
                target.update(status=result['status'], label=result.get('label'))
            except AccessError as e:
                case['replay'] = {'status':'unavailable', 'reason':str(e)}
                next(t for t in targets if t['instance_id'] == iid).update(status='unavailable')
            except StopCollection as e: case['replay'] = {'status':'unfinished', 'reason':str(e)}; stop = str(e)
            except (ValueError, RuntimeError, subprocess.TimeoutExpired, OSError) as e: case['replay'] = {'status':'unverified', 'reason':type(e).__name__}
            save_outputs(checkpoint, features, targets)
            print('replay', iid, case['replay']['status'], case['replay'].get('label',''), flush=True)
            if stop: break
    checkpoint['ended_at'] = now(); checkpoint['stop_reason'] = stop
    save_outputs(checkpoint, features, targets)
    with (PRIVATE / 'decisions.tsv').open('a') as f: f.write(f"{now()}\tcollection\tAttempt frozen cases\tAssociation and replay under cumulative budget\tphase2/checkpoint.json\tstop={stop}\n")
    return 2 if stop or any(c['association']=='unfinished' or (c['association']=='valid' and c['replay']['status']=='unfinished') for c in checkpoint['cases']) else 0


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('FATAL', type(exc).__name__, str(exc), file=sys.stderr, flush=True)
        sys.exit(2)
