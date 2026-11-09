#!/usr/bin/env python3
"""Controlled ParallACT v1 import. Responses and predictors remain private."""
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

import parallact_pilot as prior
import parallact_collect as collect
import audit_benchmark_sources as audit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path('/home/satyal/.cache/collisionguard-parallact-v1-pilot')
PUBLIC = ROOT / 'data/parallact-v1-pilot'
OLD = Path('/home/satyal/.cache/collisionguard-parallact-pilot')
PIN = prior.PIN
CFG = collect.CFG
SITE = collect.SITE
SOURCE = collect.SOURCE
TOTAL = 256 * 1024**2
REPO = 64 * 1024**2
META = 8 * 1024**2
ARCHIVE = 64 * 1024**2
DECOMPRESSED = 16 * 1024**2


def sha(raw): return hashlib.sha256(raw).hexdigest()
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def save(path, value): prior.save(path, value)
def read(path): return json.loads(path.read_bytes())


class Stop(Exception): pass
class Access(Exception): pass
class Integrity(Stop): pass


class Fetcher:
    def __init__(self, private):
        self.private = private
        self.path = private / 'ledger.json'
        self.state = read(self.path) if self.path.exists() else {'charged_bytes': 0, 'repos': {}, 'requests': [], 'objects': {}, 'failures': {}, 'verified_cache_bytes': 0}
        self.write()

    def write(self): save(self.path, self.state)

    def cached(self, path, expected):
        raw = path.read_bytes()
        if sha(raw) != expected: raise Integrity('verified cache hash mismatch')
        self.state['verified_cache_bytes'] += len(raw); self.write()
        return raw

    def fetch(self, url, repo, cap=META):
        key = sha(url.encode()); dest = self.private / 'responses' / key
        item = self.state['objects'].get(key)
        if item:
            if item.get('http_status'): raise Access('http_' + str(item['http_status']))
            if not dest.exists() or item['url'] != url or sha(dest.read_bytes()) != item['sha256']: raise Integrity('response cache mismatch')
            return self.cached(dest, item['sha256'])
        if dest.exists(): raise Integrity('unrecorded response')
        host = urllib.parse.urlsplit(url).netloc
        if self.state['failures'].get(host, 0) >= 3: raise Access('source_stopped')
        entry = {'url': url, 'repo': repo, 'status': 'started', 'charged_bytes': 0}
        self.state['requests'].append(entry); self.write()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CollisionGuard-v1-pilot'})
            try:
                response = urllib.request.urlopen(req, timeout=45)
                error = None
            except urllib.error.HTTPError as exc:
                response, error = exc, exc
            data = bytearray()
            with response:
                while True:
                    room = min(cap - len(data), TOTAL - self.state['charged_bytes'], REPO - self.state['repos'].get(repo, 0))
                    if room <= 0:
                        prior.atomic(self.private / 'partial' / (key + '-' + str(len(self.state['requests']))), bytes(data))
                        if self.state['charged_bytes'] >= TOTAL: raise Stop('global body budget limit')
                        raise Access('body or repository budget limit')
                    n = min(room, 65536)
                    entry['charged_bytes'] += n; self.state['charged_bytes'] += n
                    self.state['repos'][repo] = self.state['repos'].get(repo, 0) + n; self.write()
                    chunk = response.read(n)
                    unused = n - len(chunk)
                    entry['charged_bytes'] -= unused; self.state['charged_bytes'] -= unused; self.state['repos'][repo] -= unused; self.write()
                    if not chunk: break
                    data.extend(chunk)
            raw = bytes(data); prior.atomic(dest, raw)
            item = {'url': url, 'sha256': sha(raw), 'bytes': len(raw)}
            if error: item['http_status'] = error.code
            self.state['objects'][key] = item
            if error:
                entry.update(status='http_error', http_status=error.code, sha256=item['sha256'])
                if error.code == 429 or (error.code == 403 and error.headers.get('X-RateLimit-Remaining') == '0'):
                    self.write(); raise Stop('rate_limit')
                self.state['failures'][host] = self.state['failures'].get(host, 0) + 1; self.write()
                raise Access('http_' + str(error.code))
            entry.update(status='saved', sha256=item['sha256']); self.state['failures'][host] = 0; self.write()
            return raw
        except (Access, Stop):
            if entry['status'] == 'started': entry['status'] = 'limit'; self.write()
            raise
        except Exception as exc:
            entry.update(status='access_error', reason=type(exc).__name__)
            self.state['failures'][host] = self.state['failures'].get(host, 0) + 1; self.write()
            raise Access(type(exc).__name__) from exc


def available(instance):
    runs = instance.get('runs')
    return isinstance(runs, dict) and isinstance(runs.get(CFG), dict) and isinstance(runs[CFG].get('parallel_unaware'), dict)


def select(paths, excluded):
    groups = collections.defaultdict(list)
    for p in sorted(paths):
        q = prior.parse_path(p)
        if q and q['version'] == 'v1' and p not in excluded: groups[(q['origin'], q['family'])].append(p)
    rng = random.Random(39); counts = collections.Counter(); chosen = []; shortages = {}
    for key in [(a,b) for a in ('generated','seeds') for b in ('complementary','contradictory')]:
        pool = groups[key][:]; rng.shuffle(pool); found = 0
        for p in pool:
            repo = prior.parse_path(p)['repo']
            if counts[repo] < 2:
                chosen.append(p); counts[repo] += 1; found += 1
                if found == 3: break
        if found < 3: shortages['/'.join(key)] = 3-found
    return chosen, shortages


def identity():
    files = [Path(__file__), ROOT/'scripts/parallact_pilot.py', ROOT/'scripts/parallact_collect.py', ROOT/'scripts/audit_benchmark_sources.py', ROOT/'docs/pilot/parallact-v1-protocol.md']
    return {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in files}


def verify_identity(saved):
    if saved != identity(): raise Integrity('producer identity drift')


def snapshot_sources(ids):
    for name, digest in ids.items():
        p = PRIVATE/'producers'/digest
        raw = (ROOT/name).read_bytes()
        if p.exists() and sha(p.read_bytes()) != digest: raise Integrity('producer snapshot drift')
        if not p.exists(): prior.atomic(p, raw)


def prefix_from_history(fetcher):
    case = read(ROOT/'data/parallact-pilot/retention.json')['cases'][0]
    stem = Path(case['path']).stem
    seed = json.loads(fetcher.cached(OLD/'responses'/(stem+'.seed.json'), case['expected_seed_sha256']))
    run = collect.bounded_gunzip(fetcher.cached(OLD/'responses'/(stem+'.run.json.gz'), case['expected_run_sha256']))
    statement = seed['agentA_problem_statement']; prompt = next(t['prompt'] for t in run['turns'] if t['agent'] == 'A')
    if prompt.count(statement) != 1: raise Integrity('historical template mismatch')
    return prompt[:prompt.index(statement)]


def replay(fetcher, seed, outputs):
    # The imported helper's mutable paths are process-local and point only to this experiment.
    collect.PRIVATE = PRIVATE
    audit.CACHE = PRIVATE/'work'; audit.CACHE.mkdir(parents=True, exist_ok=True)
    # Limit decompression before the archive helper can inspect an archive.
    original = audit.archive_entries
    def checked(path):
        with gzip.open(path, 'rb') as stream:
            total = 0
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > DECOMPRESSED: raise ValueError('archive decompression limit')
        return original(path)
    audit.archive_entries = checked
    try: return collect.replay_case(fetcher, seed, outputs)
    finally: audit.archive_entries = original


def main():
    PRIVATE.mkdir(parents=True, exist_ok=True); PUBLIC.mkdir(parents=True, exist_ok=True)
    ids = identity(); snapshot_sources(ids)
    job_identity = PRIVATE/'identity.json'
    if job_identity.exists():
        previous = read(job_identity)
        if previous != ids:
            transition = read(PRIVATE/'transition-01.json')
            if transition['previous'] != previous or transition['current'] != ids: raise Integrity('unapproved producer transition')
    else: save(job_identity, ids)
    frame_ids = read(job_identity)
    f = Fetcher(PRIVATE)
    old_selection = read(ROOT/'data/source-audit/benchmarks/selection.json')
    manifest_raw = f.cached(OLD/'manifest.json', old_selection['manifest_sha256'])
    tree = json.loads(manifest_raw)
    if tree.get('sha') != PIN or tree.get('truncated'): raise Integrity('source tree pin')
    blobs = {x['path']:x['sha'] for x in tree['tree']}
    site_url = SITE+'data/manifest.json'
    site_raw = f.fetch(site_url, 'parallact-site'); site = json.loads(site_raw)
    if CFG not in [x['id'] for x in site['configs']] or 'parallel_unaware' not in [x['id'] for x in site['scenarios']]: raise Integrity('site configuration or scenario missing')
    old_pilot = read(ROOT/'data/parallact-pilot/selection.json')
    excluded = set(old_selection['paths']) | set(old_pilot['new_paths'])
    candidates = [p for p in sorted(blobs) if prior.parse_path(p) and prior.parse_path(p)['version'] == 'v1' and p not in excluded]
    availability = []; eligible = []
    for p in candidates:
        q = prior.parse_path(p); iid = Path(p).stem
        url = f"{SITE}data/instances/v1/{q['family']}/{iid}.json"
        raw = f.fetch(url, 'parallact-site'); obj = json.loads(raw)
        present = available(obj)
        availability.append({'path':p, 'url':url, 'sha256':sha(raw), 'bytes':len(raw), 'available':present})
        if present: eligible.append(p)
    chosen, shortages = select(eligible, excluded)
    frame = {'source_revision':PIN, 'site_manifest':{'url':site_url,'sha256':sha(site_raw),'bytes':len(site_raw)}, 'source_manifest_sha256':sha(manifest_raw), 'excluded_source_audit_sha256':sha((ROOT/'data/source-audit/benchmarks/selection.json').read_bytes()), 'excluded_old_pilot_sha256':sha((ROOT/'data/parallact-pilot/selection.json').read_bytes()), 'producer_hashes':frame_ids, 'selection_algorithm':'sorted strata and paths, Random(39), three per stratum, global repository cap two', 'availability':availability, 'paths':chosen, 'shortages':shortages}
    frozen = PRIVATE/'selection.json'
    if frozen.exists() and read(frozen) != frame: raise Integrity('frozen selection drift')
    if not frozen.exists():
        save(frozen, frame); save(PUBLIC/'selection.json', frame)
        with (PRIVATE/'decisions.tsv').open('a') as log: log.write(f'{now()}\tselection\tFreeze v1 selection and producer identities\tBefore selected bodies\t{sha(frozen.read_bytes())}\t{len(chosen)} selected\n')
    if len(chosen) != 12 or shortages: raise Stop('selection shortage')
    prefix = prefix_from_history(f)
    cp_path = PRIVATE/'checkpoint.json'; feat_path = PRIVATE/'features.json'; target_path = PRIVATE/'targets.json'
    cp = read(cp_path) if cp_path.exists() else {'selection_sha256':sha(frozen.read_bytes()), 'cases':[{'path':p,'association':'not_attempted','replay':{'status':'not_attempted'}} for p in chosen]}
    if cp['selection_sha256'] != sha(frozen.read_bytes()) or [c['path'] for c in cp['cases']] != chosen: raise Integrity('checkpoint identity drift')
    features = read(feat_path) if feat_path.exists() else []; targets = read(target_path) if target_path.exists() else []
    def checkpoint():
        save(cp_path, cp); save(feat_path, features); save(target_path, targets); save(PUBLIC/'cases.json', cp)
    checkpoint()
    stop = None
    for case in cp['cases']:
        if case['association'] != 'not_attempted': continue
        p=case['path']; q=prior.parse_path(p); iid=Path(p).stem
        seed_url=SOURCE+p; run_url=f"{SITE}data/runs/{CFG}/v1/{q['family']}/{iid}/parallel_unaware.json.gz"
        try:
            seed_raw=f.fetch(seed_url,'parallact-source');
            if collect.git_blob(seed_raw) != blobs[p]: raise Integrity('seed blob mismatch')
            run_raw=f.fetch(run_url,'parallact-site'); seed=json.loads(seed_raw); run=collect.bounded_gunzip(run_raw)
            checks, prompts, outputs=collect.association(seed,run,p,prefix)
            valid=all(v for k,v in checks.items() if k != 'timing_source_reported')
            case.update(seed_url=seed_url,seed_sha256=sha(seed_raw),run_url=run_url,run_sha256=sha(run_raw),repo=seed.get('repo'),base=seed.get('base_commit'),checks=checks,association='valid' if valid else 'invalid',execution_revision='unknown')
            if valid:
                feature=collect.safe_feature(seed,prompts); features.append(feature)
                taskhash=[sha(x.strip().encode()) for x in prompts]
                case.update(task_sha256=taskhash,pair_sha256=sha('\0'.join(taskhash).encode()),unordered_pair_sha256=sha('\0'.join(sorted(taskhash)).encode()))
                targets.append({'instance_id':iid,'status':'not_attempted'})
        except Access as exc: case.update(association='unavailable' if str(exc) != 'source_stopped' else 'not_attempted',reason=str(exc))
        except Stop as exc: case['reason']=str(exc); stop=str(exc)
        except (ValueError, KeyError, TypeError, gzip.BadGzipFile) as exc: case.update(association='invalid',reason=type(exc).__name__)
        checkpoint()
        print('association',iid,case['association'],case.get('reason',''),flush=True)
        if stop: break
    if not stop:
        for case in cp['cases']:
            if case['association'] != 'valid' or case['replay']['status'] != 'not_attempted': continue
            if f.state['repos'].get(case.get('repo'),0) >= REPO:
                case['replay']={'status':'unavailable','reason':'repository body budget exhausted in prior job'}
                checkpoint(); continue
            iid=Path(case['path']).stem
            try:
                seed=json.loads(f.fetch(case['seed_url'],'parallact-source')); run=collect.bounded_gunzip(f.fetch(case['run_url'],'parallact-site'))
                case['replay']=replay(f,seed,[run['outputs'][a] for a in ('A','B')])
                next(x for x in targets if x['instance_id']==iid).update(status=case['replay']['status'],label=case['replay'].get('label'))
            except Access as exc: case['replay']={'status':'unavailable' if str(exc) != 'source_stopped' else 'not_attempted','reason':str(exc)}
            except Stop as exc: case['replay']={'status':'not_attempted','reason':str(exc)}; stop=str(exc)
            except (ValueError,RuntimeError,OSError) as exc: case['replay']={'status':'unverified','reason':type(exc).__name__}
            checkpoint(); print('replay',iid,case['replay']['status'],case['replay'].get('label',''),flush=True)
            if stop: break
    usable=[c for c in cp['cases'] if c['association']=='valid' and c['replay'].get('status')=='complete' and c['replay'].get('repeat_identical')]
    labels=collections.Counter(c['replay']['label'] for c in usable); repos={c['repo'].lower() for c in usable}
    allowed={'instance_id','repo','base_commit','task_a','task_b'}
    privacy=all(set(x)==allowed for x in features)
    gate=len(usable)>=10 and len(repos)>=5 and labels['clean']>0 and labels['conflict']>0 and privacy and not stop and not cp.get('integrity_defects') and not any(c['replay'].get('status') in ('unverified', 'unverified_tree', 'unrepeatable_label') for c in cp['cases'])
    cp.update(gate='PASS' if gate else 'FAIL',usable=len(usable),repos=len(repos),labels=dict(labels),privacy_allowlist=privacy,stop_reason=stop,ended_at=now())
    checkpoint(); save(PUBLIC/'summary.json', {k:cp[k] for k in ('gate','usable','repos','labels','privacy_allowlist','stop_reason','ended_at')})
    return 2 if stop or any(c['association']=='not_attempted' or (c['association']=='valid' and c['replay']['status']=='not_attempted') for c in cp['cases']) else (0 if gate else 1)


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('FATAL',type(exc).__name__,str(exc),file=sys.stderr,flush=True); sys.exit(2)
