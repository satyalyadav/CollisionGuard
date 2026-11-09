"""
Prediction baselines for CollisionGuard where each baseline takes two task descriptions (strings available before coding starts)
and produces a conflict risk score between 0 and 1.

Baselines implemented:
    1. TF-IDF cosine similarity (unsupervised lexical overlap)
    2. Logistic regression over hand-crafted pre-execution features (supervised)
"""

import re
import math
from collections import Counter
from typing import List, Tuple, Optional


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _dot(a: dict, b: dict) -> float:
    return sum(a[k] * b.get(k, 0.0) for k in a)


def _norm(v: dict) -> float:
    return math.sqrt(sum(x * x for x in v.values())) or 1e-12


def _cosine(a: dict, b: dict) -> float:
    return _dot(a, b) / (_norm(a) * _norm(b))


# TF-IDF Cosine Similarity Baseline

class TfidfBaseline:
    """
    Unsupervised baseline: build a TF-IDF vocabulary from a small list of
    task descriptions, and then score each pair by the cosine similarity of
    their TF-IDF vectors.
    """

    def __init__(self):
        self.idf: dict = {}
        self.vocab_size: int = 0

    def fit(self, documents: List[str]) -> "TfidfBaseline":
        """Compute IDF weights from a corpus of task descriptions."""
        n = len(documents)
        if n == 0:
            return self
        df: Counter = Counter()
        for doc in documents:
            df.update(set(_tokenize(doc)))
        # Standard smoothed IDF: log((1 + n) / (1 + df)) + 1
        self.idf = {
            term: math.log((1 + n) / (1 + count)) + 1
            for term, count in df.items()
        }
        self.vocab_size = len(self.idf)
        return self

    def _tfidf_vector(self, text: str) -> dict:
        tokens = _tokenize(text)
        tf = Counter(tokens)
        total = len(tokens) or 1
        return {
            term: (count / total) * self.idf.get(term, 1.0)
            for term, count in tf.items()
        }

    def predict_score(self, task_a: str, task_b: str) -> float:
        """Return cosine similarity of TF-IDF vectors ∈ [0, 1]."""
        va = self._tfidf_vector(task_a)
        vb = self._tfidf_vector(task_b)
        sim = _cosine(va, vb)
        return max(0.0, min(1.0, sim))


# Logistic Regression Baseline

class FeatureExtractor:
    """
    Extract hand-crafted pair-level features that are available before
    either agent starts coding.
    """

    CODE_KEYWORDS = frozenset([
        "file", "test", "fix", "bug", "add", "update", "remove", "delete",
        "refactor", "config", "error", "class", "function", "method",
        "import", "module", "api", "endpoint", "database", "schema",
        "migration", "route", "handler", "component", "template",
        "style", "css", "html", "script", "build", "deploy", "ci",
        "lint", "format", "type", "interface", "model", "view",
        "controller", "service", "util", "helper", "constant",
        "variable", "parameter", "return", "async", "sync",
        "cache", "log", "debug", "warning", "exception",
    ])

    FEATURE_NAMES = [
        "tfidf_cosine",
        "shared_tokens",
        "len_ratio",
        "same_repo",
        "task_a_len",
        "task_b_len",
        "keyword_overlap",
    ]

    def __init__(self):
        self.tfidf = TfidfBaseline()
        self._fitted = False

    def fit(self, documents: List[str]) -> "FeatureExtractor":
        """Fit the IDF component on a corpus of task descriptions."""
        self.tfidf.fit(documents)
        self._fitted = True
        return self

    def extract(
        self,
        task_a: str,
        task_b: str,
        repo_a: str = "",
        repo_b: str = "",
    ) -> List[float]:
        tokens_a = set(_tokenize(task_a))
        tokens_b = set(_tokenize(task_b))

        # TF-IDF cosine
        tfidf_cos = self.tfidf.predict_score(task_a, task_b) if self._fitted else 0.0

        union = tokens_a | tokens_b
        shared = len(tokens_a & tokens_b) / len(union) if union else 0.0

        la, lb = len(tokens_a) or 1, len(tokens_b) or 1
        len_ratio = min(la, lb) / max(la, lb)

        same = 1.0 if repo_a and repo_b and repo_a.lower() == repo_b.lower() else 0.0

        kw_a = tokens_a & self.CODE_KEYWORDS
        kw_b = tokens_b & self.CODE_KEYWORDS
        kw_overlap = len(kw_a & kw_b)

        return [tfidf_cos, shared, len_ratio, same, float(la), float(lb), float(kw_overlap)]


class LogisticRegressionBaseline:
    """
    Supervised baseline: logistic regression over hand-crafted features.
    """

    def __init__(self):
        self._model = None
        self.extractor = FeatureExtractor()

    def fit(
        self,
        pairs: List[Tuple[str, str]],
        labels: List[int],
        repos: Optional[List[Tuple[str, str]]] = None,
    ) -> "LogisticRegressionBaseline":
        """
        Train the logistic regression.

        Parameters
        ----------
        pairs : list of (task_a, task_b) tuples
        labels : list of int (1 = conflict, 0 = clean)
        repos : optional list of (repo_a, repo_b) tuples
        """
        from sklearn.linear_model import LogisticRegression

        # Fit IDF on all task texts
        all_docs = [t for pair in pairs for t in pair]
        self.extractor.fit(all_docs)

        X = []
        for i, (ta, tb) in enumerate(pairs):
            ra, rb = (repos[i] if repos else ("", ""))
            X.append(self.extractor.extract(ta, tb, ra, rb))

        self._model = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )
        self._model.fit(X, labels)
        return self

    def predict_proba(
        self,
        task_a: str,
        task_b: str,
        repo_a: str = "",
        repo_b: str = "",
    ) -> float:
        if self._model is None:
            raise RuntimeError("Model not fitted.  Call fit() first.")
        feats = self.extractor.extract(task_a, task_b, repo_a, repo_b)
        proba = self._model.predict_proba([feats])[0]
        idx = list(self._model.classes_).index(1)
        return float(proba[idx])

    def predict_scores(
        self,
        pairs: List[Tuple[str, str]],
        repos: Optional[List[Tuple[str, str]]] = None,
    ) -> List[float]:
        return [
            self.predict_proba(
                ta, tb,
                *(repos[i] if repos else ("", "")),
            )
            for i, (ta, tb) in enumerate(pairs)
        ]
