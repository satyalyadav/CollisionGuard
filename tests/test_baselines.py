"""
Tests for prediction baselines.

Synthetic data used here
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from baselines import (
    TfidfBaseline,
    FeatureExtractor,
    LogisticRegressionBaseline,
    _tokenize,
    _cosine,
)


TASKS = [
    "Fix the login form validation error when users enter special characters",
    "Refactor the login page CSS to match the new design system",
    "Add rate limiting to the API endpoint to prevent abuse",
    "Update the API endpoint to support pagination with query parameters",
    "Add a verbose flag to the build command for detailed output",
    "Implement a new deploy subcommand that packages build artifacts",
    "Fix the config parser to handle nested YAML keys with dots",
    "Fix the config parser to support environment variable interpolation",
]

# Pairs that are expected to be more similar
SIMILAR_PAIR = (TASKS[6], TASKS[7])
DIFFERENT_PAIR = (TASKS[0], TASKS[4])


class TestTokenize(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_tokenize("Hello World"), ["hello", "world"])

    def test_punctuation(self):
        tokens = _tokenize("Fix bug #123 in module.py!")
        self.assertIn("fix", tokens)
        self.assertIn("bug", tokens)
        self.assertIn("123", tokens)
        self.assertIn("module", tokens)
        self.assertIn("py", tokens)

    def test_empty(self):
        self.assertEqual(_tokenize(""), [])
        self.assertEqual(_tokenize("   "), [])

    def test_underscores_preserved(self):
        tokens = _tokenize("my_function_name")
        self.assertIn("my_function_name", tokens)


class TestCosine(unittest.TestCase):
    def test_identical(self):
        v = {"a": 1.0, "b": 2.0}
        self.assertAlmostEqual(_cosine(v, v), 1.0, places=6)

    def test_orthogonal(self):
        a = {"x": 1.0}
        b = {"y": 1.0}
        self.assertAlmostEqual(_cosine(a, b), 0.0, places=6)

    def test_empty(self):
        self.assertIsInstance(_cosine({}, {}), float)


class TestTfidfBaseline(unittest.TestCase):
    def setUp(self):
        self.model = TfidfBaseline().fit(TASKS)

    def test_fit_populates_idf(self):
        self.assertGreater(self.model.vocab_size, 0)
        self.assertIn("fix", self.model.idf)

    def test_score_range(self):
        score = self.model.predict_score(TASKS[0], TASKS[1])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_identical_texts_score_one(self):
        score = self.model.predict_score(TASKS[0], TASKS[0])
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_similar_higher_than_different(self):
        sim_score = self.model.predict_score(*SIMILAR_PAIR)
        diff_score = self.model.predict_score(*DIFFERENT_PAIR)
        self.assertGreater(sim_score, diff_score)

    def test_symmetry(self):
        s1 = self.model.predict_score(TASKS[0], TASKS[1])
        s2 = self.model.predict_score(TASKS[1], TASKS[0])
        self.assertAlmostEqual(s1, s2, places=10)

    def test_empty_corpus(self):
        model = TfidfBaseline().fit([])
        score = model.predict_score("hello", "world")
        self.assertIsInstance(score, float)

    def test_unseen_words(self):
        score = self.model.predict_score(
            "quantum entanglement photon", "blockchain cryptocurrency mining"
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestFeatureExtractor(unittest.TestCase):
    def setUp(self):
        self.fe = FeatureExtractor()
        self.fe.fit(TASKS)

    def test_feature_count(self):
        feats = self.fe.extract(TASKS[0], TASKS[1])
        self.assertEqual(len(feats), len(FeatureExtractor.FEATURE_NAMES))

    def test_feature_types(self):
        feats = self.fe.extract(TASKS[0], TASKS[1])
        for f in feats:
            self.assertIsInstance(f, float)

    def test_same_repo(self):
        feats = self.fe.extract(TASKS[0], TASKS[1], "org/repo", "org/repo")
        same_repo_idx = FeatureExtractor.FEATURE_NAMES.index("same_repo")
        self.assertEqual(feats[same_repo_idx], 1.0)

    def test_different_repo(self):
        feats = self.fe.extract(TASKS[0], TASKS[1], "org/repo-a", "org/repo-b")
        same_repo_idx = FeatureExtractor.FEATURE_NAMES.index("same_repo")
        self.assertEqual(feats[same_repo_idx], 0.0)

    def test_shared_tokens_range(self):
        feats = self.fe.extract(TASKS[0], TASKS[1])
        shared_idx = FeatureExtractor.FEATURE_NAMES.index("shared_tokens")
        self.assertGreaterEqual(feats[shared_idx], 0.0)
        self.assertLessEqual(feats[shared_idx], 1.0)

    def test_keyword_overlap_nonneg(self):
        feats = self.fe.extract(TASKS[0], TASKS[1])
        kw_idx = FeatureExtractor.FEATURE_NAMES.index("keyword_overlap")
        self.assertGreaterEqual(feats[kw_idx], 0.0)


class TestLogisticRegressionBaseline(unittest.TestCase):
    def setUp(self):
        self.pairs = [
            (TASKS[0], TASKS[1]),
            (TASKS[2], TASKS[3]),
            (TASKS[4], TASKS[5]),
            (TASKS[6], TASKS[7]),
        ]
        self.labels = [0, 1, 0, 1]
        self.repos = [("r/a", "r/a")] * 4

    def test_fit_and_predict(self):
        model = LogisticRegressionBaseline()
        model.fit(self.pairs, self.labels, self.repos)
        score = model.predict_proba(TASKS[0], TASKS[1], "r/a", "r/a")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_predict_before_fit_raises(self):
        model = LogisticRegressionBaseline()
        with self.assertRaises(RuntimeError):
            model.predict_proba("a", "b")

    def test_predict_scores_length(self):
        model = LogisticRegressionBaseline()
        model.fit(self.pairs, self.labels, self.repos)
        scores = model.predict_scores(self.pairs, self.repos)
        self.assertEqual(len(scores), len(self.pairs))

    def test_all_scores_valid(self):
        model = LogisticRegressionBaseline()
        model.fit(self.pairs, self.labels, self.repos)
        scores = model.predict_scores(self.pairs, self.repos)
        for s in scores:
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_balanced_classes(self):
        """With balanced class weight, the model should not predict all-zero or all-one."""
        model = LogisticRegressionBaseline()
        model.fit(self.pairs, self.labels, self.repos)
        scores = model.predict_scores(self.pairs, self.repos)
        self.assertGreater(max(scores) - min(scores), 0.001)


class TestRunBaselineModule(unittest.TestCase):
    """Smoke test: import and run the main module functions."""

    def test_synthetic_data_loads(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from run_baselines import SYNTHETIC_FEATURES, SYNTHETIC_TARGETS, join_data

        pairs, labels, repos, ids = join_data(SYNTHETIC_FEATURES, SYNTHETIC_TARGETS)
        self.assertEqual(len(pairs), 8)
        self.assertEqual(sum(labels), 4)
        self.assertEqual(len(labels) - sum(labels), 4)

    def test_join_matches_ids(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from run_baselines import SYNTHETIC_FEATURES, SYNTHETIC_TARGETS, join_data

        pairs, labels, repos, ids = join_data(SYNTHETIC_FEATURES, SYNTHETIC_TARGETS)
        self.assertEqual(ids, [f["instance_id"] for f in SYNTHETIC_FEATURES])


if __name__ == "__main__":
    unittest.main()
