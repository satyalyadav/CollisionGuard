import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaltools import splits
from run_evaluation import audit_folds, build_records, main


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(list(args))
    return out.getvalue()


class RunEvaluationTests(unittest.TestCase):
    def test_public_data_runs_and_audit_passes(self):
        text = run('--n-boot', '20')
        self.assertIn('public ParallACT-12; 12 pairs, 5 positives', text)
        self.assertIn('Leakage audit passed for 8', text)
        for name in ('base-rate reference', 'TF-IDF cosine', 'logistic regression'):
            self.assertIn('== %s ==' % name, text)
        self.assertIn('Demo only', text)

    def test_synthetic_mode_runs(self):
        self.assertIn('Leakage audit passed for 4', run('--synthetic', '--n-boot', '20'))

    def test_cosine_scores_get_no_calibration_metrics(self):
        text = run('--synthetic', '--n-boot', '20')
        cosine_block = text.split('== TF-IDF cosine ==')[1].split('==')[0]
        self.assertIn('Brier n/a', cosine_block)

    def test_audit_catches_a_task_shared_across_repositories(self):
        pairs = [('shared task', 'one'), ('shared task', 'two'), ('three', 'four')]
        repos = [('o/a', 'o/a'), ('o/b', 'o/b'), ('o/c', 'o/c')]
        records = build_records(None, pairs, [0, 1, 0], repos, ['1', '2', '3'])
        with self.assertRaises(splits.LeakageError):
            audit_folds(records, repos)


if __name__ == '__main__':
    unittest.main()
