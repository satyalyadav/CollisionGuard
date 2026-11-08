import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
import json
from unittest import mock

spec = importlib.util.spec_from_file_location('pilot', pathlib.Path(__file__).resolve().parents[1] / 'scripts/pilot.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class SelectionAndProvenance(unittest.TestCase):
    def test_selection_rejects_shared_issue_and_shared_pr(self):
        pairs = [dict(repo_id=1, pr1_id=1, pr2_id=2, issue1_ids=[1, 2], issue2_ids=[2, 3]),
                 dict(repo_id=1, pr1_id=1, pr2_id=3, issue1_ids=[1], issue2_ids=[3]),
                 dict(repo_id=1, pr1_id=3, pr2_id=4, issue1_ids=[3], issue2_ids=[4])]
        chosen = pilot.choose_candidates(pairs)
        self.assertEqual(len(chosen), 1)
        self.assertFalse(set(chosen[0]['issue1_ids']) & set(chosen[0]['issue2_ids']))
        self.assertEqual(chosen, pilot.choose_candidates(list(reversed(pairs))))

    def test_provenance_is_not_implied_by_clean_current_merge(self):
        record = {'current_replay': {'status': 'CLEAN'}}
        self.assertFalse(pilot.strict_eligibility(record))
        for key in ('description_provenance', 'prestart_eligibility', 'historical_head_provenance', 'prestart_base_provenance'):
            record[key] = {'status': 'verified'}
        record['primary_replay'] = {'status': 'CLEAN', 'repeated': False}
        self.assertFalse(pilot.strict_eligibility(record))
        record['primary_replay']['repeated'] = True
        self.assertFalse(pilot.strict_eligibility(record))
        record['prestart_base_provenance']['sha'] = 'base'
        record['historical_head_provenance']['heads'] = ['left', 'right']
        record['primary_replay'].update(expected_base='base', merge_bases=['base'], heads=['left', 'right'],
                                       tree_id='tree', repeat_tree_id='tree', repeat_status='CLEAN')
        self.assertTrue(pilot.strict_eligibility(record))
        record['primary_replay']['repeat_tree_id'] = 'different'
        self.assertFalse(pilot.strict_eligibility(record))

    def test_unchecked_primary_evidence_stays_unassessable_without_git_caps(self):
        selected = [dict(repo_id=i // 4, pr1_id=2*i, pr2_id=2*i+1) for i in range(20)]
        records = [dict(sample=item, **{field: {'status': 'not_checked'} for field in pilot.PROVENANCE_FIELDS})
                   for item in selected]
        self.assertEqual(pilot.assess({'selected': selected}, records)['status'], 'NOT_ASSESSABLE')
        for record in records:
            for field in pilot.PROVENANCE_FIELDS:
                record[field]['status'] = 'unknown'
        self.assertEqual(pilot.assess({'selected': selected}, records)['status'], 'NO_GO')
        for record in records:
            record['git_cap_exhausted'] = True
        self.assertEqual(pilot.assess({'selected': selected}, records)['status'], 'NO_GO')

    def test_frozen_sample_rejects_changed_protocol_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'docs/pilot').mkdir(parents=True)
            protocol = root / 'docs/pilot/protocol.md'
            protocol.write_text('frozen protocol')
            cache, out = root / 'cache', root / 'out'
            cache.mkdir()
            out.mkdir()
            source = cache / 'fixture.parquet'
            source.write_bytes(b'original')
            hashes = {'fixture.parquet': pilot.digest(source)}
            pilot.save(out / 'sources.json', {'revision': pilot.REV,
                       'files': [{'name': name, 'sha256': value} for name, value in hashes.items()]})
            sample = dict(revision=pilot.REV, protocol_sha256=pilot.digest(protocol), source_sha256=hashes)
            with mock.patch.multiple(pilot, ROOT=root, CACHE=cache, OUT=out):
                pilot.validate_frozen(sample)
                source.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'Cached source'):
                    pilot.validate_frozen(sample)
                source.write_bytes(b'original')
                protocol.write_text('changed rules')
                with self.assertRaisesRegex(RuntimeError, 'protocol changed'):
                    pilot.validate_frozen(sample)

    def test_rate_limits_pause_instead_of_becoming_permanent_failures(self):
        for status, message in [(429, b'limited'), (403, b'secondary rate limit')]:
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.status_code, response.headers = status, {}
            response.iter_content.return_value = [message]
            with mock.patch.object(pilot.requests, 'get', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'RATE_LIMIT'):
                    pilot.fetch_json('https://example.invalid', {'github_response_bytes': 0})

    def test_frozen_frame_uses_half_open_windows_and_all_issue_links(self):
        import duckdb
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'docs/pilot').mkdir(parents=True)
            (root / 'docs/pilot/protocol.md').write_text('protocol fixture')
            cache = root / 'cache'
            cache.mkdir()
            con = duckdb.connect()
            con.execute("CREATE TABLE pr (id BIGINT, number BIGINT, repo_id BIGINT, repo_url VARCHAR, agent VARCHAR, created_at VARCHAR, closed_at VARCHAR)")
            con.executemany('INSERT INTO pr VALUES (?,?,?,?,?,?,?)', [
                (1, 1, 10, 'repo', 'a', '2026-01-01T00:00:00Z', '2026-01-03T00:00:00Z'),
                (2, 2, 10, 'repo', 'a', '2026-01-02T00:00:00Z', '2026-01-04T00:00:00Z'),
                (3, 3, 10, 'repo', 'b', '2026-01-03T00:00:00Z', None),
                (4, 4, 10, 'repo', 'b', '2026-01-04T00:00:00Z', '2026-01-04T00:00:00Z')])
            con.execute("CREATE TABLE links(pr_id BIGINT, issue_id BIGINT, source VARCHAR)")
            con.executemany('INSERT INTO links VALUES (?,?,?)', [(1,11,'body'),(1,99,'body'),(2,12,'body'),(2,99,'event'),(3,13,'body'),(4,14,'body')])
            con.execute('COPY pr TO ? (FORMAT PARQUET)', [str(cache / 'pull_request.parquet')])
            con.execute('COPY links TO ? (FORMAT PARQUET)', [str(cache / 'related_issue.parquet')])
            old = pilot.ROOT, pilot.CACHE, pilot.OUT
            try:
                pilot.ROOT, pilot.CACHE, pilot.OUT = root, cache, root / 'data/pilot'
                sample = pilot.freeze()
                self.assertEqual(sample['frame_size'], 1)
                self.assertEqual((sample['selected'][0]['pr1_id'], sample['selected'][0]['pr2_id']), (2, 3))
            finally:
                pilot.ROOT, pilot.CACHE, pilot.OUT = old


class GitReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.run_git('init', '-q')
        self.run_git('config', 'user.name', 'Pilot Test')
        self.run_git('config', 'user.email', 'pilot@example.invalid')
        self.commit('base\n', 'base')
        self.base = self.run_git('rev-parse', 'HEAD')

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, text, message, path='file.txt'):
        (self.repo / path).write_text(text)
        self.run_git('add', path)
        self.run_git('commit', '-qm', message)
        return self.run_git('rev-parse', 'HEAD')

    def test_clean_conflict_and_missing_object(self):
        first = self.commit('left\n', 'left')
        self.run_git('checkout', '-q', '--detach', self.base)
        conflict = self.commit('right\n', 'right')
        self.run_git('checkout', '-q', '--detach', self.base)
        clean = self.commit('other\n', 'other', 'other.txt')
        self.assertEqual(pilot.replay(self.repo, first, clean)['status'], 'CLEAN')
        self.assertEqual(pilot.replay(self.repo, first, conflict)['status'], 'CONFLICT')
        self.assertEqual(pilot.replay(self.repo, first, '0' * 40)['status'], 'ERROR')
        self.assertEqual(pilot.replay(self.repo, first, clean, primary=True)['status'], 'ERROR')
        primary = pilot.replay(self.repo, first, clean, primary=True, expected_base=self.base)
        self.assertEqual(primary['status'], 'CLEAN')
        self.assertEqual(primary['tree_id'], primary['repeat_tree_id'])
        self.assertTrue(primary['repeated'])
        self.assertEqual(pilot.replay(self.repo, first, clean, primary=True, expected_base=first)['status'], 'ERROR')

    def test_multiple_merge_bases_are_not_silently_chosen(self):
        left = self.commit('left\n', 'left')
        self.run_git('checkout', '-q', '--detach', self.base)
        right = self.commit('right\n', 'right')
        tree = self.run_git('rev-parse', self.base + '^{tree}')
        a = self.run_git('commit-tree', tree, '-p', left, '-p', right, '-m', 'a')
        b = self.run_git('commit-tree', tree, '-p', right, '-p', left, '-m', 'b')
        result = pilot.replay(self.repo, a, b, primary=True)
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(set(result['merge_bases']), {left, right})
        self.assertEqual(pilot.replay(self.repo, a, b)['status'], 'CLEAN')

    def test_shallow_history_is_not_a_definitive_label(self):
        head = self.commit('left\n', 'left')
        shallow = self.repo.parent / (self.repo.name + '-shallow')
        try:
            subprocess.check_call(['git', 'clone', '-q', '--depth=1', 'file://' + str(self.repo), str(shallow)])
            result = pilot.replay(shallow, head, head)
            self.assertEqual(result['status'], 'ERROR')
            self.assertTrue(result['shallow'])
            self.assertEqual(result['provisional_status'], 'CLEAN')
        finally:
            import shutil
            shutil.rmtree(shallow, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
