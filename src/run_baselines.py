"""
Load the private feature/target JSON files and run baselines.

Usage
-----
    cd CollisionGuard
    uv run python src/run_baselines.py

If the private data files are absent it falls back to built-in synthetic
examples so the pipeline can be verified without Satyal's local data.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baselines import TfidfBaseline, LogisticRegressionBaseline


ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "data" / "private" / "parallact" / "recovery" / "features.json"
TARGETS = ROOT / "data" / "private" / "parallact" / "recovery" / "targets.json"


# Synthetic data 

SYNTHETIC_FEATURES = [
    {
        "instance_id": "synth-001",
        "repo": "example/webapp",
        "base_commit": "abc123",
        "task_a": "Fix the login form validation error when users enter special characters in the password field. Update the authentication handler to properly escape input.",
        "task_b": "Refactor the login page CSS to match the new design system. Update button styles and form layout to use the shared component library.",
    },
    {
        "instance_id": "synth-002",
        "repo": "example/webapp",
        "base_commit": "abc123",
        "task_a": "Add rate limiting to the API endpoint /api/v1/users to prevent abuse. Implement a sliding window counter using Redis.",
        "task_b": "Update the API endpoint /api/v1/users to support pagination. Add query parameters for page and page_size with proper validation.",
    },
    {
        "instance_id": "synth-003",
        "repo": "example/cli-tool",
        "base_commit": "def456",
        "task_a": "Add a --verbose flag to the build command that prints detailed compilation output including file paths and timings.",
        "task_b": "Implement a new 'deploy' subcommand that packages the build artifacts and uploads them to the configured remote server.",
    },
    {
        "instance_id": "synth-004",
        "repo": "example/cli-tool",
        "base_commit": "def456",
        "task_a": "Fix the configuration file parser to handle nested YAML keys with dots in their names. Update the config module and its tests.",
        "task_b": "Fix the configuration file parser to support environment variable interpolation in YAML values. Add a preprocessor to the config module.",
    },
    {
        "instance_id": "synth-005",
        "repo": "example/data-pipeline",
        "base_commit": "ghi789",
        "task_a": "Optimize the ETL batch processor to use connection pooling for database writes. Update the database adapter and connection manager.",
        "task_b": "Add CSV export functionality to the ETL pipeline output stage. Implement a new CSVWriter class in the output module.",
    },
    {
        "instance_id": "synth-006",
        "repo": "example/data-pipeline",
        "base_commit": "ghi789",
        "task_a": "Refactor the data validation module to use a schema-based approach. Replace inline checks with JSON schema validation in the ingestion step.",
        "task_b": "Add data validation rules for the new 'address' field type in the ingestion pipeline. Update the validation module and schema definitions.",
    },
    {
        "instance_id": "synth-007",
        "repo": "example/frontend",
        "base_commit": "jkl012",
        "task_a": "Implement dark mode support across all dashboard components. Add a theme toggle to the settings panel and update the global stylesheet.",
        "task_b": "Redesign the dashboard layout to be responsive on mobile devices. Update the grid system and component layouts in the global stylesheet.",
    },
    {
        "instance_id": "synth-008",
        "repo": "example/frontend",
        "base_commit": "jkl012",
        "task_a": "Add unit tests for the user profile component. Test the form validation, avatar upload, and preference saving flows.",
        "task_b": "Implement the notification preferences panel in the user settings page. Add toggle switches for email, push, and in-app notifications.",
    },
]

# Synthetic labels: pairs 2, 4, 6, 7 conflict (tasks touch same files/modules)
SYNTHETIC_TARGETS = [
    {"instance_id": "synth-001", "status": "complete", "label": "clean"},
    {"instance_id": "synth-002", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-003", "status": "complete", "label": "clean"},
    {"instance_id": "synth-004", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-005", "status": "complete", "label": "clean"},
    {"instance_id": "synth-006", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-007", "status": "complete", "label": "conflict"},
    {"instance_id": "synth-008", "status": "complete", "label": "clean"},
]


def load_data():
    """Load features and targets, falling back to synthetic data."""
    if FEATURES.exists() and TARGETS.exists():
        features = json.loads(FEATURES.read_text())
        targets = json.loads(TARGETS.read_text())
        source = "private (real ParallACT data)"
    else:
        features = SYNTHETIC_FEATURES
        targets = SYNTHETIC_TARGETS
        source = "synthetic (built-in examples)"
    return features, targets, source


def join_data(features, targets):
    """Join features and targets on instance_id, return pairs and labels."""
    label_map = {t["instance_id"]: t["label"] for t in targets}
    pairs = []
    labels = []
    repos = []
    ids = []
    for f in features:
        iid = f["instance_id"]
        if iid not in label_map:
            continue
        pairs.append((f["task_a"], f["task_b"]))
        labels.append(1 if label_map[iid] == "conflict" else 0)
        repos.append((f["repo"], f["repo"]))  # same repo for both tasks
        ids.append(iid)
    return pairs, labels, repos, ids


def run_tfidf_baseline(pairs, labels, ids):
    """Run the TF-IDF similarity baseline."""
    print("\n" + "=" * 60)
    print("BASELINE 1: TF-IDF Cosine Similarity")
    print("=" * 60)

    all_docs = [t for pair in pairs for t in pair]
    model = TfidfBaseline().fit(all_docs)

    print(f"\nVocabulary size: {model.vocab_size}")
    print(f"\n{'ID':<45} {'Score':>6}  {'Label':>8}")
    print("-" * 65)

    scores = []
    for i, (ta, tb) in enumerate(pairs):
        score = model.predict_score(ta, tb)
        scores.append(score)
        label_str = "CONFLICT" if labels[i] else "clean"
        marker = " ←" if labels[i] else ""
        print(f"{ids[i]:<45} {score:>6.3f}  {label_str:>8}{marker}")

    return scores


def run_logistic_baseline(pairs, labels, repos, ids):
    """Run the logistic regression baseline."""
    print("\n" + "=" * 60)
    print("BASELINE 2: Logistic Regression (leave-one-out)")
    print("=" * 60)

    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("\n  ⚠ Skipped: scikit-learn not installed")
        return None

    if len(pairs) < 4:
        print("\n  ⚠ Too few examples for logistic regression demo")
        return None

    # Leave-one-out cross-validation 
    scores = [0.0] * len(pairs)
    print(f"\n{'ID':<45} {'Score':>6}  {'Label':>8}")
    print("-" * 65)

    for i in range(len(pairs)):
        train_pairs = [pairs[j] for j in range(len(pairs)) if j != i]
        train_labels = [labels[j] for j in range(len(pairs)) if j != i]
        train_repos = [repos[j] for j in range(len(pairs)) if j != i]

        if len(set(train_labels)) < 2:
            scores[i] = 0.5
            continue

        model = LogisticRegressionBaseline()
        model.fit(train_pairs, train_labels, train_repos)
        scores[i] = model.predict_proba(pairs[i][0], pairs[i][1], repos[i][0], repos[i][1])

    for i in range(len(pairs)):
        label_str = "CONFLICT" if labels[i] else "clean"
        marker = " ←" if labels[i] else ""
        print(f"{ids[i]:<45} {scores[i]:>6.3f}  {label_str:>8}{marker}")

    return scores


def main():
    features, targets, source = load_data()
    print(f"Data source: {source}")
    print(f"Loaded {len(features)} features, {len(targets)} targets")

    pairs, labels, repos, ids = join_data(features, targets)
    n_conflict = sum(labels)
    n_clean = len(labels) - n_conflict
    print(f"Joined pairs: {len(pairs)} ({n_conflict} conflict, {n_clean} clean)")

    tfidf_scores = run_tfidf_baseline(pairs, labels, ids)
    logistic_scores = run_logistic_baseline(pairs, labels, repos, ids)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nDataset: {len(pairs)} pairs ({n_conflict} conflict, {n_clean} clean)")
    print(f"Conflict prevalence: {n_conflict / len(pairs):.1%}")

    # Simple separation quality: average score for conflicts vs cleans
    for name, scores in [("TF-IDF", tfidf_scores), ("LogReg", logistic_scores)]:
        if scores is None:
            continue
        avg_conflict = sum(s for s, l in zip(scores, labels) if l == 1) / max(n_conflict, 1)
        avg_clean = sum(s for s, l in zip(scores, labels) if l == 0) / max(n_clean, 1)
        print(f"\n  {name}:")
        print(f"    Mean score (conflict): {avg_conflict:.3f}")
        print(f"    Mean score (clean):    {avg_clean:.3f}")
        print(f"    Separation (Δ):        {avg_conflict - avg_clean:+.3f}")


if __name__ == "__main__":
    main()
