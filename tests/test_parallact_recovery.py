import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import parallact_recovery as r


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.fetcher = r.Fetcher(self.path, [])

    def test_exact_cap_and_overflow_probe(self):
        for body, good in [(b'1234', True), (b'12345', False)]:
            url = 'https://example.test/' + str(len(body))
            with mock.patch.object(r.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
                if good:
                    self.assertEqual(self.fetcher.fetch(url, 'repo', 4), body)
                else:
                    with self.assertRaises(r.Capacity): self.fetcher.fetch(url, 'repo', 4)
        self.assertEqual(self.fetcher.state['charged_bytes'], 9)
        self.assertEqual(next((self.path / 'partial').glob('*')).read_bytes(), b'12345')

    def test_failure_keeps_partial(self):
        class Broken(io.BytesIO):
            def read(self, n=-1):
                if self.tell(): raise OSError('interrupted')
                return super().read(min(n, 3))
        with mock.patch.object(r.urllib.request, 'urlopen', return_value=Broken(b'abcdef')):
            with self.assertRaises(r.Unavailable): self.fetcher.fetch('https://x.test/a', 'repo', 10)
        self.assertEqual(next((self.path / 'partial').glob('*')).read_bytes(), b'abc')

    def test_decoded_limit_is_distinct(self):
        payload = gzip.compress(b'x' * 17)
        with self.assertRaises(r.Capacity): r.decode_gzip(io.BytesIO(payload), io.BytesIO(), 16)
        out = io.BytesIO(); r.decode_gzip(io.BytesIO(payload), out, 32)
        self.assertEqual(out.getvalue(), b'x' * 17)

    def test_concatenated_gzip_and_truncation(self):
        data = gzip.compress(b'abc') + gzip.compress(b'def') + b'\0\0'
        out = io.BytesIO()
        self.assertEqual(r.decode_gzip(io.BytesIO(data), out, 6), 6)
        self.assertEqual(out.getvalue(), b'abcdef')
        with self.assertRaises(r.Integrity): r.decode_gzip(io.BytesIO(gzip.compress(b'abc')[:-2]), io.BytesIO(), 10)

    def test_cache_identity_drift(self):
        old = self.path / 'old'; old.write_bytes(b'changed')
        f = r.Fetcher(self.path / 'new', [{'url':'https://x.test/a', 'sha256':r.sha(b'original'), 'path':old}])
        with self.assertRaises(r.Integrity): f.fetch('https://x.test/a', 'repo')

    def test_helper_exception_syncs_checkpoint(self):
        case = {'path':'a', 'association':'valid', 'replay':{'status':'not_attempted'}}
        with mock.patch.object(r, 'save_outputs') as save:
            r.attempt(case, lambda: (_ for _ in ()).throw(r.collect.IntegrityError('bad')), self.path, [])
        self.assertEqual(case['replay']['status'], 'unverified')
        self.assertTrue(save.called)
        self.assertEqual(r.target_for(case)['status'], 'unverified')

    def test_helper_exception_persists_matching_audit_status(self):
        case = {'path':'case.json', 'association':'valid', 'replay':{'status':'not_attempted'}}
        r.attempt(case, lambda: (_ for _ in ()).throw(r.collect.IntegrityError('bad')), self.path, [])
        checkpoint = json.loads((self.path / 'checkpoint.json').read_text())['cases'][0]
        audit = json.loads((self.path / 'audit.json').read_text())[0]
        self.assertEqual(checkpoint['replay']['status'], audit['status'])
        self.assertEqual(audit['status'], 'unverified')
        self.assertEqual(json.loads((self.path / 'targets.json').read_text()), [])

    def test_http_error_body_is_retained_and_charged(self):
        from urllib.error import HTTPError
        error = HTTPError('https://x.test/error', 500, 'error', {}, io.BytesIO(b'failure body'))
        with mock.patch.object(r.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(r.Unavailable): self.fetcher.fetch('https://x.test/error', 'repo')
        self.assertEqual(next((self.path / 'partial').glob('*')).read_bytes(), b'failure body')
        self.assertEqual(self.fetcher.state['charged_bytes'], len(b'failure body'))
        self.assertEqual(self.fetcher.state['requests'][0]['status'], 'http_error')

    def test_replay_replaces_mismatched_archive_blob_with_verified_blob(self):
        archive = self.path / 'archive'; archive.write_bytes(b'archive')
        expected = 'a' * 40
        replacement = b'expected'
        tree = {'sha':expected, 'truncated':False, 'tree':[{'path':'file', 'type':'blob', 'mode':'100644', 'sha':r.collect.git_blob(replacement), 'size':len(replacement)}]}
        class Fetch:
            def fetch_path(self, url, repo, cap): return archive
            def fetch(self, url, repo, cap=r.META):
                if '/git/commits/' in url: return json.dumps({'sha':'base', 'tree':{'sha':expected}}).encode()
                if '/git/trees/' in url: return json.dumps(tree).encode()
                return replacement
        calls = []
        def replay(path, tree_id, patches, additions=()):
            calls.append((r.audit.archive_entries(path), list(additions)))
            if len(calls) == 1: return {'status':'unverified_tree'}
            return {'status':'complete', 'repeat_identical':True, 'label':'clean', 'expected_tree':tree_id, 'snapshot_tree':tree_id}
        with mock.patch.object(r, 'PRIVATE', self.path), mock.patch.object(r, 'decode_gzip', return_value=1), mock.patch.object(r.audit, 'archive_entries', return_value=[('file','100644',b'archive-content')]), mock.patch.object(r.audit, 'replay', side_effect=replay):
            result = r.replay(Fetch(), {'repo':'owner/repo','base_commit':'base'}, ['a','b'])
        self.assertEqual(calls[1], ([], [('file','100644',replacement)]))
        self.assertEqual(result['replaced_archive_entries'], 1)
        self.assertEqual(result['status'], 'complete')

    def test_rate_limit_pauses_even_when_error_body_exceeds_cap(self):
        from urllib.error import HTTPError
        error = HTTPError('https://x.test/limited', 429, 'limited', {}, io.BytesIO(b'too long'))
        with mock.patch.object(r.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(r.Pause): self.fetcher.fetch('https://x.test/limited', 'repo', 3)
        self.assertEqual(next((self.path / 'partial').glob('*')).read_bytes(), b'too ')
        self.assertEqual(self.fetcher.state['requests'][0]['status'], 'rate_limit')

    def test_gate_allows_capacity_exclusions(self):
        cases = [{'association':'valid','repo':f'r{i % 5}', 'replay':{'status':'complete','repeat_identical':True,'label':'clean' if i % 2 else 'conflict'}} for i in range(10)]
        cases += [{'association':'valid','replay':{'status':'capacity_limited'}} for _ in range(2)]
        self.assertTrue(r.gate(cases, True))
        cases[0]['replay']['repeat_identical'] = False
        self.assertFalse(r.gate(cases, True))
