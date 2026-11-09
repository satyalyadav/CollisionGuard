import gzip
import io
import tarfile
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import parallact_collect as collect


class CollectTests(unittest.TestCase):
    def fixture(self):
        path = 'dataset/v2/generated/complementary/instance_org__my-repo-' + 'a'*40 + '.json'
        seed = {'instance_id': Path(path).stem, 'repo': 'org/my-repo', 'base_commit': 'b'*40,
                'agentA_problem_statement':'first task', 'agentB_problem_statement':'second task',
                'agentA_solution':'reference A', 'agentB_solution':'reference B', 'family':'secret', 'integration_test_patch':'secret'}
        run = {'cfg':collect.CFG,'v':'v2','fam':'complementary','iid':seed['instance_id'],'scen':'parallel_unaware',
               'started_at':'date','wall':1,'messages':[], 'turns':[{'agent':'A','prompt':'prefix first task'}, {'agent':'B','prompt':'prefix second task'}], 'outputs':{'A':'patch A','B':'patch B'}}
        return path,seed,run

    def test_association_and_private_allowlist(self):
        path,seed,run = self.fixture()
        checks,prompts,_ = collect.association(seed,run,path,'prefix ')
        self.assertTrue(all(checks.values()))
        self.assertEqual(set(collect.safe_feature(seed,prompts)), {'instance_id','repo','base_commit','task_a','task_b'})
        run['turns'][0]['prompt'] += ' later instruction'
        self.assertFalse(collect.association(seed,run,path,'prefix ')[0]['A_assignment'])
        run['turns'][0]['prompt'] = 'prefix first task'; run['messages'] = ['message']
        self.assertFalse(collect.association(seed,run,path,'prefix ')[0]['no_messages'])

    def test_assignment_ignores_outer_whitespace_and_rejects_extra_instructions(self):
        path, seed, run = self.fixture()
        seed['agentA_problem_statement'] += '\n\n\n'
        self.assertTrue(collect.association(seed, run, path, 'prefix ')[0]['A_assignment'])
        run['turns'][0]['prompt'] += ' extra instruction'
        self.assertFalse(collect.association(seed, run, path, 'prefix ')[0]['A_assignment'])
        run['turns'][0]['prompt'] = 'prefix first task first task'
        self.assertFalse(collect.association(seed, run, path, 'prefix ')[0]['A_assignment'])

    def test_decompression_limit(self):
        with self.assertRaises(collect.IntegrityError): collect.bounded_gunzip(gzip.compress(b' '* (16*1024*1024+1)))

    def test_budget_and_cache_drift(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return b'x'*n
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'ledger.json').write_text(json.dumps({'charged_bytes':0,'repos':{},'requests':[]}))
            meter=collect.Fetcher(p)
            with patch.object(collect.urllib.request,'urlopen',return_value=Response()):
                with self.assertRaises(collect.AccessError): meter.fetch('https://example.invalid/a','r',5)
            self.assertEqual(json.loads((p/'ledger.json').read_text())['charged_bytes'],5)
            key=collect.sha(b'https://example.invalid/b'); dest=p/'phase2'/'responses'/key; dest.write_bytes(b'drift')
            meter.state['phase2_objects'][key]={'url':'https://example.invalid/b','sha256':collect.sha(b'original')}
            with self.assertRaises(collect.IntegrityError): meter.fetch('https://example.invalid/b','r')

    def test_replay_includes_gitlink_without_loading_submodule(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive = root / 'source.tar.gz'; work = root / 'work'; work.mkdir()
            with tarfile.open(archive, 'w:gz') as tar:
                for name, data in [('root/a', b'one\n'), ('root/b', b'two\n')]:
                    item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o644
                    tar.addfile(item, io.BytesIO(data))
            repo = root / 'source'; repo.mkdir()
            collect.audit.git(repo, 'init', '-q')
            index = bytearray()
            for name, data in [('a', b'one\n'), ('b', b'two\n')]:
                blob = collect.audit.git(repo, 'hash-object', '-w', '--stdin', input=data).stdout.strip()
                index.extend(b'100644 ' + blob + b'\t' + name.encode() + b'\0')
            index.extend(b'160000 ' + b'a'*40 + b'\tvendor\0')
            collect.audit.git(repo, 'update-index', '-z', '--index-info', input=bytes(index))
            tree = collect.audit.git(repo, 'write-tree').stdout.decode().strip()
            patch_a = b'diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-one\n+changed\n'
            patch_b = b'diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-two\n+changed\n'
            with patch.object(collect.audit, 'CACHE', work):
                result = collect.replay_with_gitlinks(archive, tree, [patch_a, patch_b], [], [('vendor', 'a'*40)])
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['label'], 'clean')
            self.assertTrue(result['repeat_identical'])
            self.assertEqual(result['gitlink_count'], 1)

    def test_frozen_selection_drift(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'selection.json').write_text('{}')
            with self.assertRaises(collect.IntegrityError): collect.verify_frame(p)


if __name__ == '__main__': unittest.main()
