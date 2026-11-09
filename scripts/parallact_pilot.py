#!/usr/bin/env python3
"""Bounded ParallACT pilot preflight and durable historical retention."""
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path('/home/satyal/.cache/collisionguard-parallact-pilot')
PUBLIC = ROOT / 'data/parallact-pilot'
MANIFEST = Path('/tmp/collisionguard-parallact-manifest.json')
PIN = 'c212deb174fbc8980212cc1bde5b3f047941f332'
TOTAL = 256 * 1024 * 1024
REPO = 64 * 1024 * 1024
BODY = 8 * 1024 * 1024
PATTERN = re.compile(r'^instance_(.+)-([0-9a-f]{40})(?:-v[^/]+)?\.json$')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('wb') as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save(path, obj):
    atomic(path, (json.dumps(obj, indent=2, sort_keys=True) + '\n').encode())


def parse_path(path):
    parts = path.split('/')
    if len(parts) != 5 or parts[0] != 'dataset' or parts[1] not in ('v1', 'v2') or parts[2] not in ('seeds', 'generated') or parts[3] not in ('complementary', 'contradictory'):
        return None
    m = PATTERN.fullmatch(parts[4])
    if not m or '__' not in m[1]:
        return None
    return {'version': parts[1], 'origin': parts[2], 'family': parts[3], 'repo': m[1].replace('__', '/', 1), 'instance_commit': m[2]}


def select(paths, old):
    groups = collections.defaultdict(list)
    for p in sorted(paths):
        info = parse_path(p)
        if info and p not in old:
            groups[(info['version'], info['origin'], info['family'])].append(p)
    rng = random.Random(39)
    counts = collections.Counter()
    chosen, shortages = [], {}
    for key in sorted(groups):
        candidates = groups[key][:]
        rng.shuffle(candidates)
        pick = []
        for p in candidates:
            repo = parse_path(p)['repo']
            if counts[repo] < 2:
                counts[repo] += 1
                pick.append(p)
                if len(pick) == 2:
                    break
        chosen.extend(pick)
        if len(pick) < 2:
            shortages['/'.join(key)] = 2 - len(pick)
    return chosen, shortages


class Meter:
    """Reserve before each read so interruption cannot undercount bytes."""
    def __init__(self, path):
        self.path = path
        self.state = json.loads(path.read_text()) if path.exists() else {'charged_bytes': 0, 'repos': {}, 'requests': [], 'cache_reuse_bytes': 0}

    def write(self):
        save(self.path, self.state)

    def fetch(self, url, repo, dest, expected=None):
        if dest.exists():
            data = dest.read_bytes()
            if expected and digest(data) != expected:
                raise ValueError('cached bytes differ from expected hash')
            self.state['cache_reuse_bytes'] += len(data)
            self.write()
            return data
        entry = {'url': url, 'repo': repo, 'charged_bytes': 0, 'status': 'started'}
        self.state['requests'].append(entry)
        self.write()
        data = bytearray()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-local-pilot'})
            with urllib.request.urlopen(req, timeout=30) as response:
                while True:
                    room = min(BODY - len(data), TOTAL - self.state['charged_bytes'], REPO - self.state['repos'].get(repo, 0))
                    if room <= 0:
                        raise ValueError('body budget exhausted or body limit reached')
                    amount = min(65536, room)
                    entry['charged_bytes'] += amount
                    self.state['charged_bytes'] += amount
                    self.state['repos'][repo] = self.state['repos'].get(repo, 0) + amount
                    self.write()
                    chunk = response.read(amount)
                    unused = amount - len(chunk)
                    entry['charged_bytes'] -= unused
                    self.state['charged_bytes'] -= unused
                    self.state['repos'][repo] -= unused
                    self.write()
                    if not chunk:
                        break
                    data.extend(chunk)
            atomic(dest, bytes(data))
            entry.update(status='saved', sha256=digest(data))
            self.write()
            if expected and digest(data) != expected:
                raise ValueError('response differs from recorded hash')
            return bytes(data)
        except Exception as exc:
            entry.update(status='failed', reason=type(exc).__name__)
            self.write()
            raise


def main():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    old_selection = json.loads((ROOT / 'data/source-audit/benchmarks/selection.json').read_text())
    manifest = MANIFEST.read_bytes()
    if digest(manifest) != old_selection['manifest_sha256']:
        raise ValueError('manifest identity mismatch')
    data = json.loads(manifest)
    if data.get('sha') != PIN or data.get('truncated'):
        raise ValueError('manifest pin or completeness mismatch')
    paths = sorted(x['path'] for x in data['tree'] if parse_path(x['path']))
    if len(paths) != 155:
        raise ValueError('inventory count mismatch')
    selected, shortages = select(paths, set(old_selection['paths']))
    inventory = collections.Counter('/'.join((q['version'], q['origin'], q['family'], q['repo'])) for q in map(parse_path, paths))
    identity = {'source_revision': PIN, 'manifest_sha256': digest(manifest), 'protocol_sha256': digest((ROOT / 'docs/pilot/parallact-protocol.md').read_bytes()), 'script_sha256': digest(Path(__file__).read_bytes()), 'old_paths': old_selection['paths'], 'new_paths': selected, 'selection_algorithm': 'sorted strata and paths, Python Random(39) shuffle per stratum, first two subject to global repository cap two', 'shortages': shortages, 'inventory_counts': dict(sorted(inventory.items()))}
    frozen = PRIVATE / 'selection.json'
    if frozen.exists() and json.loads(frozen.read_text()) != identity:
        raise ValueError('resume identity mismatch')
    atomic(PRIVATE / 'manifest.json', manifest)
    save(frozen, identity)
    save(PUBLIC / 'selection.json', identity)
    with (PRIVATE / 'decisions.tsv').open('a') as f:
        f.write(f'{dt.datetime.now(dt.timezone.utc).isoformat()}\tselection\tFreeze selection and identities\tBefore reading selected cases\t{digest(frozen.read_bytes())}\t{len(selected)} paths; shortages {len(shortages)}\n')
    if len(selected) != 12 or shortages:
        raise ValueError('selection shortage; stop before collection')
    meter = Meter(PRIVATE / 'ledger.json')
    results = []
    failures = collections.Counter()
    for path in old_selection['paths']:
        evidence = json.loads((ROOT / 'data/source-audit/benchmarks' / (Path(path).stem + '.json')).read_text())
        record = {'path': path, 'repo': evidence['repo'], 'seed_url': evidence['seed_url'], 'run_url': evidence['run_url'], 'expected_seed_sha256': evidence['seed_sha256'], 'expected_run_sha256': evidence['run_sha256'], 'status': 'unfinished'}
        if failures['parallact'] >= 3:
            record['reason'] = 'source stopped after three consecutive access failures'
            results.append(record)
            continue
        try:
            for kind in ('seed', 'run'):
                expected = evidence[kind + '_sha256']
                dest = PRIVATE / 'responses' / (Path(path).stem + ('.seed.json' if kind == 'seed' else '.run.json.gz'))
                body = meter.fetch(evidence[kind + '_url'], 'parallact', dest, expected)
                record[kind + '_sha256'] = digest(body)
            failures['parallact'] = 0
            record['status'] = 'matched'
        except urllib.error.HTTPError as exc:
            record['reason'] = 'http_' + str(exc.code)
            if exc.code in (429, 403):
                record['status'] = 'paused_rate_or_access_limit'
                failures['parallact'] = 3
            else:
                failures['parallact'] += 1
                record['status'] = 'access_failure'
        except ValueError:
            record.update(status='integrity_failure', reason='hash_or_budget_mismatch')
            failures['parallact'] = 3
        except Exception as exc:
            record.update(status='access_failure', reason=type(exc).__name__)
            failures['parallact'] += 1
        results.append(record)
        save(PRIVATE / 'checkpoint.json', {'retention': results, 'new_cases': 'not_attempted'})
    save(PUBLIC / 'retention.json', {'cases': results, 'new_case_status': 'unfinished', 'note': 'Known-label retention checks; not new validation.'})
    print('retention', sum(x['status'] == 'matched' for x in results), '/', len(results), flush=True)
    print('STOP: retention stage only; use parallact_collect.py for collection and replay.', flush=True)
    return 2


if __name__ == '__main__':
    sys.exit(main())
