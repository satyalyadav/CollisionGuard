"""Training, persistence, scoring, and explanations for the product model."""

import bisect

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from .features import reason_text

FORMAT = "collisionguard-product-2"
LEGACY_FORMAT = "collisionguard-product-1"


class EnsembleClassifier:
    """Equal-weight average of a linear model and an extremely randomized forest.

    The two components see the same dense one-hot feature matrix. Averaging
    their raw conflict probabilities improved average precision and the top
    decile over either component alone on the natural cohort.
    """

    def __init__(self, logistic, trees):
        self.logistic = logistic
        self.trees = trees

    def predict_proba(self, matrix):
        linear = self.logistic.predict_proba(matrix)[:, 1]
        forest = self.trees.predict_proba(matrix)[:, 1]
        averaged = (linear + forest) / 2.0
        return np.column_stack([1.0 - averaged, averaged])


def fit(X, y, C=0.5):
    """Fit the ensemble and return (model, feature vectorizer)."""
    vectorizer = DictVectorizer(sparse=False)
    matrix = vectorizer.fit_transform(X)
    logistic = LogisticRegression(
        class_weight="balanced", max_iter=5000, C=C)
    logistic.fit(matrix, y)
    trees = ExtraTreesClassifier(
        n_estimators=800,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced",
        random_state=0,
        n_jobs=2,
    )
    trees.fit(matrix, y)
    return EnsembleClassifier(logistic, trees), vectorizer


def raw_scores(model, vectorizer, rows):
    if not rows:
        return []
    matrix = vectorizer.transform(rows)
    return [float(value) for value in model.predict_proba(matrix)[:, 1]]


def save_artifact(path, model, vectorizer, calibrator, oof_scores, metrics, metadata):
    ordered = sorted(float(value) for value in oof_scores)
    artifact = {
        "format": FORMAT,
        "model": model,
        "vectorizer": vectorizer,
        "calibrator": calibrator,
        "oof_scores": ordered,
        "metrics": metrics,
        "metadata": metadata,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)
    return artifact


def load_artifact(path):
    artifact = joblib.load(path)
    if artifact.get("format") not in (FORMAT, LEGACY_FORMAT):
        raise ValueError("unrecognized model artifact format")
    return artifact


def score(artifact, features):
    raw = raw_scores(artifact["model"], artifact["vectorizer"], [features])[0]
    calibrated = float(artifact["calibrator"].predict([raw])[0])
    ordered = artifact["oof_scores"]
    percentile = bisect.bisect_right(ordered, raw) / len(ordered) if ordered else 0.5
    if percentile >= 0.90:
        band = "high"
    elif percentile >= 0.70:
        band = "elevated"
    else:
        band = "low"
    return {
        "raw_score": raw,
        "calibrated_probability": calibrated,
        "percentile": percentile,
        "band": band,
    }


def _linear_part(artifact):
    model = artifact["model"]
    if isinstance(model, EnsembleClassifier):
        return model.logistic
    return model.named_steps["logisticregression"]


def contributions(artifact, features, limit=4):
    """Return the largest logistic contributions for one pair.

    The forest contributes to the score but has no signed per-feature
    decomposition here. The linear component supplies the explanatory view.
    Legacy v0.1 artifacts standardized their inputs, so undo that scaling
    before multiplying by the coefficients.
    """
    vectorizer = artifact["vectorizer"]
    model = artifact["model"]
    estimator = _linear_part(artifact)
    names = vectorizer.get_feature_names_out()
    row = vectorizer.transform([features])
    row = row.toarray()[0] if hasattr(row, "toarray") else row[0]
    if not isinstance(model, EnsembleClassifier):
        scaler = model.named_steps["standardscaler"]
        row = (row - scaler.mean_) / scaler.scale_
    coefficients = estimator.coef_[0]
    scored = [(float(coef * value), name, value)
              for coef, name, value in zip(coefficients, names, row) if value]
    scored.sort(key=lambda item: -abs(item[0]))
    out = []
    for value, name, _ in scored[:limit]:
        out.append({
            "reason": reason_text(name),
            "direction": "raises" if value > 0 else "lowers",
            "weight": value,
        })
    return out
