"""Training, persistence, scoring, and explanations for the product model."""

import bisect

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import reason_text


def fit(X, y, C=0.5):
    vectorizer = DictVectorizer(sparse=False)
    matrix = vectorizer.fit_transform(X)
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=2000, C=C),
    )
    model.fit(matrix, y)
    return model, vectorizer


def raw_scores(model, vectorizer, rows):
    if not rows:
        return []
    matrix = vectorizer.transform(rows)
    return [float(value) for value in model.predict_proba(matrix)[:, 1]]


def save_artifact(path, model, vectorizer, calibrator, oof_scores, metrics, metadata):
    ordered = sorted(float(value) for value in oof_scores)
    artifact = {
        "format": "collisionguard-product-1",
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
    if artifact.get("format") != "collisionguard-product-1":
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


def contributions(artifact, features, limit=4):
    """Return the largest standardized logistic contributions for one pair."""
    vectorizer = artifact["vectorizer"]
    model = artifact["model"]
    names = vectorizer.get_feature_names_out()
    row = vectorizer.transform([features])
    row = row.toarray()[0] if hasattr(row, "toarray") else row[0]
    scaler = model.named_steps["standardscaler"]
    values = (row - scaler.mean_) / scaler.scale_
    coefficients = model.named_steps["logisticregression"].coef_[0]
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
