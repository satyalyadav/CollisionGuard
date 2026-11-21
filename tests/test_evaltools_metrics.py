import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaltools import metrics as m
from evaltools.bootstrap import cluster_bootstrap, paired_difference

Y = [1, 0, 1, 0]
S = [0.9, 0.8, 0.7, 0.1]


class MetricTests(unittest.TestCase):
    def test_average_precision_by_hand(self):
        # thresholds .9 .8 .7 .1 give P = 1, 1/2, 2/3, 1/2 and R = .5, .5, 1, 1
        self.assertAlmostEqual(m.average_precision(Y, S), 0.5 * 1 + 0.5 * (2 / 3))

    def test_perfect_and_constant_scores(self):
        self.assertEqual(m.average_precision([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]), 1.0)
        # one tied threshold: AP equals prevalence, whatever the input order
        self.assertAlmostEqual(m.average_precision([1, 0, 0, 0], [0.5] * 4), 0.25)
        self.assertAlmostEqual(m.average_precision([0, 0, 0, 1], [0.5] * 4), 0.25)

    def test_ap_and_trapezoid_are_different_numbers(self):
        self.assertAlmostEqual(m.pr_auc_trapezoid(Y, S), 0.5 + 0.5 * (0.5 + 2 / 3) / 2)
        self.assertNotAlmostEqual(m.pr_auc_trapezoid(Y, S), m.average_precision(Y, S))

    def test_undefined_without_positives(self):
        self.assertTrue(math.isnan(m.average_precision([0, 0], [0.2, 0.4])))
        self.assertTrue(math.isnan(m.pr_auc_trapezoid([0, 0], [0.2, 0.4])))

    def test_precision_at_recall(self):
        self.assertEqual(m.precision_at_recall(Y, S, 0.5), (1.0, 0.9))
        precision, thr = m.precision_at_recall(Y, S, 1.0)
        self.assertAlmostEqual(precision, 2 / 3)
        self.assertEqual(thr, 0.7)

    def test_recall_at_top_fraction_never_exceeds_budget(self):
        self.assertEqual(m.recall_at_top_fraction(Y, S, 0.25), (0.5, 1))
        # a tie that would overflow the budget is not split
        self.assertEqual(m.recall_at_top_fraction([1, 0, 0, 0], [0.5] * 4, 0.5), (0.0, 0))

    def test_confusion(self):
        c = m.confusion_at_threshold(Y, S, 0.75)
        self.assertEqual((c['tp'], c['fp'], c['tn'], c['fn']), (1, 1, 1, 1))
        self.assertAlmostEqual(c['f1'], 0.5)

    def test_brier_and_log_loss_by_hand(self):
        self.assertAlmostEqual(m.brier_score([1, 0], [0.8, 0.3]), 0.065)
        self.assertAlmostEqual(m.log_loss([1, 0], [0.8, 0.3]), -(math.log(0.8) + math.log(0.7)) / 2)
        self.assertTrue(math.isfinite(m.log_loss([1], [0.0])))  # clipped, not infinite

    def test_reliability_counts_and_ece(self):
        y, s = [1, 0, 1, 1], [0.9, 0.9, 0.1, 0.1]
        rows = m.reliability_table(y, s, n_bins=2)
        self.assertEqual([r[2] for r in rows], [2, 2])
        # low bin: mean score .1 vs 100% positive (gap .9); high bin: .9 vs 50% (gap .4)
        self.assertAlmostEqual(m.expected_calibration_error(y, s, n_bins=2), 0.5 * 0.9 + 0.5 * 0.4)
        with self.assertRaises(ValueError):
            m.reliability_table([1], [1.5])

    def test_rejects_bad_input(self):
        for bad in [([], []), ([1, 0], [0.5]), ([2], [0.5]), ([1], [float('nan')])]:
            with self.assertRaises(ValueError):
                m.average_precision(*bad)

    def test_matches_scikit_learn_when_installed(self):
        try:
            from sklearn import metrics as sk
        except ImportError:
            self.skipTest('scikit-learn not installed')
        rng = random.Random(3)
        for _ in range(20):
            y = [int(rng.random() < 0.3) for _ in range(40)]
            s = [round(rng.random(), 1) for _ in range(40)]  # rounding forces ties
            if sum(y) == 0:
                continue
            self.assertAlmostEqual(m.average_precision(y, s), sk.average_precision_score(y, s))
            p, r, _ = sk.precision_recall_curve(y, s)
            self.assertAlmostEqual(m.pr_auc_trapezoid(y, s), sk.auc(r, p))
            self.assertAlmostEqual(m.brier_score(y, s), sk.brier_score_loss(y, s))
            # scikit-learn clips at machine epsilon; match it so scores of exactly 0 or 1 agree
            self.assertAlmostEqual(m.log_loss(y, s, eps=2.220446049250313e-16),
                                   sk.log_loss(y, s, labels=[0, 1]))


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        rng = random.Random(1)
        self.clusters = [c for c in 'ABCDEFGH' for _ in range(6)]
        self.y = [int(rng.random() < 0.4) for _ in self.clusters]
        self.s = [0.3 * a + rng.random() * 0.7 for a in self.y]

    def test_same_seed_same_answer_and_point_inside_interval(self):
        a = cluster_bootstrap(self.y, self.s, self.clusters, m.average_precision, n_boot=200, seed=5)
        b = cluster_bootstrap(self.y, self.s, self.clusters, m.average_precision, n_boot=200, seed=5)
        self.assertEqual(a, b)
        self.assertLessEqual(a['low'], a['point'] + 0.15)
        self.assertGreaterEqual(a['high'], a['point'] - 0.15)
        self.assertEqual(a['n_clusters'], 8)

    def test_resamples_without_positives_are_counted_not_hidden(self):
        y = [1, 0, 0, 0, 0, 0]
        out = cluster_bootstrap(y, [0.9, 0.1, 0.2, 0.1, 0.3, 0.2], list('AABBCC'),
                                m.average_precision, n_boot=300, seed=2)
        self.assertGreater(out['n_skipped'], 0)
        self.assertEqual(out['n_skipped'] + out['n_valid'], 300)

    def test_paired_difference_of_identical_scores_is_zero(self):
        out = paired_difference(self.y, self.s, self.s, self.clusters, m.average_precision, n_boot=100)
        self.assertEqual((out['point'], out['low'], out['high']), (0.0, 0.0, 0.0))

    def test_needs_two_clusters(self):
        with self.assertRaises(ValueError):
            cluster_bootstrap([1, 0], [0.5, 0.4], ['A', 'A'], m.average_precision)


if __name__ == '__main__':
    unittest.main()
