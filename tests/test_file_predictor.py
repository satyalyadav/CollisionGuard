
import unittest

from scripts.file_predictor import (
    predict_files,
    predict_files_tfidf,
    tokenize,
    calculate_file_overlap
)


class TestFilePredictor(unittest.TestCase):

    def test_overlap_threshold_filters_low_scores(self):
        files = [
            "app/auth.py",
            "tests/test_auth.py",
            "app/database.py",
            "app/security.py",
        ]

        result = calculate_file_overlap(
            "Fix JWT authentication bug",
            "Update authentication tests",
            files,
            top_k=2,
            min_similarity=0.1,
        )

        for _, score in result["task_a_files"]:
            self.assertGreaterEqual(score, 0.1)

        for _, score in result["task_b_files"]:
            self.assertGreaterEqual(score, 0.1)

    def test_overlap_invalid_threshold(self):
        with self.assertRaises(ValueError):
            calculate_file_overlap(
                "Fix auth",
                "Update tests",
                ["app/auth.py"],
                min_similarity=1.5,
            )


    def test_file_overlap(self):
        files = [
            "app/auth.py",
            "app/security.py",
            "tests/test_auth.py",
            "app/database.py",
        ]

        result = calculate_file_overlap(
            "Fix JWT authentication",
            "Update authentication tests",
            files,
            top_k=2,
        )

        self.assertEqual(
            result["overlap_count"],
            len(result["shared_files"]),
        )

        self.assertGreaterEqual(
            result["jaccard_similarity"], 0.0
        )

        self.assertLessEqual(
            result["jaccard_similarity"], 1.0
        )

    def test_overlap_empty_files(self):
        result = calculate_file_overlap(
            "Fix auth",
            "Update tests",
            [],
        )

        self.assertEqual(result["shared_files"], [])
        self.assertEqual(result["overlap_count"], 0)
        self.assertEqual(result["jaccard_similarity"], 0.0)


    def test_tfidf_relevant_file_ranks_first(self):
        files = [
            "app/database.py",
            "app/auth.py",
            "app/config.py",
        ]

        predictions = predict_files_tfidf(
            "Fix JWT authentication in auth module",
            files,
            top_k=3,
        )

        self.assertEqual(predictions[0][0], "app/auth.py")

    def test_tfidf_top_k(self):
        files = [
            "app/auth.py",
            "app/database.py",
            "app/config.py",
        ]

        predictions = predict_files_tfidf(
            "Fix authentication",
            files,
            top_k=2,
        )

        self.assertEqual(len(predictions), 2)

    def test_tfidf_empty_files(self):
        predictions = predict_files_tfidf(
            "Fix auth bug",
            [],
        )

        self.assertEqual(predictions, [])

    def test_tfidf_empty_task(self):
        predictions = predict_files_tfidf(
            "",
            ["app/auth.py", "app/database.py"],
            top_k=2,
        )

        self.assertEqual(
            predictions,
            [
                ("app/auth.py", 0.0),
                ("app/database.py", 0.0),
            ],
        )


    def test_tokenize(self):
        tokens = tokenize("Fix JWT_auth.py")
        self.assertEqual(tokens, {"fix", "jwt", "auth", "py"})

    def test_relevant_file_ranks_first(self):
        files = [
            "app/database.py",
            "app/auth.py",
            "app/config.py",
        ]

        predictions = predict_files(
            "Fix auth bug",
            files,
            top_k=3,
        )

        self.assertEqual(predictions[0][0], "app/auth.py")

    def test_top_k(self):
        files = [
            "app/auth.py",
            "app/database.py",
            "app/config.py",
        ]

        predictions = predict_files(
            "Fix authentication",
            files,
            top_k=2,
        )

        self.assertEqual(len(predictions), 2)

    def test_empty_files(self):
        predictions = predict_files("Fix auth", [])
        self.assertEqual(predictions, [])

    def test_zero_top_k(self):
        predictions = predict_files(
            "Fix auth",
            ["app/auth.py"],
            top_k=0,
        )

        self.assertEqual(predictions, [])


if __name__ == "__main__":
    unittest.main()
