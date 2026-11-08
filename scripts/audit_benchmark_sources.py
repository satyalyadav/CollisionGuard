#!/usr/bin/env python3
"""Replay pinned benchmark patches against bounded, validated source archives.

Only archive bodies count toward the persistent snapshot budget. No repository
files are checked out or executed. Run under an external process-tree deadline.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import urllib.parse
import sys

os.environ['NO_PROXY'] = os.environ['no_proxy'] = ''
CACHE = Path('/tmp/collisionguard-benchmark-cache')
EVIDENCE = Path('data/source-audit/benchmarks')
PIN = 'c212deb174fbc8980212cc1bde5b3f047941f332'
LIMIT = 128 * 1024 * 1024
BUDGET = 256 * 1024 * 1024
ENV = {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')}, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
       'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1', 'GIT_ATTR_NOSYSTEM': '1', 'NO_PROXY': '', 'no_proxy': '',
       'GIT_AUTHOR_NAME': 'audit', 'GIT_AUTHOR_EMAIL': 'audit@example.invalid',
       'GIT_COMMITTER_NAME': 'audit', 'GIT_COMMITTER_EMAIL': 'audit@example.invalid',
       'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z'}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


def get(url, cap=8*1024*1024):
    req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-source-audit'})
    with urllib.request.urlopen(req, timeout=45) as response:
        body = response.read(cap + 1)
    if len(body) > cap:
        raise ValueError('response exceeds cap')
    return body


def gunzip(body):
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('decompressed run exceeds cap')
    return data


def snapshot(url, path):
    ledger = CACHE / 'snapshot-budget.json'
    state = json.loads(ledger.read_text()) if ledger.exists() else {'downloaded_body_bytes': 0, 'requests': []}
    entry = {'url': url, 'body_bytes': 0, 'completed': False}
    state['requests'].append(entry)
    save(ledger, state)
    req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-source-audit'})
    partial = path.with_suffix(path.suffix + '.partial')
    try:
        with urllib.request.urlopen(req, timeout=45) as response, partial.open('wb') as out:
            while True:
                allowed = min(LIMIT - entry['body_bytes'], BUDGET - state['downloaded_body_bytes'])
                if allowed <= 0:
                    raise ValueError('snapshot budget exhausted')
                chunk = response.read(min(1024*1024, allowed))
                if not chunk:
                    break
                entry['body_bytes'] += len(chunk)
                state['downloaded_body_bytes'] += len(chunk)
                save(ledger, state)
                out.write(chunk)
        os.replace(partial, path)
        entry['completed'] = True
    finally:
        save(ledger, state)
        if not entry['completed']:
            partial.unlink(missing_ok=True)


def archive_entries(path):
    """Validate paths and types before building an index, without extraction."""
    entries, seen, root = [], set(), None
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = member.name
            p = PurePosixPath(name)
            if p.is_absolute() or not p.parts or any(x in ('..', '.') for x in name.split('/')) or '\\' in name:
                raise ValueError('unsafe archive path: ' + name)
            if root is None:
                root = p.parts[0]
            if p.parts[0] != root:
                raise ValueError('multiple archive roots')
            if len(p.parts) == 1:
                if not member.isdir():
                    raise ValueError('root is not a directory')
                continue
            rel = '/'.join(p.parts[1:])
            if rel == '.git' or rel.startswith('.git/') or rel in seen:
                raise ValueError('duplicate or git path: ' + rel)
            seen.add(rel)
            if member.isdir():
                continue
            if member.issym():
                target = member.linkname
                if not target or '\x00' in target:
                    raise ValueError('invalid symlink')
                data = target.encode('utf-8', 'surrogateescape')
                mode = '120000'
            elif member.isfile():
                total += member.size
                if member.size > LIMIT or total > 1024*1024*1024:
                    raise ValueError('uncompressed archive limit')
                data = archive.extractfile(member).read(member.size + 1)
                if len(data) != member.size:
                    raise ValueError('truncated archive member')
                mode = '100755' if member.mode & 0o111 else '100644'
            else:
                raise ValueError('unsupported archive entry: ' + rel)
            entries.append((rel, mode, data))
    if not entries:
        raise ValueError('empty archive')
    return entries


def git(repo, *args, input=None, ok=(0,)):
    p = subprocess.run(['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null', *args], input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV, timeout=120)
    if p.returncode not in ok:
        raise RuntimeError(f'git {args[0]} exit {p.returncode}: {p.stderr.decode(errors="replace")[:1000]}')
    return p


def replay(archive, expected_tree, patches, additions=()):
    if len(patches) != 2:
        raise ValueError('a replay requires exactly two agent patches')
    entries = archive_entries(archive) + list(additions)
    with tempfile.TemporaryDirectory(prefix='collisionguard-replay-', dir=CACHE) as d:
        repo = Path(d)
        empty = repo / 'empty-template'; empty.mkdir()
        git(repo, 'init', '-q', '--template=' + str(empty))
        git(repo, 'read-tree', '--empty')
        index = bytearray()
        for path, mode, data in entries:
            blob = git(repo, 'hash-object', '-w', '--stdin', input=data).stdout.strip()
            index.extend(mode.encode() + b' ' + blob + b'\t' + os.fsencode(path) + b'\0')
        git(repo, 'update-index', '-z', '--index-info', input=bytes(index))
        tree = git(repo, 'write-tree').stdout.decode().strip()
        if tree != expected_tree:
            return {'status': 'unverified_tree', 'snapshot_tree': tree, 'expected_tree': expected_tree,
                    'archive_entries': len(entries)}
        base = git(repo, 'commit-tree', tree, input=b'audit base\n').stdout.decode().strip()
        heads = []
        for patch in patches:
            git(repo, 'read-tree', tree)
            check = git(repo, 'apply', '--cached', '--check', '-', input=patch, ok=(0, 1, 128))
            if check.returncode:
                return {'status': 'patch_not_applicable', 'snapshot_tree': tree, 'patch_index': len(heads),
                        'error': check.stderr.decode(errors='replace')[:1000]}
            git(repo, 'apply', '--cached', '-', input=patch)
            changed_tree = git(repo, 'write-tree').stdout.decode().strip()
            heads.append(git(repo, 'commit-tree', changed_tree, '-p', base, input=b'audit agent\n').stdout.decode().strip())
        def merge():
            p = git(repo, 'merge-tree', '--write-tree', *heads, ok=(0, 1))
            return {'exit': p.returncode, 'stdout': p.stdout.decode(errors='replace'),
                    'stderr': p.stderr.decode(errors='replace')}
        first, second = merge(), merge()
        return {'status': 'complete' if first == second else 'unrepeatable_label', 'snapshot_tree': tree, 'expected_tree': expected_tree,
                'archive_entries': len(entries), 'base_head': base, 'agent_heads': heads,
                'merge': first, 'repeat_identical': first == second,
                'label': 'clean' if first['exit'] == 0 else 'conflict'}


def audit_case(case, patches):
    repo, commit = case['repo'], case['base']
    api = f'https://api.github.com/repos/{repo}/git/commits/{commit}'
    commit_data = json.loads(get(api))
    if commit_data.get('sha') != commit:
        raise ValueError('commit API returned a different source revision')
    expected = commit_data['tree']['sha']
    url = f'https://codeload.github.com/{repo}/tar.gz/{commit}'
    snapshot_url = url
    archive = CACHE / (repo.replace('/', '__') + '-' + commit + '.tar.gz')
    if not archive.exists():
        snapshot(url, archive)
    result = replay(archive, expected, patches)
    if result['status'] == 'unverified_tree' and '--repair-unverified' in sys.argv:
        tree_url = f'https://api.github.com/repos/{repo}/git/trees/{expected}?recursive=1'
        tree_body = get(tree_url, 16 * 1024 * 1024)
        tree_data = json.loads(tree_body)
        if tree_data.get('truncated'):
            raise ValueError('recursive source tree is truncated')
        original = {name: (mode, hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest())
                    for name, mode, data in archive_entries(archive)}
        expected_entries = {x['path']: x for x in tree_data['tree'] if x['type'] != 'tree'}
        if any(x['type'] != 'blob' for x in expected_entries.values()):
            raise ValueError('source tree contains unsupported gitlink')
        if original.keys() - expected_entries.keys() or any(
            (expected_entries[n]['mode'], expected_entries[n]['sha']) != value for n, value in original.items()
        ):
            raise ValueError('archive contains extra or changed entries')
        additions, supplemented = [], []
        for name in sorted(expected_entries.keys() - original.keys()):
            item = expected_entries[name]
            if name == '.git' or name.startswith('.git/') or any(x in ('', '.', '..') for x in name.split('/')):
                raise ValueError('unsafe supplemental path')
            if item['mode'] not in ('100644', '100755', '120000') or item.get('size', LIMIT + 1) > LIMIT:
                raise ValueError('unsupported supplemental file')
            blob_path = CACHE / ('blob-' + item['sha'])
            url = f'https://raw.githubusercontent.com/{repo}/{commit}/' + urllib.parse.quote(name, safe='/')
            if not blob_path.exists():
                snapshot(url, blob_path)
            data = blob_path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != item['sha'] or len(data) != item['size']:
                raise ValueError('supplemental blob mismatch')
            additions.append((name, item['mode'], data))
            supplemented.append({'path': name, 'git_blob': actual, 'bytes': len(data), 'url': url})
        prior = result
        result = replay(archive, expected, patches, additions)
        result['initial_archive_tree'] = prior['snapshot_tree']
        result['supplemental_tree_api'] = tree_url
        result['supplemental_tree_api_sha256'] = hashlib.sha256(tree_body).hexdigest()
        result['supplemented'] = supplemented
    result.update({'repo': repo, 'base': commit, 'commit_api': api, 'snapshot_url': snapshot_url,
                   'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                   'archive_bytes': archive.stat().st_size,
                   'patch_sha256': [hashlib.sha256(x).hexdigest() for x in patches]})
    return result


def main():
    CACHE.mkdir(exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
    manifest_path = Path('/tmp/collisionguard-parallact-manifest.json')
    manifest_url = f'https://api.github.com/repos/rm206/ParallACT_data_and_code/git/trees/{PIN}?recursive=1'
    if not manifest_path.exists():
        manifest_path.write_bytes(get(manifest_url, 16 * 1024 * 1024))
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('truncated'):
        raise ValueError('seed manifest is truncated')
    node_path = Path('/tmp/collisionguard-parallact-run.json')
    if not node_path.exists():
        run_url = 'https://lingyunxiao18.github.io/ParallACT/data/runs/api--claude_code--opus-4.8/v1/contradictory/instance_NodeBB__NodeBB-4327a09d76f10a79109da9d91c22120428d3bdb9-vnan/parallel_unaware.json.gz'
        node_path.write_bytes(gunzip(get(run_url)))
    coop_root = 'https://huggingface.co/datasets/CooperBench/trajectories/resolve/906bc2f62325eb6f8ccb4cf221e63df051cb3c99/coop/dottxt_ai_outlines_task/task1371/feature1_feature2/'
    for i in (1, 2):
        patch_path = Path(f'/tmp/collisionguard-cooperbench-patch{i}.patch')
        if not patch_path.exists():
            patch_path.write_bytes(get(coop_root + f'patch_claude_k1_feature{i}.patch'))
    paths = [x['path'] for x in manifest['tree'] if x['path'].startswith('dataset/v1/seeds/') and x['path'].endswith('.json')]
    # Select from paths before fetching selected runs; the cached NodeBB label was already known.
    selected = [next(p for p in sorted(paths) if f'/seeds/{family}/instance_{repo}-' in p)
                for family in ('complementary', 'contradictory')
                for repo in ('NodeBB__NodeBB', 'ansible__ansible', 'element-hq__element-web')]
    selection = {'manifest_url': f'https://api.github.com/repos/rm206/ParallACT_data_and_code/git/trees/{PIN}?recursive=1',
                 'manifest_sha256': hashlib.sha256(Path('/tmp/collisionguard-parallact-manifest.json').read_bytes()).hexdigest(),
                 'rule': 'lexically first seed in each family for NodeBB, ansible, element-web', 'paths': selected,
                 'note': 'Selection used seed paths before fetching these runs, but the cached NodeBB contradictory label was already known from earlier audit notes.'}
    save(EVIDENCE / 'selection.json', selection)
    cases = [('cached-nodebb', {'repo': 'NodeBB/NodeBB', 'base': '754965b572f33bfd864e98e4805e1182c1960080'},
              [x.encode() for x in [json.loads(Path('/tmp/collisionguard-parallact-run.json').read_text())['outputs'][k] for k in ('A','B')]]),
             ('cached-cooperbench', {'repo': 'dottxt-ai/outlines', 'base': '7149a5e613b9c2bb3c2ed3ee5b7c9228772504b1'},
              [Path(f'/tmp/collisionguard-cooperbench-patch{i}.patch').read_bytes() for i in (1,2)])]
    for path in selected:
        name = Path(path).stem
        raw_url = f'https://raw.githubusercontent.com/rm206/ParallACT_data_and_code/{PIN}/{path}'
        family = path.split('/')[3]
        run_url = f'https://lingyunxiao18.github.io/ParallACT/data/runs/api--claude_code--opus-4.8/v1/{family}/{name}/parallel_unaware.json.gz'
        result_path = EVIDENCE / (name + '.json')
        if result_path.exists() and not ('--repair-unverified' in sys.argv and json.loads(result_path.read_text()).get('status') == 'unverified_tree'):
            continue
        try:
            seed_bytes = get(raw_url); seed = json.loads(seed_bytes)
            run_bytes = get(run_url); run = json.loads(gunzip(run_bytes))
            case = {'repo': seed['repo'], 'base': seed['base_commit'], 'seed_url': raw_url,
                    'seed_sha256': hashlib.sha256(seed_bytes).hexdigest(), 'run_url': run_url,
                    'run_sha256': hashlib.sha256(run_bytes).hexdigest(), 'scenario': run.get('scen'),
                    'prompt_matches': {a: next(t['prompt'] for t in run['turns'] if t['agent'] == a).count(seed[f'agent{a}_problem_statement']) for a in ('A','B')},
                    'messages_count': len(run.get('messages', [])),
                    'agent_reference_equal': {a: run['outputs'][a] == seed[f'agent{a}_solution'] for a in ('A','B')},
                    'exported_merge_status': run.get('eval',{}).get('policies',{}).get('git-merge',{}).get('status')}
            cases.append((name, case, [run['outputs'][a].encode() for a in ('A','B')]))
        except Exception as e:
            save(result_path, {'status': 'missing_or_inaccessible', 'seed_url': raw_url, 'run_url': run_url, 'error': str(e)})
    for name, case, patches in cases:
        out = EVIDENCE / (name + '.json')
        if out.exists() and not ('--repair-unverified' in sys.argv and json.loads(out.read_text()).get('status') == 'unverified_tree'):
            continue
        try:
            result = audit_case(case, patches)
            result.update(case)
        except Exception as e:
            result = {**case, 'status': 'error', 'error': str(e)}
        save(out, result)
        print(name, result['status'], result.get('label', ''), flush=True)


if __name__ == '__main__':
    main()
