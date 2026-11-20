import http.server
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import io
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import swe_rebench_pilot as p  # noqa: E402


def row(**fields):
    return {'row': fields, 'truncated_cells': []}


class SelectionTests(unittest.TestCase):
    catalog = [['a-1', 'Org/A', 'b1'], ['a-2', 'org/a', 'b1'], ['a-3', 'org/a', 'b2'],
               ['b-1', 'org/b', 'c1'], ['b-2', 'org/b', 'c1'], ['b-3', 'org/b', 'c1'],
               ['x-1', 'org/x', 'd1'], ['x-2', 'org/x', 'd1'], ['n-1', 'org/n', 'e1'], ['n-2', 'org/n', 'e1']]
    traces = ['a-1', 'a-2', 'a-3', 'b-1', 'b-2', 'b-3', 'x-1', 'x-2', 'n-1']

    def test_pairs_need_traces_same_base_case_folded_repo(self):
        pairs = p.candidate_pairs(self.catalog, self.traces)
        keys = {(x['repo_key'], tuple(x['instances'])) for x in pairs}
        self.assertEqual(keys, {('org/a', ('a-1', 'a-2')), ('org/b', ('b-1', 'b-2')), ('org/b', ('b-1', 'b-3')),
                                ('org/b', ('b-2', 'b-3')), ('org/x', ('x-1', 'x-2'))})

    def test_selection_is_repository_aware_deterministic_and_excludes(self):
        pairs = p.candidate_pairs(self.catalog, self.traces)
        first, eligible = p.select_fresh(pairs, n=2, excluded={'org/x'})
        again, _ = p.select_fresh(list(reversed(pairs)), n=2, excluded={'org/x'})
        self.assertEqual(first, again)
        self.assertEqual(eligible, 2)
        self.assertEqual(sorted(c['repo_key'] for c in first), ['org/a', 'org/b'])
        smallest_b = min(p.pair_hash(x['instances']) for x in pairs if x['repo_key'] == 'org/b')
        self.assertEqual([c['pair_sha256'] for c in first if c['repo_key'] == 'org/b'], [smallest_b])

    def test_pair_hash_ignores_order_and_uses_seed(self):
        self.assertEqual(p.pair_hash(['b', 'a']), p.pair_hash(['a', 'b']))
        self.assertNotEqual(p.pair_hash(['a', 'b'], 1), p.pair_hash(['a', 'b'], 2))

    def test_frozen_selection_matches_recomputation(self):
        sel = p.PUBLIC / 'selection.json'
        if not (sel.exists() and (p.INPUT / 'catalog-metadata.json').exists()):
            self.skipTest('retained inputs absent')
        pairs = p.candidate_pairs(p.read(p.INPUT / 'catalog-metadata.json'), p.read(p.INPUT / 'trace-instance-ids.json'))
        chosen, _ = p.select_fresh(pairs)
        frozen = p.read(sel)['cases']
        self.assertEqual([c['instances'] for c in chosen], [c['instances'] for c in frozen if c['role'] == 'fresh'])
        self.assertEqual(len(pairs), 144)
        self.assertEqual(frozen[0]['instances'], p.CONTROL)

    def test_first_trace_offset_ignores_later_attempts(self):
        task, trace = p.offsets([['a', 'r', 'b'], ['c', 'r', 'b']], ['c', 'a', 'c'])
        self.assertEqual((task['c'], trace['c'], trace['a']), (1, 0, 1))


class JoinTests(unittest.TestCase):
    def pair(self, **over):
        t = row(instance_id='r__x-1', repo='o/r', base_commit='b', problem_statement='Fix the port bug.\n')
        u = row(instance_id='r__x-2', repo='o/r', base_commit='b', problem_statement='Other issue.')
        tr = row(instance_id='r__x-1', repo='o/r', model_patch='diff --git a/f b/f\n', trajectory_id='t',
                 exit_status='submit', trajectory=[{'role': 'system', 'content': 's'},
                                                   {'role': 'user', 'content': 'Please do this: Fix the port bug.'},
                                                   {'role': 'assistant', 'content': 'ok'}])
        t['row'].update(over.get('task', {})); tr['row'].update(over.get('trace', {}))
        return t, tr, u

    def check(self, **over):
        t, tr, u = self.pair(**over)
        return p.validate_join(['r__x-1', 'o/r', 'b'], 'r__x-2', t, tr, u)

    def test_good_join(self):
        r = self.check()
        self.assertTrue(r['ok'], r)
        self.assertEqual(r['user_messages'], 1)

    def test_catalog_drift_and_wrong_trace(self):
        self.assertIn('task_row_differs_from_pinned_catalog', self.check(task={'base_commit': 'other'})['problems'])
        self.assertIn('trace_instance_mismatch', self.check(trace={'instance_id': 'r__x-9'})['problems'])

    def test_text_mismatch_empty_patch_and_truncation(self):
        self.assertIn('task_text_not_in_first_prompt', self.check(task={'problem_statement': 'unrelated'})['problems'])
        self.assertIn('empty_output_patch', self.check(trace={'model_patch': ' \n'})['problems'])
        t, tr, u = self.pair()
        t['truncated_cells'] = ['patch']
        self.assertIn('truncated_cells', p.validate_join(['r__x-1', 'o/r', 'b'], 'r__x-2', t, tr, u)['problems'])

    def test_partner_leak_detected(self):
        msgs = [{'role': 'user', 'content': 'Fix the port bug. See r__x-2'}]
        r = self.check(trace={'trajectory': msgs})
        self.assertTrue(any(x.startswith('partner_leak') for x in r['problems']))
        msgs = [{'role': 'user', 'content': 'Fix the port bug.'}, {'role': 'assistant', 'content': 'Other issue.'}]
        self.assertTrue(any(x.startswith('partner_leak') for x in self.check(trace={'trajectory': msgs})['problems']))

    def test_two_user_messages_fail(self):
        msgs = [{'role': 'user', 'content': 'Fix the port bug.'}, {'role': 'user', 'content': 'more'}]
        self.assertIn('user_message_count_2', self.check(trace={'trajectory': msgs})['problems'])


class ReplayClassificationTests(unittest.TestCase):
    def merge(self, code, stdout=''):
        return {'status': 'complete', 'repeat_identical': True, 'merge': {'exit': code, 'stdout': stdout, 'stderr': ''}}

    def test_clean_and_conflict(self):
        self.assertEqual(p.classify_replay(self.merge(0))['diagnostic_label'], 'clean')
        out = p.classify_replay(self.merge(1, 'abc\n100644 ' + 'a' * 40 + ' 2\tsrc/f.py\n100644 ' + 'b' * 40 + ' 3\tsrc/f.py\n\nCONFLICT'))
        self.assertEqual((out['diagnostic_label'], out['conflict_paths'], out['artifact_only_conflict']), ('conflict', ['src/f.py'], False))

    def test_artifact_only_conflict_is_flagged(self):
        out = p.classify_replay(self.merge(1, 'x\n100644 ' + 'a' * 40 + ' 2\t.openhands/TASKS.md\n100644 ' + 'b' * 40 + ' 3\t.openhands/TASKS.md\n'))
        self.assertTrue(out['artifact_only_conflict'])
        mixed = p.classify_replay(self.merge(1, 'x\n100644 ' + 'a' * 40 + ' 2\t.openhands/TASKS.md\n100644 ' + 'b' * 40 + ' 2\ta.py\n'))
        self.assertFalse(mixed['artifact_only_conflict'])

    def test_errors_unrepeatable_and_unknown_never_labeled(self):
        for result in [{'status': 'patch_not_applicable'}, {'status': 'unrepeatable_label', 'repeat_identical': False},
                       {'status': 'unverified_tree'}, self.merge(128), self.merge(2)]:
            self.assertIsNone(p.classify_replay(result)['diagnostic_label'], result)

    def test_conflict_without_parsed_paths_is_not_artifact_only(self):
        out = p.classify_replay(self.merge(1, 'tree-only'))
        self.assertTrue(out['conflict_paths_unparsed'])
        self.assertFalse(out['artifact_only_conflict'])

    def test_normalize_patch_adds_only_one_lf(self):
        self.assertEqual(p.normalize_patch(b'a\n b'), b'a\n b\n')
        self.assertEqual(p.normalize_patch(b'a\n'), b'a\n')


class ConflictDetailTests(unittest.TestCase):
    def test_marks_scratch_artifact_and_reference_paths(self):
        new = b'diff --git a/x.py b/x.py\nnew file mode 100644\n+a\ndiff --git a/.openhands/T.md b/.openhands/T.md\nnew file mode 100644\n'
        tasks = [row(patch='diff --git a/src/f.py b/src/f.py\n', test_patch='diff --git a/tests/t.py b/tests/t.py\n')] * 2
        d = {'conflict_paths': ['x.py', '.openhands/T.md', 'src/f.py', 'tests/t.py']}
        out = {x['path']: x for x in p.conflict_detail(d, [new, new], tasks)}
        self.assertTrue(out['x.py']['new_file_in_both_outputs'] and not out['x.py']['in_reference_patches'])
        self.assertTrue(out['.openhands/T.md']['harness_artifact'])
        self.assertTrue(out['src/f.py']['in_reference_patches'] and not out['src/f.py']['new_file_in_both_outputs'])
        self.assertTrue(out['tests/t.py']['in_test_patches'])


class PrimaryVersusDiagnosticTests(unittest.TestCase):
    def rec(self, **over):
        r = {'join': {'ok': True}, 'declared_base': {'tree_verified': True, 'repeat_identical': True, 'diagnostic_label': 'clean',
                                                      'artifact_only_conflict': False},
             'snapshot': {'published_snapshot_verified': True, 'original_snapshot_verified': True}, 'contradictions': []}
        for k, v in over.items():
            r[k].update(v) if isinstance(v, dict) else r.__setitem__(k, v)
        return r

    def test_full_evidence_gives_label(self):
        self.assertEqual(p.primary_label(self.rec()), 'clean')

    def test_declared_base_alone_never_gives_primary(self):
        self.assertIsNone(p.primary_label(self.rec(snapshot={'published_snapshot_verified': None})))

    def test_published_snapshot_is_not_original(self):
        self.assertIsNone(p.primary_label(self.rec(snapshot={'original_snapshot_verified': False})))

    def test_each_failure_blocks_label(self):
        for over in [{'join': {'ok': False}}, {'declared_base': {'tree_verified': False}},
                     {'declared_base': {'repeat_identical': False}}, {'declared_base': {'diagnostic_label': None}},
                     {'declared_base': {'artifact_only_conflict': True}}, {'contradictions': ['x']}]:
            self.assertIsNone(p.primary_label(self.rec(**over)), over)

    def test_gate_and_summary_separate_classes(self):
        diag = {'case_id': 'd', 'role': 'fresh', 'repo': 'o/d', 'declared_base': {'diagnostic_label': 'clean'}, 'primary_label': None,
                'snapshot': {'status': 'unavailable', 'published_snapshot_verified': None, 'original_snapshot_verified': False},
                'contradictions': []}
        s = p.summarize([diag, {**diag, 'case_id': 'e', 'repo': 'o/e', 'declared_base': {'diagnostic_label': 'conflict'}}])
        self.assertEqual((s['strict_primary_fresh'], s['declared_base_diagnostic_fresh']), (0, {'clean': 1, 'conflict': 1}))
        self.assertFalse(s['expansion_gate']['passes'])
        ok = {**diag, 'primary_label': 'clean'}
        three = [{**ok, 'case_id': str(i), 'repo': f'o/{i}'} for i in range(3)]
        self.assertTrue(p.summarize(three)['expansion_gate']['passes'])
        same_repo = [{**ok, 'case_id': str(i)} for i in range(3)]
        self.assertFalse(p.summarize(same_repo)['expansion_gate']['passes'])
        excl = [{**ok, 'case_id': str(i), 'repo': f'o/{i}'} for i in range(3)] + [
            {**diag, 'case_id': f'x{i}', 'repo': f'x/{i}', 'exclusion': 'access:down'} for i in range(2)]
        self.assertFalse(p.summarize(excl)['expansion_gate']['passes'])

    def test_public_case_has_no_private_text(self):
        rec = {'case_id': 'c', 'role': 'fresh', 'repo': 'o/r', 'base_commit': 'b', 'instances': ['a', 'b'], 'exclusion': None,
               'primary_label': None, 'join': {'ok': True, 'problems': [[], []], 'pin_limit': 'x'}, 'patch_sha256': ['h'],
               'per_task': [{'task_text_sha256': 'secret-ish'}], 'task_metadata': [{'image': 'i'}],
               'declared_base': {'tree_verified': True, 'merge_stdout_sha256': 'h', 'replay_error': 'path /tmp'}}
        out = json.dumps(p.public_case(rec))
        self.assertNotIn('per_task', out)
        self.assertNotIn('task_metadata', out)
        self.assertNotIn('replay_error', out)

    def test_ready_export_only_for_primary_and_ids_match(self):
        recs = [{'case_id': 'a', 'repo': 'o/a', 'base_commit': 'b', 'primary_label': 'clean'},
                {'case_id': 'b', 'repo': 'o/b', 'base_commit': 'b', 'primary_label': None}]
        with tempfile.TemporaryDirectory() as d:
            feats, targets = p.export_ready(recs, d)
            self.assertEqual([f['instance_id'] for f in feats], ['a'])
            self.assertEqual(json.loads((Path(d) / 'targets.json').read_text())[0]['label'], 'clean')


class BudgetAndCheckpointTests(unittest.TestCase):
    def test_budget_room_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            b = p.Budget(Path(d) / 'b.json', total=100)
            b.charge('s', 30); b.flush()
            self.assertEqual(b.room('s', 50, 1000), 20)
            self.assertEqual(b.room('other', 50, 10), 10)
            self.assertEqual(p.Budget(Path(d) / 'b.json', total=100).used('s'), 30)

    def test_archive_precheck_caps(self):
        def tgz(files):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode='w:gz') as tf:
                for name, data in files:
                    ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
            return buf.getvalue()
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'a.tgz'
            f.write_bytes(tgz([('r/a', b'x' * 10), ('r/b', b'y' * 10)]))
            self.assertEqual(p.precheck_archive(f)['decoded_bytes'], 20)
            with self.assertRaises(p.Capacity):
                p.precheck_archive(f, member_cap=5)
            with self.assertRaises(p.Capacity):
                p.precheck_archive(f, decoded_cap=15)


class _Handler(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        body = b'x' * 1000 if self.path == '/big' else b'{"ok": 1}'
        self.send_response(200 if self.path != '/missing' else 404)
        if self.path != '/chunked':
            self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass


class FetcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_cap_stops_transfer_and_charges_declared_zero(self):
        with tempfile.TemporaryDirectory() as d:
            f = p.Fetcher(raw=d)
            with self.assertRaises(p.Capacity):
                f.get('big', self.url + '/big', 100, 's')
            self.assertFalse((Path(d) / 'bodies' / 'big').exists())
            self.assertTrue((Path(d) / 'bodies' / 'big.error').exists())
            self.assertLessEqual(f.budget.used(), 100 + 1)

    def test_cache_hit_is_not_charged_again(self):
        with tempfile.TemporaryDirectory() as d:
            f = p.Fetcher(raw=d)
            f.get('ok', self.url + '/ok', 1000, 's')
            first = f.budget.used()
            hits = _Handler.hits
            f.get('ok', self.url + '/ok', 1000, 's')
            self.assertEqual((f.budget.used(), _Handler.hits), (first, hits))
            self.assertEqual(f.budget.state['cached_bytes'], 9)

    def test_http_error_raises_unavailable_and_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            f = p.Fetcher(raw=d)
            with self.assertRaises(p.Unavailable):
                f.get('missing', self.url + '/missing', 1000, 's')
            ledger = [json.loads(x) for x in (Path(d) / 'ledger.jsonl').read_text().splitlines()]
            self.assertEqual(ledger[-1]['status'], 404)

    def test_prior_capacity_stop_is_not_refetched(self):
        with tempfile.TemporaryDirectory() as d:
            f = p.Fetcher(raw=d)
            with self.assertRaises(p.Capacity):
                f.get('big3', self.url + '/big', 100, 's')
            hits, used = _Handler.hits, f.budget.used()
            with self.assertRaises(p.Capacity):
                f.get('big3', self.url + '/big', 100, 's')
            self.assertEqual((_Handler.hits, f.budget.used()), (hits, used))

    def test_scope_cap_applies_before_global_cap(self):
        with tempfile.TemporaryDirectory() as d:
            f = p.Fetcher(raw=d)
            with self.assertRaises(p.Capacity):
                f.get('big2', self.url + '/big', 10000, 'img', scope_cap=500)


class CheckpointTests(unittest.TestCase):
    def test_atomic_save_leaves_no_tmp_and_survives_second_case(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('one', 'two'):
                p.save(Path(d) / (name + '.json'), {'case': name})
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ['one.json', 'two.json'])

    def test_git_version_gate(self):
        with mock.patch.object(p.subprocess, 'run') as run:
            run.return_value.stdout = 'git version 2.50.0\n'
            with self.assertRaises(SystemExit):
                p.check_git()
            run.return_value.stdout = 'git version 2.43.0\n'
            self.assertEqual(p.check_git(), 'git version 2.43.0')


if __name__ == '__main__':
    unittest.main()
