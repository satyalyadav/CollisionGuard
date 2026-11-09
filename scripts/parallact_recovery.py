#!/usr/bin/env python3
"""Post-hoc recovery of the frozen v1 cases; raw evidence stays private."""
import collections
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zlib

import parallact_pilot as pilot
import parallact_collect as collect
import parallact_v1_pilot as v1
import audit_benchmark_sources as audit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path('/home/satyal/.cache/collisionguard-parallact-recovery')
PUBLIC = ROOT / 'data/parallact-recovery'
OLD = Path('/home/satyal/.cache/collisionguard-parallact-v1-pilot')
META = 8 * 1024**2
ARCHIVE = 384 * 1024**2
TOTAL = 2 * 1024**3
REPO = 768 * 1024**2


def sha(data): return hashlib.sha256(data).hexdigest()
def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def save(path, value): pilot.save(path, value)
def read(path): return json.loads(path.read_bytes())
class Integrity(Exception): pass
class Capacity(Exception): pass
class Unavailable(Exception): pass
class Pause(Exception): pass


class Fetcher:
    def __init__(self, private, cache):
        self.private = private
        self.path = private / 'ledger.json'
        self.state = read(self.path) if self.path.exists() else {'charged_bytes':0,'repos':{},'requests':[],'objects':{},'failures':{},'cache_read_bytes':0}
        self.cache = {x['url']:x for x in cache}
        self.write()
    def write(self): save(self.path, self.state)
    def fetch(self, url, repo, cap=META): return self.fetch_path(url, repo, cap).read_bytes()
    def fetch_path(self, url, repo, cap=META):
        key = sha(url.encode()); dest = self.private / 'responses' / key
        item = self.state['objects'].get(key)
        if item:
            if item['url'] != url or not dest.exists() or file_hash(dest) != item['sha256']: raise Integrity('recovery cache drift')
            return dest
        if url in self.cache:
            item = self.cache[url]; path = Path(item['path'])
            if not path.is_file() or file_hash(path) != item['sha256'] or (item.get('bytes') is not None and path.stat().st_size != item['bytes']): raise Integrity('old cache drift')
            if path.stat().st_size > cap: raise Capacity('cached response exceeds cap')
            self.state['cache_read_bytes'] += path.stat().st_size; self.write()
            return path
        host = urllib.parse.urlsplit(url).netloc
        if self.state['failures'].get(host, 0) >= 3: raise Unavailable('host paused after failures')
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = self.private / 'partial' / (key + '-' + str(len(self.state['requests'])))
        partial.parent.mkdir(parents=True, exist_ok=True)
        entry = {'url':url,'repo':repo,'status':'started','charged_bytes':0,'partial':str(partial)}
        self.state['requests'].append(entry); self.write()
        error = None
        try:
            request = urllib.request.Request(url, headers={'User-Agent':'CollisionGuard-recovery'})
            try: response = urllib.request.urlopen(request, timeout=45)
            except urllib.error.HTTPError as exc: response, error = exc, exc
            with response, partial.open('wb') as out:
                size = 0
                while True:
                    remaining = min(TOTAL-self.state['charged_bytes'], REPO-self.state['repos'].get(repo,0))
                    if remaining <= 0: raise Capacity('body budget exhausted')
                    # A single charged byte distinguishes exact EOF from an oversized body.
                    n = min(65536, remaining, max(1, cap-size))
                    entry['charged_bytes'] += n; self.state['charged_bytes'] += n
                    self.state['repos'][repo] = self.state['repos'].get(repo,0) + n; self.write()
                    chunk = response.read(n)
                    unused = n-len(chunk); entry['charged_bytes'] -= unused; self.state['charged_bytes'] -= unused; self.state['repos'][repo] -= unused
                    if chunk: out.write(chunk); out.flush(); os.fsync(out.fileno())
                    self.write()
                    if not chunk: break
                    size += len(chunk)
                    if size > cap: raise Capacity('response exceeds cap')
            digest = file_hash(partial)
            if error:
                entry.update(status='http_error',http_status=error.code,sha256=digest)
                if error.code == 429 or (error.code == 403 and error.headers.get('X-RateLimit-Remaining') == '0'): raise Pause('rate limit')
                self.state['failures'][host] = self.state['failures'].get(host,0)+1
                raise Unavailable('http_'+str(error.code))
            os.replace(partial, dest)
            self.state['objects'][key] = {'url':url,'sha256':digest,'bytes':size}
            entry.update(status='saved',sha256=digest); self.state['failures'][host] = 0; self.write()
            return dest
        except (Capacity, Pause, Unavailable) as exc:
            if entry['status'] == 'started': entry.update(status=type(exc).__name__, reason=str(exc))
            if error and (error.code == 429 or (error.code == 403 and error.headers.get('X-RateLimit-Remaining') == '0')):
                entry.update(status='rate_limit',http_status=error.code)
                raise Pause('rate limit') from exc
            raise
        except Exception as exc:
            entry.update(status='failure',reason=type(exc).__name__)
            if error and (error.code == 429 or (error.code == 403 and error.headers.get('X-RateLimit-Remaining') == '0')):
                entry.update(status='rate_limit',http_status=error.code)
                raise Pause('rate limit') from exc
            self.state['failures'][host] = self.state['failures'].get(host,0)+1
            raise Unavailable(type(exc).__name__) from exc
        finally:
            if partial.exists(): entry.update(partial_sha256=file_hash(partial),partial_bytes=partial.stat().st_size)
            self.write()


def decode_gzip(source, dest, limit):
    # zlib's max_length prevents buffered gzip readers from decoding a larger
    # block when only a boundary byte remains.
    total = 0
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = b''
    finished = False
    while True:
        if not pending:
            pending = source.read(65536)
            if not pending:
                if not finished: raise Integrity('truncated gzip stream')
                return total
        if finished:
            pending = pending.lstrip(b'\0')
            if not pending: continue
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            finished = False
        chunk = decoder.decompress(pending, limit-total+1)
        pending = decoder.unconsumed_tail
        if decoder.eof:
            pending = decoder.unused_data
            finished = True
        if total + len(chunk) > limit: raise Capacity('decoded limit')
        dest.write(chunk)
        total += len(chunk)


def cache_index():
    ledger = read(OLD / 'ledger.json')
    return [dict(item, path=OLD/'responses'/key) for key,item in ledger['objects'].items() if not item.get('http_status')]


def target_for(case):
    replay = case['replay']
    return {'instance_id':Path(case['path']).stem, 'status':replay['status'], 'label':replay.get('label')}

def gate(cases, privacy):
    usable = [c for c in cases if c['association']=='valid' and c['replay'].get('status')=='complete' and c['replay'].get('repeat_identical') and c['replay'].get('label') in ('clean','conflict')]
    return len(usable)>=10 and len({c['repo'].lower() for c in usable})>=5 and {c['replay']['label'] for c in usable}=={'clean','conflict'} and privacy

def save_outputs(private, cases, features):
    ready = {Path(c['path']).stem for c in cases if c['association']=='valid' and c['replay'].get('status')=='complete' and c['replay'].get('repeat_identical') and c['replay'].get('label') in ('clean','conflict')}
    feat = [x for x in features if x['instance_id'] in ready]
    targets = [target_for(c) for c in cases if Path(c['path']).stem in ready]
    save(private/'checkpoint.json', {'cases':cases})
    save(private/'features.json', feat); save(private/'targets.json', targets)
    save(private/'audit.json', [target_for(c) for c in cases if Path(c['path']).stem not in ready])

def attempt(case, fn, private, features, cases=None):
    try: case['replay'] = fn()
    except Pause as exc: case['replay']={'status':'not_attempted','reason':str(exc)}; raise
    except Capacity as exc: case['replay']={'status':'capacity_limited','reason':str(exc)}
    except Unavailable as exc: case['replay']={'status':'unavailable','reason':str(exc)}
    except Exception as exc: case['replay']={'status':'unverified','reason':type(exc).__name__}
    finally: save_outputs(private, cases if cases is not None else [case], features)


def replay(fetcher, seed, outputs):
    repo, base = seed['repo'], seed['base_commit']
    commit_url = f'https://api.github.com/repos/{repo}/git/commits/{base}'
    commit = json.loads(fetcher.fetch(commit_url,repo)); expected=commit.get('tree',{}).get('sha','')
    if commit.get('sha') != base or not re.fullmatch('[0-9a-f]{40}',expected): raise Integrity('commit identity')
    url=f'https://codeload.github.com/{repo}/tar.gz/{base}'
    archive=fetcher.fetch_path(url,repo,ARCHIVE)
    # Check the entire decoded stream before passing the original gzip to tarfile.
    with archive.open('rb') as source, open(os.devnull,'wb') as sink: decoded=decode_gzip(source,sink,1024**3)
    audit.CACHE=PRIVATE/'work'; audit.CACHE.mkdir(parents=True,exist_ok=True)
    result=audit.replay(archive,expected,[x.encode() for x in outputs])
    if result['status']=='unverified_tree':
        tree=json.loads(fetcher.fetch(f'https://api.github.com/repos/{repo}/git/trees/{expected}?recursive=1',repo))
        if tree.get('truncated') or tree.get('sha') != expected: raise Integrity('recursive tree identity')
        original={name:(mode,collect.git_blob(data)) for name,mode,data in audit.archive_entries(archive)}
        entries={x['path']:x for x in tree['tree'] if x['type']!='tree'}
        if any(x['type'] not in ('blob','commit') or (x['type']=='commit' and x['mode']!='160000') for x in entries.values()) or original.keys()-entries.keys(): raise Integrity('archive entries mismatch')
        changed={n for n,val in original.items() if (entries[n]['mode'],entries[n]['sha']) != val}
        additions=[]; links=[]
        for name in sorted((entries.keys()-original.keys()) | changed):
            item=entries[name]
            if name=='.git' or name.startswith('.git/') or any(p in ('','.','..') for p in name.split('/')): raise Integrity('unsafe supplemental path')
            if item['type']=='commit': links.append((name,item['sha'])); continue
            if item['mode'] not in ('100644','100755','120000') or item.get('size',audit.LIMIT+1)>audit.LIMIT: raise Integrity('supplemental mode or size')
            blob=fetcher.fetch(f'https://raw.githubusercontent.com/{repo}/{base}/'+urllib.parse.quote(name,safe='/'),repo,audit.LIMIT)
            if len(blob)!=item['size'] or collect.git_blob(blob)!=item['sha']: raise Integrity('supplemental blob identity')
            additions.append((name,item['mode'],blob))
        # Replace archive-substituted files only with independently verified Git blobs.
        original_reader=audit.archive_entries
        def filtered(path): return [entry for entry in original_reader(path) if entry[0] not in changed]
        audit.archive_entries=filtered
        try:
            result=collect.replay_with_gitlinks(archive,expected,[x.encode() for x in outputs],additions,links) if links else audit.replay(archive,expected,[x.encode() for x in outputs],additions)
        finally: audit.archive_entries=original_reader
        result.update(supplemented_count=len(additions),gitlink_count=len(links),replaced_archive_entries=len(changed))
    keys=('status','snapshot_tree','expected_tree','archive_entries','base_head','agent_heads','repeat_identical','label','patch_index','supplemented_count','gitlink_count','replaced_archive_entries')
    result={k:result[k] for k in keys if k in result}
    result.update(archive_url=url,archive_sha256=file_hash(archive),archive_bytes=archive.stat().st_size,decoded_bytes=decoded,commit_url=commit_url,patch_sha256=[sha(x.encode()) for x in outputs])
    return result


def identities():
    names=['scripts/parallact_recovery.py','scripts/parallact_collect.py','scripts/parallact_pilot.py','scripts/parallact_v1_pilot.py','scripts/audit_benchmark_sources.py','docs/pilot/parallact-recovery-protocol.md','data/parallact-v1-pilot/selection.json']
    return {name:file_hash(ROOT/name) for name in names}

def freeze_sources():
    ids=identities(); directory=PRIVATE/'producers'; directory.mkdir(parents=True,exist_ok=True)
    for name,digest in ids.items():
        target=directory/digest
        if target.exists():
            if file_hash(target)!=digest: raise Integrity('producer snapshot drift')
        else:
            shutil.copyfile(ROOT/name,target)
            if file_hash(target)!=digest: raise Integrity('producer snapshot copy drift')
    identity=PRIVATE/'identity.json'
    previous=read(identity) if identity.exists() else None
    if previous and previous!=ids:
        if any(previous.get(k)!=v for k,v in ids.items() if k!='scripts/parallact_recovery.py'): raise Integrity('helper identity drift')
        for digest in previous.values():
            if not (directory/digest).exists() or file_hash(directory/digest)!=digest: raise Integrity('previous producer snapshot drift')
        transition={'previous':previous,'current':ids,'reason':'producer correction; previous and current source snapshots retained'}
        save(PRIVATE/('transition-'+ids['scripts/parallact_recovery.py']+'.json'),transition)
        save(identity,ids)
    elif not previous: save(identity,ids)
    return ids,previous

def historical_prefix():
    case=read(ROOT/'data/parallact-pilot/retention.json')['cases'][0]
    stem=Path(case['path']).stem
    old=Path('/home/satyal/.cache/collisionguard-parallact-pilot')/'responses'
    seed_raw=(old/(stem+'.seed.json')).read_bytes(); run_raw=(old/(stem+'.run.json.gz')).read_bytes()
    if sha(seed_raw)!=case['expected_seed_sha256'] or sha(run_raw)!=case['expected_run_sha256']: raise Integrity('historical template evidence drift')
    seed=json.loads(seed_raw); run=collect.bounded_gunzip(run_raw)
    statement=seed['agentA_problem_statement']; prompt=next(t['prompt'] for t in run['turns'] if t['agent']=='A')
    if prompt.count(statement)!=1: raise Integrity('historical template mismatch')
    return prompt[:prompt.index(statement)]

def main():
    PRIVATE.mkdir(parents=True,exist_ok=True); PUBLIC.mkdir(parents=True,exist_ok=True)
    ids,previous=freeze_sources()
    selection=read(ROOT/'data/parallact-v1-pilot/selection.json')
    if ids['data/parallact-v1-pilot/selection.json']!='7cdd8af5c03df07c607ff21a3258a0ba9c6d2377d28fdc041dc940f6483c0d31': raise Integrity('selection identity')
    paths=selection['paths']
    if len(paths)!=12 or len(set(paths))!=12: raise Integrity('selection denominator')
    manifest_path=Path('/home/satyal/.cache/collisionguard-parallact-pilot/manifest.json')
    if file_hash(manifest_path)!=selection['source_manifest_sha256']: raise Integrity('manifest identity')
    manifest=read(manifest_path)
    if manifest.get('sha')!=pilot.PIN or manifest.get('truncated'): raise Integrity('manifest pin')
    blobs={x['path']:x['sha'] for x in manifest['tree']}
    oldcases={x['path']:x for x in read(ROOT/'data/parallact-v1-pilot/cases.json')['cases']}
    prefix=historical_prefix(); fetcher=Fetcher(PRIVATE,cache_index())
    checkpoint=PRIVATE/'checkpoint.json'; featurefile=PRIVATE/'all-features.json'
    cases=read(checkpoint)['cases'] if checkpoint.exists() else [{'path':p,'association':'not_attempted','replay':{'status':'not_attempted'}} for p in paths]
    if [x['path'] for x in cases]!=paths: raise Integrity('checkpoint selection drift')
    features=read(featurefile) if featurefile.exists() else []
    if previous and previous!=ids:
        for case in cases:
            if case['replay'].get('status')=='complete': case.setdefault('producer_sha256',previous['scripts/parallact_recovery.py'])
    save_outputs(PRIVATE,cases,features)
    for case in cases:
        if case['association']=='valid': continue
        p=case['path']; info=pilot.parse_path(p); iid=Path(p).stem
        seed_url=collect.SOURCE+p; run_url=f"{collect.SITE}data/runs/{collect.CFG}/v1/{info['family']}/{iid}/parallel_unaware.json.gz"
        try:
            seed_raw=fetcher.fetch(seed_url,'parallact-source'); run_raw=fetcher.fetch(run_url,'parallact-site')
            old=oldcases[p]
            if sha(seed_raw)!=old['seed_sha256'] or sha(run_raw)!=old['run_sha256'] or collect.git_blob(seed_raw)!=blobs[p]: raise Integrity('seed or run identity')
            seed=json.loads(seed_raw); run=collect.bounded_gunzip(run_raw)
            checks,prompts,outputs=collect.association(seed,run,p,prefix)
            if not all(v for k,v in checks.items() if k!='timing_source_reported'): raise Integrity('association mismatch')
            feature=collect.safe_feature(seed,prompts)
            if set(feature)!={'instance_id','repo','base_commit','task_a','task_b'} or seed['repo']!=old['repo'] or seed['base_commit']!=old['base']: raise Integrity('feature identity')
            features=[x for x in features if x['instance_id']!=iid]+[feature]
            save(featurefile,features)
            case.update(association='valid',seed_url=seed_url,seed_sha256=sha(seed_raw),run_url=run_url,run_sha256=sha(run_raw),repo=seed['repo'],base=seed['base_commit'],checks=checks,execution_revision='unknown',site_revision='unknown')
            taskhash=[sha(x.strip().encode()) for x in prompts]
            case.update(task_sha256=taskhash,unordered_pair_sha256=sha('\0'.join(sorted(taskhash)).encode()))
        except Pause: raise
        except Exception as exc:
            case.update(association='unverified',reason=type(exc).__name__)
        finally: save_outputs(PRIVATE,cases,features)
        print('association',iid,case['association'],flush=True)
    # Cached source archives first; the sort key uses only URL presence and path.
    def order(case):
        url=f"https://codeload.github.com/{case.get('repo','')}/tar.gz/{case.get('base','')}"
        return (url not in fetcher.cache,case['path'])
    for case in sorted(cases,key=order):
        if case['association']!='valid' or case['replay']['status']=='complete': continue
        def run_case():
            seed_raw=fetcher.fetch(case['seed_url'],'parallact-source'); run_raw=fetcher.fetch(case['run_url'],'parallact-site')
            if sha(seed_raw)!=case['seed_sha256'] or sha(run_raw)!=case['run_sha256']: raise Integrity('replay input drift')
            seed=json.loads(seed_raw); run=collect.bounded_gunzip(run_raw)
            return replay(fetcher,seed,[run['outputs'][a] for a in ('A','B')])
        attempt(case,run_case,PRIVATE,features,cases)
        case['producer_sha256']=ids['scripts/parallact_recovery.py']
        save_outputs(PRIVATE,cases,features)
        print('replay',Path(case['path']).stem,case['replay']['status'],case['replay'].get('label',''),flush=True)
    ready=read(PRIVATE/'features.json'); targets=read(PRIVATE/'targets.json')
    ids_ready=[x['instance_id'] for x in ready]; target_ids=[x['instance_id'] for x in targets]
    privacy=all(set(x)=={'instance_id','repo','base_commit','task_a','task_b'} for x in ready) and len(ids_ready)==len(set(ids_ready)) and set(ids_ready)==set(target_ids) and len(target_ids)==len(set(target_ids))
    usable=[c for c in cases if c['association']=='valid' and c['replay'].get('status')=='complete' and c['replay'].get('repeat_identical') and c['replay'].get('label') in ('clean','conflict')]
    counts=collections.Counter(c['replay']['label'] for c in usable)
    summary={'gate':'PASS' if gate(cases,privacy) else 'FAIL','usable':len(usable),'denominator':12,'repositories':sorted({c['repo'] for c in usable}),'labels':dict(counts),'feature_target_ids_match':privacy,'new_body_bytes':fetcher.state['charged_bytes'],'verified_cache_read_bytes':fetcher.state['cache_read_bytes'],'producer_hashes':ids,'execution_revision':'unknown','site_revision':'unknown','peer_review':'pending'}
    save(PUBLIC/'summary.json',summary); save(PUBLIC/'cases.json',{'cases':cases})
    print(json.dumps(summary,sort_keys=True),flush=True)
    return 0 if summary['gate']=='PASS' else 1

if __name__=='__main__':
    import sys
    try: sys.exit(main())
    except Exception as exc:
        print('FATAL',type(exc).__name__,str(exc),file=sys.stderr,flush=True); sys.exit(2)
