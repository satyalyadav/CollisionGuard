from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaltools import schema, splits
from evaltools.synthetic import make_synthetic_records, make_synthetic_scores
from evaltools.report import evaluate, format_report, prevalence_scores


def rec(iid, repo, a, b, label=0, family=None, time=None):
    return {'instance_id': iid, 'repo': repo, 'task_a_id': a, 'task_b_id': b,
            'label': label, 'family': family, 'time': time}


class SchemaTests(unittest.TestCase):
    def test_label_and_task_id_conventions(self):
        self.assertEqual(schema.normalize_label('conflict'), 1)
        self.assertEqual(schema.normalize_label('clean'), 0)
        with self.assertRaises(schema.SchemaError):
            schema.normalize_label('maybe')
        self.assertEqual(schema.task_id('  fix it\n'), schema.task_id('fix it'))
        rows = schema.normalize_records([{'instance_id': 'x', 'repo': 'r', 'task_a': 'one',
                                          'task_b': 'two', 'label': 'clean'}])
        self.assertEqual(rows[0]['task_a'], schema.task_id('one'))

    def test_rejects_bad_rows(self):
        with self.assertRaises(schema.SchemaError):
            schema.normalize_records([rec('a', 'r', 't1', 't2'), rec('a', 'r', 't3', 't4')])
        with self.assertRaises(schema.SchemaError):
            schema.normalize_records([rec('a', 'r', 't1', 't1')])

    def test_join_requires_matching_ids(self):
        f = [{'instance_id': '1', 'repo': 'r', 'task_a': 'x', 'task_b': 'y'}]
        self.assertEqual(schema.join_features_targets(f, [{'instance_id': '1', 'label': 'conflict'}])[0]['label'], 1)
        with self.assertRaises(schema.SchemaError):
            schema.join_features_targets(f, [{'instance_id': '2', 'label': 'clean'}])


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.records = schema.normalize_records(make_synthetic_records(seed=4))

    def test_kfold_covers_everything_once_and_never_leaks(self):
        folds = splits.group_kfold(self.records, n_splits=4, seed=1)
        seen = []
        for train, test in folds:
            splits.assert_no_leakage(splits.take(self.records, train), splits.take(self.records, test))
            seen += test
        self.assertEqual(sorted(seen), list(range(len(self.records))))

    def test_kfold_is_repeatable(self):
        self.assertEqual(splits.group_kfold(self.records, 4, seed=9), splits.group_kfold(self.records, 4, seed=9))

    def test_too_few_groups_fails_loudly(self):
        with self.assertRaises(splits.SplitError):
            splits.group_kfold(self.records, n_splits=9)

    def test_task_shared_across_repos_merges_those_repos(self):
        rows = schema.normalize_records([
            rec('1', 'A', 'shared', 't1'), rec('2', 'B', 'shared', 't2'), rec('3', 'C', 't3', 't4')])
        self.assertEqual(len(set(splits.assign_groups(rows))), 2)
        with self.assertRaises(splits.SplitError):
            splits.group_kfold(rows, n_splits=3)

    def test_family_keeps_repos_together(self):
        rows = schema.normalize_records([
            rec('1', 'A', 't1', 't2', family='f'), rec('2', 'B', 't3', 't4', family='f')])
        self.assertEqual(len(set(splits.assign_groups(rows))), 1)

    def test_holdout_keeps_both_sides_nonempty(self):
        train, test = splits.holdout_split(self.records, 0.25, seed=2)
        self.assertTrue(train and test)
        splits.assert_no_leakage(splits.take(self.records, train), splits.take(self.records, test))

    def test_leakage_check_catches_each_planted_leak(self):
        base = schema.normalize_records([rec('1', 'A', 't1', 't2', family='f1')])
        cases = {
            'repo': rec('2', 'A', 't8', 't9'),
            'task': rec('2', 'B', 't1', 't9'),
            'family': rec('2', 'B', 't8', 't9', family='f1'),
            'pair': rec('2', 'B', 't2', 't1'),
            'instance_id': rec('1', 'B', 't8', 't9'),
        }
        for name, row in cases.items():
            with self.assertRaises(splits.LeakageError, msg=name) as ctx:
                splits.assert_no_leakage(base, schema.normalize_records([row]))
            self.assertIn(name, str(ctx.exception))
        clean = schema.normalize_records([rec('2', 'B', 't8', 't9')])
        splits.assert_no_leakage(base, clean)

    def test_forward_time_split_drops_shared_tasks(self):
        rows = schema.normalize_records([
            rec('1', 'A', 't1', 't2', time=1), rec('2', 'A', 't3', 't4', time=2),
            rec('3', 'A', 't1', 't5', time=5), rec('4', 'B', 't6', 't7', time=6),
            rec('5', 'A', 't8', 't9', time=7)])
        train, test, dropped = splits.forward_time_split(rows, cutoff=3)
        self.assertEqual((train, test), ([0, 1], [3, 4]))
        self.assertEqual(dropped, [(2, 'shared_task')])
        splits.assert_no_leakage(splits.take(rows, train), splits.take(rows, test), allow_shared_repos=True)
        _, test, dropped = splits.forward_time_split(rows, cutoff=3, unseen_repos=True)
        self.assertEqual(test, [3])
        self.assertIn((4, 'seen_repo'), dropped)

    def test_forward_time_needs_times(self):
        with self.assertRaises(splits.SplitError):
            splits.forward_time_split(schema.normalize_records([rec('1', 'A', 't1', 't2')]), cutoff=1)


class EndToEndTests(unittest.TestCase):
    def test_pipeline_on_synthetic_data(self):
        records = schema.normalize_records(make_synthetic_records(n_repos=10, pairs_per_repo=8, seed=7))
        out_of_fold = {}
        for train, test in splits.group_kfold(records, 5, seed=0):
            tr, te = splits.take(records, train), splits.take(records, test)
            splits.assert_no_leakage(tr, te)
            for r, s in zip(te, prevalence_scores(tr, te)):
                out_of_fold[r['instance_id']] = s
        flat = evaluate(records, out_of_fold, n_boot=50)
        good = evaluate(records, make_synthetic_scores(records, signal=0.4, seed=1), n_boot=50)
        # one constant score ties every pair, so AP equals prevalence exactly
        constant = evaluate(records, [0.3] * len(records), n_boot=50)
        self.assertAlmostEqual(constant['average_precision'], constant['prevalence'], places=9)
        self.assertGreater(good['average_precision'], flat['average_precision'])
        self.assertIn('average precision', format_report(good, 'demo'))


if __name__ == '__main__':
    unittest.main()
