"""Tests for the CollisionGuard product package."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from collisionguard.cli import build_report
from collisionguard.features import normalize_agent, pair_features, reason_text
from collisionguard.files import (language_from_files, list_repo_files,
                                  predict_files, shared_directories, shared_files)
from collisionguard.model import (
    SigmoidCalibrator, contributions, fit, load_artifact, save_artifact, score)
import export_natural_cohort_hf as hf


class FeatureTests(unittest.TestCase):
    def test_pair_features_marks_task_types(self):
        features = pair_features("Add an API endpoint", "Fix the documentation",
                                 language="Python", tree_files=100, same_agent=True)
        self.assertEqual(features["type_api"], 1)
        self.assertEqual(features["type_docs"], 1)
        self.assertEqual(features["both_api"], 0)
        self.assertEqual(features["lang"], "Python")
        self.assertEqual(features["same"], 1)
        self.assertGreater(features["tree"], 4)

    def test_agent_aliases(self):
        self.assertEqual(normalize_agent("codex"), "OpenAI_Codex")
        self.assertEqual(normalize_agent("Claude Code"), "Claude_Code")
        self.assertEqual(normalize_agent("github-copilot"), "Copilot")
        self.assertEqual(normalize_agent(""), "unknown")

    def test_pair_features_handles_empty_text(self):
        features = pair_features("", "", language=None, tree_files=0)
        self.assertEqual(features["lang"], "unknown")
        self.assertEqual(features["la"], 0.0)
        self.assertEqual(features["type_api"], 0)


class FileTests(unittest.TestCase):
    def test_language_from_files(self):
        self.assertEqual(language_from_files(["a.py", "b.py", "c.ts"]), "Python")
        self.assertEqual(language_from_files(["a.ts", "b.ts", "c.py"]), "TypeScript")
        self.assertEqual(language_from_files(["README.md"]), "unknown")

    def test_predict_files_prefers_matching_name(self):
        files = ["src/parser.py", "src/cache.py", "docs/readme.md"]
        ranked = predict_files("fix parser crash", files, top_k=1)
        self.assertEqual(ranked[0][0], "src/parser.py")
        self.assertGreater(ranked[0][1], 0)

    def test_shared_helpers(self):
        self.assertEqual(shared_files(["a.py", "b.py"], ["b.py", "c.py"]), ["b.py"])
        self.assertEqual(shared_directories(["src/a.py"], ["src/b.py"]), ["src"])

    def test_list_repo_files_on_current_checkout(self):
        paths = list_repo_files(ROOT)
        self.assertIn("README.md", paths)

    def test_list_repo_files_on_plain_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "a.py").write_text("x")
            Path(temp, "sub").mkdir()
            Path(temp, "sub", "b.txt").write_text("y")
            self.assertEqual(sorted(list_repo_files(temp)), ["a.py", "sub/b.txt"])
        with self.assertRaises(ValueError):
            list_repo_files("/does/not/exist")


class ModelTests(unittest.TestCase):
    def test_fit_score_and_contributions(self):
        rows = []
        labels = []
        for index in range(30):
            features = pair_features("Add API endpoint" if index % 2 else "Fix docs",
                                     "Update API client" if index % 2 else "Update docs",
                                     language="Python", tree_files=10,
                                     same_agent=False)
            rows.append(features)
            labels.append(index % 2)
        model, vectorizer = fit(rows, labels)
        result = score({"model": model, "vectorizer": vectorizer,
                        "calibrator": _Identity(), "oof_scores": [0.1, 0.5, 0.9]},
                       rows[0])
        self.assertIn(result["band"], ("low", "elevated", "high"))
        reasons = contributions({"model": model, "vectorizer": vectorizer}, rows[0])
        self.assertTrue(reasons)
        self.assertIn("reason", reasons[0])

    def test_ensemble_averages_the_two_components(self):
        rows = []
        labels = []
        for index in range(40):
            rows.append(pair_features("Add API endpoint" if index % 2 else "Fix docs",
                                      "Update API client" if index % 2 else "Update docs",
                                      language="Python", tree_files=10,
                                      same_agent=bool(index % 3)))
            labels.append(index % 2)
        model, vectorizer = fit(rows, labels)
        matrix = vectorizer.transform(rows)
        combined = model.predict_proba(matrix)[:, 1]
        linear = model.logistic.predict_proba(matrix)[:, 1]
        forest = model.trees.predict_proba(matrix)[:, 1]
        for value, first, second in zip(combined, linear, forest):
            self.assertAlmostEqual(value, (first + second) / 2.0, places=12)

    def test_sigmoid_calibrator_stays_in_range(self):
        calibrator = SigmoidCalibrator().fit([0.0, 0.1, 0.8, 0.9], [0, 0, 1, 1])
        values = calibrator.predict([0.0, 0.5, 1.0])
        self.assertTrue(all(0.0 < value < 1.0 for value in values))
        self.assertLess(values[0], values[2])

    def test_agent_reason_text(self):
        self.assertEqual(reason_text("agent_pair=OpenAI_Codex+Copilot"),
                         "agent pairing OpenAI_Codex + Copilot")
        self.assertEqual(reason_text("agent_a=Copilot"), "agent A is Copilot")

    def test_artifact_round_trip(self):
        rows = [pair_features("Add API endpoint", "Update API client",
                              language="Python", tree_files=10)] * 20
        labels = [1, 0] * 10
        model, vectorizer = fit(rows, labels)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.joblib"
            save_artifact(path, model, vectorizer, _Identity(), [0.1, 0.9],
                          {"pairs": 20}, {"version": "test"})
            artifact = load_artifact(path)
            self.assertEqual(artifact["metadata"]["version"], "test")
            result = score(artifact, rows[0])
            self.assertIn("calibrated_probability", result)


class ExportHelperTests(unittest.TestCase):
    def test_splits(self):
        self.assertEqual(hf._split(4), "test")
        self.assertEqual(hf._split(3), "validation")
        self.assertEqual(hf._split(2), "train")

    def test_title_similarity(self):
        pair = {"title_a": "Fix parser", "title_b": "Fix parser"}
        self.assertEqual(hf._title_similarity(pair), 1.0)
        pair = {"title_a": "Add cache", "title_b": "Remove docs"}
        self.assertEqual(hf._title_similarity(pair), 0.0)

    def test_strict_issue(self):
        pair = {
            "issue_source_a": "body", "issue_source_b": "body",
            "issue_created_a": "2026-01-01T00:00:00Z",
            "issue_created_b": "2026-01-02T00:00:00Z",
            "created_a": "2026-01-03T00:00:00Z",
            "created_b": "2026-01-04T00:00:00Z",
        }
        self.assertTrue(hf._strict_issue(pair))
        self.assertFalse(hf._strict_issue({**pair, "issue_source_b": "timeline"}))


class _Identity:
    def predict(self, values):
        return list(values)


@unittest.skipUnless((ROOT / "models" / "collisionguard-v0.2.joblib").is_file(),
                     "product model artifact is not trained")
class CliIntegrationTests(unittest.TestCase):
    def test_build_report_on_this_repo(self):
        report = build_report(ROOT, "Add a merge-risk CLI", "Improve the README",
                              agent_a="codex", agent_b="copilot")
        self.assertEqual(report["risk"]["band"], report["risk"]["band"].lower())
        self.assertTrue(report["likely_files"]["a"])
        self.assertEqual(report["repo"], str(ROOT))
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
